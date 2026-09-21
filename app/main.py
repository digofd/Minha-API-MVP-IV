from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select, text

from app.aisweb_cache import CacheAisweb
from app.clients.aisweb_client import AiswebClient
from app.clients.redemet_client import RedemetClient
from app.config import settings
from app.core.coleta import dias_para_recuperar
from app.core.espaco_aereo import CLASSES_CONHECIDAS
from app.database import AsyncSessionLocal, Base, engine
from app.deteccao_classe_espaco_aereo import DetectorDeClasse
from app.historico.coletor import ColetorHistorico
from app.historico.database import BaseHistorico, HistoricoSessionLocal, engine_historico
from app.historico import models as modelos_historico 
from app.jobs.hourly_collector import (
    HourlyCollector, agendar_tarefa, encerrar_agendador, iniciar_agendador,
)
from app.logging_config import configurar_logging
from app.models import aisweb_cache as modelos_aisweb_cache  
from app.models.route import Route
from app.routes import historico as rotas_historico
from app.routes import routes

configurar_logging()
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def _icaos_das_rotas_ativas() -> list[str]:
    # Aeródromos distintos das rotas ativas, lidos do banco operacional.
    async with AsyncSessionLocal() as sessao:
        linhas = (await sessao.execute(
            select(Route.origem_icao, Route.destino_icao)
            .where(Route.ativa.is_(True)))).all()
    return sorted({icao for linha in linhas for icao in linha if icao})


def _manutencao_do_historico(coletor_historico: ColetorHistorico):
    """
    Tarefa horária do histórico: coleta a hora corrente e expurga o excedente.
    Lê os aeródromos das rotas ativas no banco operacional, série por
    ICAO, então o mesmo aeródromo em duas rotas é coletado uma vez só.
    """
    async def tarefa() -> None:
        icaos = await _icaos_das_rotas_ativas()
        if not icaos:
            logger.info("histórico: nenhuma rota ativa")
            return
        resultado = await coletor_historico.coletar_recente(icaos)
        logger.info("histórico: coleta da hora corrente", extra={
            "icaos": icaos, "lidas": resultado.lidas, "gravadas": resultado.gravadas,
            "ignoradas": resultado.ignoradas, "janelas_vazias": resultado.janelas_vazias,
            "falhas": resultado.falhas})
        await coletor_historico.expurgar(dias=settings.historico_dias)

    return tarefa


def _recuperar_lacunas_do_historico(coletor_historico: ColetorHistorico):
    """Na subida, recoleta o período em que a aplicação ficou fora do ar.
    A tarefa horária só pede as últimas 2 horas e só roda uma hora depois da
    subida, então recoletar um dia que já tem parte das leituras não duplica nada.
    """
    async def tarefa() -> None:
        icaos = await _icaos_das_rotas_ativas()
        ultimas = await coletor_historico.ultima_leitura_por_icao(icaos)
        dias = dias_para_recuperar(ultimas, datetime.now(timezone.utc),
                                   maximo=settings.historico_dias)
        if not dias:
            logger.info("histórico: nenhuma lacuna a recuperar", extra={"icaos": icaos})
            return
        logger.info("histórico: recuperando lacuna", extra={"icaos": icaos, "dias": dias})
        await coletor_historico.preencher(icaos, dias=dias)

    return tarefa


# AIRAC muda a cada 28 dias, checar semanalmente se a fonte mudou.
INTERVALO_VERIFICACAO_CLASSE_MINUTOS = 7 * 24 * 60


def _verificar_edicao_das_classes(cache_aisweb: CacheAisweb):
    # Confere, para cada ICAO checado manualmente, se a carta-fonte mudou de AMDT.
    async def tarefa() -> None:
        for icao, conhecida in CLASSES_CONHECIDAS.items():
            await cache_aisweb.checar_edicao_da_carta(icao, conhecida.fonte_tipo)

    return tarefa


def _detectar_classes_das_rotas_ativas(detector: DetectorDeClasse):
    """Backfill na subida: detecta a classe de todo ICAO de rota ativa que
    ainda não tem uma (nem manual, nem já detectada antes). 
    """
    async def tarefa() -> None:
        icaos = await _icaos_das_rotas_ativas()
        for icao in icaos:
            try:
                await detector.detectar_e_gravar(icao)
            except Exception:
                logger.exception("detecção de classe de espaço aéreo falhou para %s", icao)

    return tarefa


async def _executar_sem_derrubar(tarefa, descricao: str) -> None:
    # Roda uma tarefa de subida e registra a falha, em vez de perdê-la na task solta.
    try:
        await tarefa()
    except Exception:
        logger.exception("%s falhou", descricao)


async def _adicionar_colunas_novas(conexao) -> None:
    await conexao.execute(text(
        "ALTER TABLE observations ADD COLUMN IF NOT EXISTS aviso_temporario VARCHAR(255)"))
    # `fonte_tipo` guarda o nome da carta ("ARC RIO DE JANEIRO")
    await conexao.execute(text(
        "ALTER TABLE classe_espaco_aereo_detectada "
        "ALTER COLUMN fonte_tipo TYPE VARCHAR(80)"))


async def _travar_observacoes_repetidas(conexao) -> None:
   # Apaga duplicata e trava a chave natural 
    await conexao.execute(text("""
        DELETE FROM observations o USING observations mais_antiga
        WHERE o.route_id = mais_antiga.route_id AND o.icao = mais_antiga.icao
          AND o.tipo = mais_antiga.tipo AND o.mensagem_bruta = mais_antiga.mensagem_bruta
          AND o.recebimento = mais_antiga.recebimento AND o.id > mais_antiga.id
    """))
    await conexao.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_observation_natural_key'
            ) THEN
                ALTER TABLE observations ADD CONSTRAINT uq_observation_natural_key
                    UNIQUE (route_id, icao, tipo, mensagem_bruta, recebimento);
            END IF;
        END $$;
    """))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Monta as dependências, sobe o agendador e desliga tudo na saída.
    async with engine.begin() as conexao:
        await conexao.run_sync(Base.metadata.create_all)
        await _adicionar_colunas_novas(conexao)
        await _travar_observacoes_repetidas(conexao)
    async with engine_historico.begin() as conexao:
        await conexao.run_sync(BaseHistorico.metadata.create_all)
    logger.info("esquema dos dois bancos verificado")

    cliente = RedemetClient(settings.redemet_base_url, settings.redemet_api_key)
    cliente_aisweb = AiswebClient(settings.aisweb_base_url, settings.aisweb_api_key,
                                  settings.aisweb_api_pass)
    cache_aisweb = CacheAisweb(cliente_aisweb, AsyncSessionLocal)
    coletor = HourlyCollector(cliente, AsyncSessionLocal, cache_aisweb)
    coletor_historico = ColetorHistorico(cliente, HistoricoSessionLocal, cache_aisweb)
    detector_classe = DetectorDeClasse(cliente_aisweb, cache_aisweb)
    app.state.coletor = coletor
    app.state.coletor_historico = coletor_historico
    app.state.detector_classe = detector_classe
    app.state.tarefas_historico_inicial = set()
    app.state.tarefas_deteccao_classe = set()
    app.state.tarefa_agendador = asyncio.create_task(
        iniciar_agendador(coletor, minutos=settings.collector_interval_minutes))
    agendar_tarefa(_manutencao_do_historico(coletor_historico),
                   minutos=settings.collector_interval_minutes,
                   id_tarefa="historico_horario")
    agendar_tarefa(_verificar_edicao_das_classes(cache_aisweb),
                   minutos=INTERVALO_VERIFICACAO_CLASSE_MINUTOS,
                   id_tarefa="verificacao_classe_espaco_aereo")
    # Backfill: detecta a classe dos ICAOs de rota ativa que ainda não têm uma detectada.
    app.state.tarefa_deteccao_inicial = asyncio.create_task(
        _detectar_classes_das_rotas_ativas(detector_classe)())
    # Em segundo plano: recuperar dias inteiros que ficaram sem coleta, se a aplicação caiu ou foi desligada.
    app.state.tarefa_recuperacao_historico = asyncio.create_task(
        _executar_sem_derrubar(_recuperar_lacunas_do_historico(coletor_historico),
                               "recuperação de lacunas do histórico"))
    logger.info("aplicação iniciada")

    yield

    await encerrar_agendador()
    app.state.tarefa_agendador.cancel()
    with suppress(asyncio.CancelledError):
        await app.state.tarefa_agendador
    for tarefa_de_subida in (app.state.tarefa_deteccao_inicial,
                             app.state.tarefa_recuperacao_historico):
        tarefa_de_subida.cancel()
        with suppress(asyncio.CancelledError):
            await tarefa_de_subida
    for tarefa in list(app.state.tarefas_historico_inicial):
        tarefa.cancel()
    with suppress(asyncio.CancelledError):
        await asyncio.gather(*app.state.tarefas_historico_inicial, return_exceptions=True)
    for tarefa in list(app.state.tarefas_deteccao_classe):
        tarefa.cancel()
    with suppress(asyncio.CancelledError):
        await asyncio.gather(*app.state.tarefas_deteccao_classe, return_exceptions=True)
    await cliente.close()
    await cliente_aisweb.close()
    logger.info("aplicação encerrada")


app = FastAPI(
    title="SkyRoute Weather API",
    description="Condições VFR de aeródromos por rota, a partir de METAR e TAF da "
                "REDEMET, classificadas pela ICA 100-12.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=600,
)

app.include_router(routes.router)
app.include_router(rotas_historico.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
