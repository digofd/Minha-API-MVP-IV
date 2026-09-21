from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.aisweb_cache import CacheAisweb
from app.clients.redemet_client import RedemetClient, descrever, mensagens_de
from app.core.sol import JanelasSol
from app.core.tendencia import Leitura, leituras_de_envelopes
from app.historico.models import LeituraHistorica

logger = logging.getLogger(__name__)

HORAS_POR_JANELA = 2
PAUSA_ENTRE_JANELAS_S = 0.2


@dataclass(frozen=True)
class ResultadoPreenchimento:
    """O que a coleta conseguiu e o que não conseguiu."""

    janelas: int
    lidas: int
    gravadas: int
    ignoradas: int
    janelas_vazias: int
    falhas: tuple[str, ...]


class ColetorHistorico:
    """Preenche e mantém a janela de 15 dias."""

    def __init__(self, cliente: RedemetClient, sessao_factory,
                cache_aisweb: CacheAisweb | None = None) -> None:
        self._cliente = cliente
        self._sessao_factory = sessao_factory
        self._cache_aisweb = cache_aisweb

    async def preencher(self, icaos: list[str], *, dias: int,
                        ate: datetime | None = None) -> ResultadoPreenchimento:
        """Percorre o período em janelas de 2 horas, com os ICAOs agrupados.
        a unicidade no banco descarta o que já existe.
        """
        fim = (ate or datetime.now(timezone.utc)).replace(
            minute=0, second=0, microsecond=0)
        inicio = fim - timedelta(days=dias - 1)
        inicio = inicio.replace(hour=0)

        total = ResultadoPreenchimento(0, 0, 0, 0, 0, ())
        janela_inicio = inicio
        while janela_inicio <= fim:
            janela_fim = min(janela_inicio + timedelta(hours=HORAS_POR_JANELA - 1), fim)
            total = _somar(total, await self._coletar_janela(
                icaos, janela_inicio, janela_fim))
            janela_inicio = janela_fim + timedelta(hours=1)
            await asyncio.sleep(PAUSA_ENTRE_JANELAS_S)

        logger.info("preenchimento do histórico concluído", extra={
            "janelas": total.janelas, "gravadas": total.gravadas,
            "vazias": total.janelas_vazias, "falhas": len(total.falhas)})
        return total

    async def coletar_recente(self, icaos: list[str]) -> ResultadoPreenchimento:
        """Coleta a hora corrente e a anterior, chamada pelo agendador horário."""
        agora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        return await self._coletar_janela(icaos, agora - timedelta(hours=1), agora)

    async def _coletar_janela(self, icaos: list[str], inicio: datetime,
                              fim: datetime) -> ResultadoPreenchimento:
        """Uma requisição, uma gravação, montando workflow: busca, decide, grava."""
        if not icaos:
            return ResultadoPreenchimento(0, 0, 0, 0, 0, ())
        resposta = await self._cliente.get_metar_periodo(icaos, inicio, fim)
        envelopes = mensagens_de(resposta)
        if not envelopes:
            falha = () if _foi_sucesso(resposta) else (
                f"{inicio:%Y-%m-%d %HZ}: {descrever(resposta)}",)
            if falha:
                logger.warning("janela sem dado por falha: %s", falha[0])
            return ResultadoPreenchimento(1, 0, 0, 0, 1, falha)

        janelas_sol, dentro_ctr_atz_por_icao, classes_detectadas = await self._contexto_aisweb(
            icaos, inicio, fim)
        lidas, ignoradas = leituras_de_envelopes(
            envelopes, agora=inicio.replace(tzinfo=timezone.utc),
            janelas_sol=janelas_sol, dentro_ctr_atz_por_icao=dentro_ctr_atz_por_icao,
            classes_detectadas=classes_detectadas)
        gravadas = await self._gravar(lidas)
        return ResultadoPreenchimento(1, len(lidas), gravadas, len(ignoradas), 0, ())

    async def _contexto_aisweb(self, icaos: list[str], inicio: datetime, fim: datetime):
        """Dados do VFR Especial e classes já detectadas, vazio sem AISWEB ligada."""
        if self._cache_aisweb is None:
            return {}, {}, {}
        janelas_sol: JanelasSol = {}
        for icao in icaos:
            janelas_sol.update(
                await self._cache_aisweb.janela_sol(icao, inicio.date(), fim.date()))
        return (janelas_sol, await self._cache_aisweb.dentro_ctr_atz_por_icao(icaos),
               await self._cache_aisweb.classes_detectadas_por_icao(icaos))

    async def _gravar(self, leituras: tuple[Leitura, ...]) -> int:
        """Insere ignorando o que já existe, devolve quantas linhas entraram."""
        if not leituras:
            return 0
        linhas = [_para_linha(l) for l in leituras]
        async with self._sessao_factory() as sessao:
            comando = insert(LeituraHistorica).values(linhas)
            comando = comando.on_conflict_do_nothing(
                constraint="uq_leitura_historica")
            resultado = await sessao.execute(comando)
            await sessao.commit()
            return resultado.rowcount or 0

    async def expurgar(self, *, dias: int) -> int:
        """Apaga o que saiu da janela, mantendo o histórico com tamanho fixo."""
        corte = datetime.now(timezone.utc) - timedelta(days=dias)
        async with self._sessao_factory() as sessao:
            resultado = await sessao.execute(
                delete(LeituraHistorica).where(LeituraHistorica.momento_utc < corte))
            await sessao.commit()
            removidas = resultado.rowcount or 0
        if removidas:
            logger.info("histórico expurgado", extra={"linhas": removidas})
        return removidas

    async def icaos_ja_preenchidos(self, icaos: list[str], *, dias: int,
                                   agora: datetime | None = None) -> set[str]:
        if not icaos:
            return set()
        corte = (agora or datetime.now(timezone.utc)) - timedelta(days=dias - 1)
        margem = timedelta(hours=6)
        async with self._sessao_factory() as sessao:
            resultado = await sessao.execute(
                select(LeituraHistorica.icao)
                .where(LeituraHistorica.icao.in_(icaos))
                .group_by(LeituraHistorica.icao)
                .having(func.min(LeituraHistorica.momento_utc) <= corte + margem))
            return {linha[0] for linha in resultado.all()}

    async def ultima_leitura_por_icao(self, icaos: list[str]) -> dict[str, datetime | None]:
        """Instante da leitura mais nova de cada aeródromo, `None` se nunca teve."""
        if not icaos:
            return {}
        async with self._sessao_factory() as sessao:
            resultado = await sessao.execute(
                select(LeituraHistorica.icao, func.max(LeituraHistorica.momento_utc))
                .where(LeituraHistorica.icao.in_(icaos))
                .group_by(LeituraHistorica.icao))
            encontradas = dict(resultado.all())
        return {icao: encontradas.get(icao) for icao in icaos}

    async def icaos_com_dado(self) -> list[str]:
        """Aeródromos que já têm série gravada."""
        async with self._sessao_factory() as sessao:
            resultado = await sessao.execute(
                select(LeituraHistorica.icao).distinct())
            return [linha[0] for linha in resultado.all()]


def _para_linha(leitura: Leitura) -> dict:
    """Converte a decisão pura em linha do ORM."""
    return {
        "icao": leitura.icao, "momento_utc": leitura.momento_utc,
        "tipo": leitura.tipo, "mensagem_bruta": leitura.mensagem_bruta,
        "teto_ft": leitura.teto_ft, "visibilidade_m": leitura.visibilidade_m,
        "temperatura_c": leitura.temperatura_c, "pressao_hpa": leitura.pressao_hpa,
        "status_operacional": leitura.status_operacional,
        "base_legal": leitura.base_legal,
    }


def _foi_sucesso(resposta) -> bool:
    """Lista vazia por ausência de mensagem não é falha."""
    return type(resposta).__name__ == "Dados"


def _somar(a: ResultadoPreenchimento,
           b: ResultadoPreenchimento) -> ResultadoPreenchimento:
    """Acumula o resultado de cada janela."""
    return ResultadoPreenchimento(
        a.janelas + b.janelas, a.lidas + b.lidas, a.gravadas + b.gravadas,
        a.ignoradas + b.ignoradas, a.janelas_vazias + b.janelas_vazias,
        a.falhas + b.falhas)
