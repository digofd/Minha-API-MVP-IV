# Se um instante é diurno, a partir da tabela de nascer/pôr do sol.

from __future__ import annotations

from datetime import date, datetime

JanelasSol = dict[tuple[str, date], tuple[datetime, datetime]]


def diurno_em(icao: str, momento: datetime, janelas_sol: JanelasSol) -> bool | None:
    """True se o instante cai entre o nascer e o pôr do sol daquele dia/aeródromo.
    `None` quando não há dado para o dia, o classificador trata isso como
    reprovação, não como suposição.
    """
    janela = janelas_sol.get((icao, momento.date()))
    if janela is None:
        return None
    nascer, por = janela
    return nascer <= momento <= por
