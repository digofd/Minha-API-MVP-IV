#Endpoints do histórico, casca sobre o núcleo de tendencias.

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.tendencia import Leitura, serie_diaria
from app.database import get_db
from app.historico.database import get_db_historico
from app.historico.models import LeituraHistorica
from app.models.route import Route
from app.schemas.historico import (
    ColetaOut, HistoricoOut, HistoricoRotaOut, ResumoDiaOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/historico", tags=["histórico"])


@router.get("/rota/{route_id}", response_model=HistoricoRotaOut)
async def historico_da_rota(route_id: int,
                            dias: int = Query(None, ge=1, le=31),
                            db: AsyncSession = Depends(get_db),
                            db_hist: AsyncSession = Depends(get_db_historico)):
    # Série dos dois aeródromos da rota, para comparar origem e destino.
    rota = (await db.execute(
        select(Route.id, Route.origem_icao, Route.destino_icao)
        .where(Route.id == route_id))).one_or_none()
    if rota is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Route not found")
    identificador, origem_icao, destino_icao = rota
    janela = dias or settings.historico_dias
    return HistoricoRotaOut(
        route_id=identificador,
        origem=await _montar(db_hist, origem_icao, janela),
        destino=await _montar(db_hist, destino_icao, janela))


@router.get("/{icao}", response_model=HistoricoOut)
async def historico_do_aerodromo(icao: str,
                                 dias: int = Query(None, ge=1, le=31),
                                 db_hist: AsyncSession = Depends(get_db_historico)):
    #Série de um aeródromo: pontos e resumo por dia
    return await _montar(db_hist, icao, dias or settings.historico_dias)


@router.post("/coletar", response_model=ColetaOut)
async def coletar(request: Request, dias: int = Query(None, ge=1, le=31),
                  db: AsyncSession = Depends(get_db)):
    # Preenche o histórico dos aeródromos das rotas ativas e expurga o excedente.
    coletor = getattr(request.app.state, "coletor_historico", None)
    if coletor is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "coletor de histórico indisponível")
    icaos = await _icaos_das_rotas_ativas(db)
    if not icaos:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "nenhuma rota ativa: não há aeródromo para coletar")
    janela = dias or settings.historico_dias
    resultado = await coletor.preencher(icaos, dias=janela)
    expurgadas = await coletor.expurgar(dias=settings.historico_dias)
    return ColetaOut(icaos=icaos, dias=janela, expurgadas=expurgadas,
                     falhas=list(resultado.falhas),
                     **{k: v for k, v in asdict(resultado).items() if k != "falhas"})


async def _icaos_das_rotas_ativas(db: AsyncSession) -> list[str]:
    """Aeródromos distintos das rotas ativas — sem repetir o mesmo ICAO."""
    linhas = (await db.execute(
        select(Route.origem_icao, Route.destino_icao)
        .where(Route.ativa.is_(True)))).all()
    return sorted({icao for linha in linhas for icao in linha if icao})


async def _montar(db_hist: AsyncSession, icao: str, dias: int) -> HistoricoOut:
    """Lê as linhas do período e delega a agregação ao núcleo puro."""
    codigo = icao.strip().upper()
    corte = datetime.now(timezone.utc) - timedelta(days=dias)
    linhas = (await db_hist.execute(
        select(LeituraHistorica)
        .where(LeituraHistorica.icao == codigo,
               LeituraHistorica.momento_utc >= corte)
        .order_by(LeituraHistorica.momento_utc))).scalars().all()

    leituras = [_para_dominio(linha) for linha in linhas]
    serie = serie_diaria(leituras, ate=datetime.now(timezone.utc).date(), dias=dias)
    return HistoricoOut(
        icao=codigo, dias=dias, leituras=linhas,
        serie_diaria=[ResumoDiaOut(**asdict(r), sem_dado=r.sem_dado) for r in serie])


def _para_dominio(linha: LeituraHistorica) -> Leitura:
    # Converte a linha do ORM no tipo do domínio, o núcleo não vê o SQLAlchemy
    return Leitura(
        icao=linha.icao, momento_utc=linha.momento_utc, tipo=linha.tipo,
        mensagem_bruta=linha.mensagem_bruta, teto_ft=linha.teto_ft,
        visibilidade_m=linha.visibilidade_m, temperatura_c=linha.temperatura_c,
        pressao_hpa=linha.pressao_hpa,
        status_operacional=linha.status_operacional or "INDETERMINADO",
        base_legal=linha.base_legal or "")
