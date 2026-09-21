# Coletor horário, só faz IO, lê rotas, chama a REDEMET, grava observações e registra o resultado.

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.aisweb_cache import CacheAisweb
from app.clients.redemet_client import RedemetClient, descrever, mensagens_de
from app.core.coleta import AlvoColeta, JanelaColeta, alvos_de_coleta, janela_de_coleta
from app.core.observacoes import ResultadoDecisao, decidir_observacoes
from app.models.collection_log import CollectionLog
from app.models.observation import Observation
from app.models.route import Route

logger = logging.getLogger(__name__)


class HourlyCollector:
    def __init__(self, cliente: RedemetClient, sessao_factory,
                cache_aisweb: CacheAisweb | None = None) -> None:
        self._cliente = cliente
        self._sessao_factory = sessao_factory
        self._cache_aisweb = cache_aisweb

    async def coletar_todas_as_rotas(self) -> None:
        """Ponto de entrada do agendador, coleta para todas as rotas ativas."""
        agora = datetime.now(timezone.utc)
        janela = janela_de_coleta(agora)
        alvos = alvos_de_coleta(await self._ler_rotas_ativas())
        if not alvos:
            logger.info("nenhuma rota ativa; coleta encerrada")
            return
        logger.info("iniciando coleta", extra={"alvos": len(alvos)})
        await asyncio.gather(*(self._coletar(alvo, janela, agora) for alvo in alvos))
        logger.info("coleta finalizada", extra={"alvos": len(alvos)})

    async def coletar_rota(self, route_id: int, *icaos: str) -> None:
        """Coleta imediata para uma rota nova criada."""
        agora = datetime.now(timezone.utc)
        janela = janela_de_coleta(agora)
        for icao in icaos:
            await self._coletar(AlvoColeta(icao=icao, route_id=route_id), janela, agora)

    async def _ler_rotas_ativas(self) -> list[tuple[int, str, str]]:
        """Lê as rotas ativas como tuplas simples."""
        async with self._sessao_factory() as sessao:
            resultado = await sessao.execute(
                select(Route.id, Route.origem_icao, Route.destino_icao)
                .where(Route.ativa.is_(True)))
            return [tuple(linha) for linha in resultado.all()]

    async def _coletar(self, alvo: AlvoColeta, janela: JanelaColeta,
                       agora: datetime) -> None:
        """Busca, decide e grava para um aeródromo."""
        metar = await self._cliente.get_metar(alvo.icao, janela.inicio, janela.fim)
        taf = await self._cliente.get_taf(alvo.icao)
        janelas_sol, dentro_ctr_atz, classes_detectadas = await self._contexto_aisweb(
            alvo.icao, agora)
        decisao = decidir_observacoes(
            icao=alvo.icao, route_id=alvo.route_id,
            metares=mensagens_de(metar), tafs=mensagens_de(taf), agora=agora,
            janelas_sol=janelas_sol,
            dentro_ctr_atz_por_icao=(
                {alvo.icao: dentro_ctr_atz} if dentro_ctr_atz is not None else {}),
            classes_detectadas=classes_detectadas)
        resumo = f"METAR: {descrever(metar)}; TAF: {descrever(taf)}"
        await self._gravar(alvo, decisao, resumo)

    async def _contexto_aisweb(self, icao: str, agora: datetime):
        """Dados do VFR Especial e a classe já detectada, vazio se a AISWEB não estiver ligada."""
        if self._cache_aisweb is None:
            return {}, None, {}
        dia = agora.date()
        return (await self._cache_aisweb.janela_sol(icao, dia, dia),
               await self._cache_aisweb.dentro_ctr_atz(icao),
               await self._cache_aisweb.classes_detectadas_por_icao([icao]))

    async def _gravar(self, alvo: AlvoColeta, decisao: ResultadoDecisao,
                      resumo: str) -> None:
        async with self._sessao_factory() as sessao:
            try:
                if decisao.observacoes:
                    comando = insert(Observation).values(
                        [_para_linha(o) for o in decisao.observacoes]
                    ).on_conflict_do_nothing(constraint="uq_observation_natural_key")
                    await sessao.execute(comando)
                sessao.add(_log_de(alvo, decisao, resumo))
                await sessao.commit()
            except Exception:
                await sessao.rollback()
                logger.exception("falha ao gravar coleta de %s (rota %s)",
                                 alvo.icao, alvo.route_id)
                return
        _registrar_ignoradas(alvo, decisao)


def _para_linha(observacao) -> dict:
    """Converte a decisão pura em linha do ORM. A decisão pura não tem route_id, mas a linha do ORM precisa."""
    return {
        "route_id": observacao.route_id, "icao": observacao.icao, "tipo": observacao.tipo,
        "mensagem_bruta": observacao.mensagem_bruta, "teto_ft": observacao.teto_ft,
        "visibilidade_m": observacao.visibilidade_m,
        "status_operacional": observacao.status_operacional,
        "base_legal": observacao.base_legal, "recebimento": observacao.recebimento,
        "aviso_temporario": observacao.aviso_temporario,
    }


def _log_de(alvo: AlvoColeta, decisao: ResultadoDecisao, resumo: str) -> CollectionLog:
    """Registro da coleta que distingue 'sem dados' de 'falha na origem'."""
    sucesso = bool(decisao.observacoes)
    erro = None if sucesso else resumo
    return CollectionLog(icao=alvo.icao, sucesso=sucesso, tentativas=1, erro=erro)


def _registrar_ignoradas(alvo: AlvoColeta, decisao: ResultadoDecisao) -> None:
    """Loga cada mensagem descartada com o motivo, só ações impuras são logadas."""
    for ignorada in decisao.ignoradas:
        logger.warning("mensagem %s ignorada para %s: %s",
                       ignorada.tipo, alvo.icao, ignorada.motivo)


scheduler = AsyncIOScheduler()


async def iniciar_agendador(coletor: HourlyCollector, *, minutos: int = 60) -> None:
    """Agenda a coleta periódica e dispara a primeira execução."""
    if scheduler.running:
        logger.info("agendador já estava em execução")
        return
    scheduler.add_job(
        coletor.coletar_todas_as_rotas, IntervalTrigger(minutes=minutos),
        id="hourly_weather_collector", replace_existing=True, max_instances=1,
        misfire_grace_time=600, coalesce=True)
    scheduler.start()
    logger.info("agendador iniciado", extra={"intervalo_minutos": minutos})
    await coletor.coletar_todas_as_rotas()


def agendar_tarefa(funcao, *, minutos: int, id_tarefa: str) -> None:
    """Registra uma tarefa periódica no mesmo agendador, usado pelo histórico."""
    scheduler.add_job(funcao, IntervalTrigger(minutes=minutos), id=id_tarefa,
                      replace_existing=True, max_instances=1,
                      misfire_grace_time=600, coalesce=True)
    logger.info("tarefa agendada", extra={"id": id_tarefa, "minutos": minutos})


async def encerrar_agendador() -> None:
    """Desliga o agendador."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("agendador encerrado")
