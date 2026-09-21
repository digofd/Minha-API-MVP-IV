from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence


@dataclass(frozen=True)
class LeituraObservacao:
    """Projeção mínima de uma observação, sem nada do ORM."""

    tipo: str
    status_operacional: str | None
    recebimento: datetime | None


@dataclass(frozen=True)
class ResumoRota:
    """O que o painel precisa saber sobre a situação de uma rota."""

    total: int
    por_status: dict[str, int]
    status_atual: str | None
    ultima_leitura: datetime | None
    total_metar: int
    total_taf: int


def resumir(observacoes: Sequence[LeituraObservacao]) -> ResumoRota:
    """Agrega as observações de uma rota."""
    if not observacoes:
        return ResumoRota(0, {}, None, None, 0, 0)
    contagem = Counter(o.status_operacional or "INDETERMINADO" for o in observacoes)
    metares = [o for o in observacoes if o.tipo == "METAR"]
    return ResumoRota(
        total=len(observacoes),
        por_status=dict(contagem),
        status_atual=_status_mais_recente(metares),
        ultima_leitura=_recebimento_mais_recente(observacoes),
        total_metar=len(metares),
        total_taf=sum(1 for o in observacoes if o.tipo == "TAF"),
    )


def _status_mais_recente(observacoes: Sequence[LeituraObservacao]) -> str | None:
    """Status da leitura mais recente, ignorando as que não têm data."""
    datadas = [o for o in observacoes if o.recebimento is not None]
    if not datadas:
        return None
    return max(datadas, key=lambda o: o.recebimento).status_operacional


def _recebimento_mais_recente(
        observacoes: Sequence[LeituraObservacao]) -> datetime | None:
    """Data da leitura mais recente do conjunto."""
    datas = [o.recebimento for o in observacoes if o.recebimento is not None]
    return max(datas) if datas else None
