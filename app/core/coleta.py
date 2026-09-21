"""Planejamento da coleta decide o que buscar, sem buscar nada.
Núcleo puro. Recebe as rotas já lidas do banco como tuplas simples  
(route_id, origem, destino) e devolve os alvos de coleta (ICAO + rota).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping

# A tarefa horária do histórico já pede as últimas 2 horas
# (`ColetorHistorico.coletar_recente`); abaixo disso não há buraco a recuperar.
LACUNA_TOLERADA = timedelta(hours=2)


@dataclass(frozen=True)
class AlvoColeta:
    """Um aeródromo a consultar, associado à rota que o exige."""
    icao: str
    route_id: int


@dataclass(frozen=True)
class JanelaColeta:
    """Período de consulta ao histórico de mensagens."""
    inicio: datetime
    fim: datetime


def janela_de_coleta(agora: datetime, *, horas: int = 1) -> JanelaColeta:
    """Última hora fechada a partir de `agora`."""
    fim = agora.replace(minute=0, second=0, microsecond=0)
    return JanelaColeta(inicio=fim - timedelta(hours=horas), fim=fim)


def alvos_de_coleta(rotas: Iterable[tuple[int, str, str]]) -> tuple[AlvoColeta, ...]:
    """Converte rotas em alvos, sem repetir o mesmo par (aeródromo, rota).
    Cada rota gera dois alvos, origem e destino. Um ICAO que aparece em duas
    rotas diferentes é coletado uma vez para cada, porque a observação é
    gravada por rota.
    """
    vistos: set[tuple[str, int]] = set()
    alvos: list[AlvoColeta] = []
    for route_id, origem, destino in rotas:
        for icao in (origem, destino):
            if icao and (icao, route_id) not in vistos:
                vistos.add((icao, route_id))
                alvos.append(AlvoColeta(icao=icao, route_id=route_id))
    return tuple(alvos)


def dias_para_recuperar(ultimas_leituras: Mapping[str, datetime | None],
                        agora: datetime, *, maximo: int) -> int:
    """Quantos dias do histórico precisam ser recoletados para fechar o buraco.
    `ultimas_leituras` é um mapeamento de ICAO para a data da última coleta."""
    if not ultimas_leituras:
        return 0
    if None in ultimas_leituras.values():
        return maximo
    mais_atrasada = min(ultimas_leituras.values())
    if agora - mais_atrasada <= LACUNA_TOLERADA:
        return 0
    return min((agora.date() - mais_atrasada.date()).days + 1, maximo)
