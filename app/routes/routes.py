from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.consulta import (
    FiltroRotas, Ordenacao, Paginacao, montar_filtro, montar_ordenacao, montar_paginacao,
)
from app.core.resumo import LeituraObservacao, resumir
from app.database import get_db
from app.models.observation import Observation
from app.models.route import Route
from app.schemas.observation_schema import ObservationSchema, PaginaDeObservacoes
from app.schemas.route import (
    PaginaDeRotas, ResumoRotaOut, RouteCreate, RouteOut, RouteUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Quantas observações recentes o painel de detalhe recebe
LIMITE_OBSERVACOES_DETALHE = 20

@router.get("/health", tags=["infra"])
async def health(db: AsyncSession = Depends(get_db)):
    """Prontidão da API e do banco — usado pelo Docker e pelo front-end."""
    await db.execute(select(1))
    return {"status": "ok"}


@router.post("/routes", response_model=RouteOut, status_code=status.HTTP_201_CREATED,
             tags=["rotas"])
async def create_route(route: RouteCreate, request: Request,
                       db: AsyncSession = Depends(get_db)):
    """Cria a rota e faz a primeira coleta para origem e destino.
    A coleta é síncrona para que a resposta já traga as observações. 
    Ela chama o método público do coletor obtido da raiz de composição. 
    """
    db_route = Route(origem_icao=route.origem_icao, destino_icao=route.destino_icao,
                     ativa=route.ativa)
    db.add(db_route)
    await db.commit()
    await db.refresh(db_route)

    await _coletar_para(request, db_route)
    _disparar_historico_inicial(request, db_route)
    _disparar_deteccao_de_classe(request, db_route)

    await db.refresh(db_route, attribute_names=["observations"])
    return RouteOut(
        id=db_route.id, origem_icao=db_route.origem_icao, destino_icao=db_route.destino_icao,
        ativa=db_route.ativa, criado_em=db_route.criado_em,
        total_observations=len(db_route.observations),
        observations=[ObservationSchema.model_validate(o) for o in db_route.observations])


async def _coletar_para(request: Request, db_route: Route) -> None:
    """Dispara a coleta inicial sem deixar a falha derrubar a criação da rota."""
    coletor = getattr(request.app.state, "coletor", None)
    if coletor is None:
        logger.warning("coletor indisponível; rota %s ficará para a coleta horária",
                       db_route.id)
        return
    try:
        await coletor.coletar_rota(db_route.id, db_route.origem_icao,
                                   db_route.destino_icao)
    except Exception:
        logger.exception("coleta inicial falhou para a rota %s", db_route.id)


def _disparar_historico_inicial(request: Request, db_route: Route) -> None:
    """Preenche os dias de histórico da rota nova, em segundo plano.
    Roda em background, não em `await`: diferente da coleta operacional, 
    pois preencher o histórico leva dezenas de segundos (uma janela de 2 h por vez, por aeródromo),
    e esperar isso na resposta do POST deixaria a criação da rota lenta e arriscaria timeout.
    """
    coletor_historico = getattr(request.app.state, "coletor_historico", None)
    if coletor_historico is None:
        logger.warning("coletor de histórico indisponível; rota %s sem tendência "
                       "até a próxima coleta horária", db_route.id)
        return
    icaos = [db_route.origem_icao, db_route.destino_icao]
    tarefas = request.app.state.tarefas_historico_inicial
    tarefa = asyncio.create_task(
        _preencher_historico_inicial(coletor_historico, icaos, db_route.id))
    tarefas.add(tarefa)
    tarefa.add_done_callback(tarefas.discard)


async def _preencher_historico_inicial(coletor_historico, icaos: list[str],
                                       route_id: int) -> None:
    try:
        dias = settings.historico_dias
        ja_prontos = await coletor_historico.icaos_ja_preenchidos(icaos, dias=dias)
        faltando = [icao for icao in icaos if icao not in ja_prontos]
        if not faltando:
            logger.info("histórico da rota %s já estava completo (%s)", route_id, icaos)
            return
        resultado = await coletor_historico.preencher(faltando, dias=dias)
        logger.info("histórico inicial preenchido para a rota %s (%s): "
                    "%s gravadas, %s falhas", route_id, faltando,
                    resultado.gravadas, len(resultado.falhas))
    except Exception:
        logger.exception("preenchimento inicial do histórico falhou para a rota %s", route_id)


def _disparar_deteccao_de_classe(request: Request, db_route: Route) -> None:
    """Detecta a classe de espaço aéreo de ICAO novo, em segundo plano.
    Roda em background pelo mesmo motivo do histórico, pois baixar e ler 
    o PDF da carta não é instantâneo.
    """
    detector = getattr(request.app.state, "detector_classe", None)
    if detector is None:
        return
    icaos = [db_route.origem_icao, db_route.destino_icao]
    tarefas = request.app.state.tarefas_deteccao_classe
    for icao in icaos:
        tarefa = asyncio.create_task(_detectar_classe_para(detector, icao))
        tarefas.add(tarefa)
        tarefa.add_done_callback(tarefas.discard)


async def _detectar_classe_para(detector, icao: str) -> None:
    try:
        await detector.detectar_e_gravar(icao)
    except Exception:
        logger.exception("detecção de classe de espaço aéreo falhou para %s", icao)


@router.get("/routes", response_model=PaginaDeRotas, tags=["rotas"])
async def read_routes(
    db: AsyncSession = Depends(get_db),
    pagina: int = Query(1, ge=1, description="Página, começando em 1"),
    tamanho: int = Query(20, ge=1, le=100, description="Itens por página"),
    ativa: Optional[bool] = Query(None, description="Filtra por rota ativa"),
    icao: Optional[str] = Query(None, description="Filtra por ICAO de origem ou destino"),
    ordenar_por: str = Query("criado_em", description="criado_em, origem_icao, destino_icao ou id"),
    ordem: str = Query("desc", description="asc ou desc"),
):
    # Lista rotas com filtro, ordenação e paginação
    try:
        ordenacao = montar_ordenacao(ordenar_por, ordem)
    except ValueError as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(erro)) from erro
    paginacao = montar_paginacao(pagina, tamanho)
    filtro = montar_filtro(ativa, icao)

    total = await _contar_rotas(db, filtro)
    itens = await _buscar_rotas(db, filtro, ordenacao, paginacao)
    return PaginaDeRotas(itens=itens, total=total, pagina=paginacao.pagina,
                         tamanho=paginacao.tamanho,
                         paginas=paginacao.total_de_paginas(total))


def _aplicar_filtro(consulta, filtro: FiltroRotas):
    # Traduz o filtro do domínio em cláusulas SQL
    if filtro.ativa is not None:
        consulta = consulta.where(Route.ativa.is_(filtro.ativa))
    if filtro.icao:
        consulta = consulta.where(or_(Route.origem_icao == filtro.icao,
                                      Route.destino_icao == filtro.icao))
    return consulta


async def _contar_rotas(db: AsyncSession, filtro: FiltroRotas) -> int:
    # Total de rotas que atendem ao filtro, para calcular as páginas
    consulta = _aplicar_filtro(select(func.count()).select_from(Route), filtro)
    return int((await db.execute(consulta)).scalar_one())


async def _buscar_rotas(db: AsyncSession, filtro: FiltroRotas, ordenacao: Ordenacao,
                        paginacao: Paginacao) -> list[RouteOut]:
    # Página de rotas já ordenada, com a contagem de observações
    coluna = getattr(Route, ordenacao.campo)
    consulta = _aplicar_filtro(select(Route), filtro)
    consulta = (consulta.order_by(coluna.desc() if ordenacao.descendente else coluna.asc())
                .offset(paginacao.offset).limit(paginacao.tamanho))
    rotas = list((await db.execute(consulta)).scalars().all())
    contagens = await _contagens_por_rota(db, [r.id for r in rotas])
    return [RouteOut(id=r.id, origem_icao=r.origem_icao, destino_icao=r.destino_icao,
                     ativa=r.ativa, criado_em=r.criado_em,
                     total_observations=contagens.get(r.id, 0), observations=[])
            for r in rotas]


async def _contagens_por_rota(db: AsyncSession, route_ids: list[int]) -> dict[int, int]:
    # Quantas observações cada rota tem, num único `GROUP BY`.
    if not route_ids:
        return {}
    linhas = (await db.execute(
        select(Observation.route_id, func.count())
        .where(Observation.route_id.in_(route_ids))
        .group_by(Observation.route_id))).all()
    return dict(linhas)


@router.get("/routes/{route_id}", response_model=RouteOut, tags=["rotas"])
async def read_route(route_id: int, db: AsyncSession = Depends(get_db)):
    return await _detalhe_da_rota(db, route_id)


@router.get("/routes/{route_id}/observacoes", response_model=PaginaDeObservacoes,
           tags=["rotas"])
async def route_observations(
    route_id: int,
    db: AsyncSession = Depends(get_db),
    pagina: int = Query(1, ge=1, description="Página, começando em 1"),
    tamanho: int = Query(10, ge=1, le=100, description="Itens por página"),
    horas: int = Query(24, ge=1, le=24 * 15, description="Janela, em horas, a partir de agora"),
):
    await _rota_orm_ou_404(db, route_id)
    paginacao = montar_paginacao(pagina, tamanho)
    corte = datetime.now(timezone.utc) - timedelta(hours=horas)
    total = await _contar_observacoes_desde(db, route_id, corte)
    itens = await _buscar_observacoes_desde(db, route_id, corte, paginacao)
    return PaginaDeObservacoes(itens=itens, total=total, pagina=paginacao.pagina,
                               tamanho=paginacao.tamanho,
                               paginas=paginacao.total_de_paginas(total))


async def _contar_observacoes_desde(db: AsyncSession, route_id: int,
                                    corte: datetime) -> int:
    # Quantas observações da rota caem dentro da janela, para calcular as páginas.
    return int((await db.execute(
        select(func.count()).select_from(Observation)
        .where(Observation.route_id == route_id, Observation.recebimento >= corte)
    )).scalar_one())


async def _buscar_observacoes_desde(db: AsyncSession, route_id: int, corte: datetime,
                                    paginacao: Paginacao) -> list[ObservationSchema]:
    # Uma página de observações da rota dentro da janela, da mais nova pra mais velha.
    linhas = (await db.execute(
        select(Observation)
        .where(Observation.route_id == route_id, Observation.recebimento >= corte)
        .order_by(Observation.recebimento.desc())
        .offset(paginacao.offset).limit(paginacao.tamanho))).scalars().all()
    return [ObservationSchema.model_validate(o) for o in linhas]


@router.put("/routes/{route_id}", response_model=RouteOut, tags=["rotas"])
async def update_route(route_id: int, alteracao: RouteUpdate,
                       db: AsyncSession = Depends(get_db)):
    # Ativa ou desativa a rota. Rota inativa sai da coleta horária.
    rota = await _rota_orm_ou_404(db, route_id)
    rota.ativa = alteracao.ativa
    await db.commit()
    logger.info("rota %s marcada como ativa=%s", route_id, alteracao.ativa)
    return await _detalhe_da_rota(db, route_id)


@router.delete("/routes/{route_id}", status_code=status.HTTP_200_OK, tags=["rotas"])
async def delete_route(route_id: int, db: AsyncSession = Depends(get_db)):
    """ 
    Aqui as observações precisam estar carregadas: é o `cascade=
    "all, delete-orphan"` que as apaga junto, e ele depende da coleção
    estar em memória no momento do `delete`.
    """
    resultado = await db.execute(
        select(Route).filter(Route.id == route_id)
        .options(selectinload(Route.observations)))
    rota = resultado.scalars().unique().one_or_none()
    if rota is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Route not found")
    await db.delete(rota)
    await db.commit()
    logger.info("rota %s removida", route_id)
    return {"message": f"Route {route_id} deleted successfully"}


@router.get("/routes/{route_id}/resumo", response_model=ResumoRotaOut, tags=["rotas"])
async def route_summary(route_id: int, db: AsyncSession = Depends(get_db)):
    """Resumo operacional da rota, lê só as três colunas que `resumir()` usa, 
    não a observação inteira, pois a mensagem crua de cada METAR/TAF não entra nesta conta, 
    e não precisa trafegar pela rede para ser descartada em seguida.
    """
    rota = (await db.execute(
        select(Route.id, Route.origem_icao, Route.destino_icao)
        .where(Route.id == route_id))).one_or_none()
    if rota is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Route not found")
    identificador, origem_icao, destino_icao = rota

    linhas = (await db.execute(
        select(Observation.tipo, Observation.status_operacional, Observation.recebimento)
        .where(Observation.route_id == route_id))).all()
    leituras = [LeituraObservacao(tipo=t, status_operacional=s, recebimento=r)
                for t, s, r in linhas]
    resumo = resumir(leituras)
    return ResumoRotaOut(route_id=identificador, origem_icao=origem_icao,
                         destino_icao=destino_icao, **asdict(resumo))


async def _rota_orm_ou_404(db: AsyncSession, route_id: int) -> Route:
    # Busca só a linha da rota, sem observações para quando elas não importam
    rota = (await db.execute(select(Route).where(Route.id == route_id))).scalar_one_or_none()
    if rota is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Route not found")
    return rota


async def _detalhe_da_rota(db: AsyncSession, route_id: int) -> RouteOut:
    rota = await _rota_orm_ou_404(db, route_id)
    total = (await db.execute(
        select(func.count()).select_from(Observation)
        .where(Observation.route_id == route_id))).scalar_one()
    recentes = (await db.execute(
        select(Observation).where(Observation.route_id == route_id)
        .order_by(Observation.recebimento.desc())
        .limit(LIMITE_OBSERVACOES_DETALHE))).scalars().all()
    return RouteOut(
        id=rota.id, origem_icao=rota.origem_icao, destino_icao=rota.destino_icao,
        ativa=rota.ativa, criado_em=rota.criado_em, total_observations=total,
        observations=[ObservationSchema.model_validate(o) for o in recentes])
