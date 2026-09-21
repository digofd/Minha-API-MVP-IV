from __future__ import annotations

from dataclasses import dataclass

TAMANHO_PADRAO = 20
TAMANHO_MAXIMO = 100

CAMPOS_ORDENAVEIS = ("criado_em", "origem_icao", "destino_icao", "id")


@dataclass(frozen=True)
class Paginacao:
    pagina: int
    tamanho: int

    @property
    def offset(self) -> int:
        return (self.pagina - 1) * self.tamanho

    def total_de_paginas(self, total_de_itens: int) -> int:
        if total_de_itens <= 0:
            return 0
        return -(-total_de_itens // self.tamanho)  # divisão para cima


@dataclass(frozen=True)
class Ordenacao:
    campo: str
    descendente: bool


@dataclass(frozen=True)
class FiltroRotas:
    ativa: bool | None = None
    icao: str | None = None


def montar_paginacao(pagina: int | None, tamanho: int | None) -> Paginacao:
    pagina_pedida = pagina if pagina is not None else 1
    tamanho_pedido = tamanho if tamanho is not None else TAMANHO_PADRAO
    return Paginacao(pagina=max(1, pagina_pedida),
                     tamanho=min(TAMANHO_MAXIMO, max(1, tamanho_pedido)))


def montar_ordenacao(campo: str | None, ordem: str | None) -> Ordenacao:
    escolhido = campo or "criado_em"
    if escolhido not in CAMPOS_ORDENAVEIS:
        raise ValueError(
            f"campo de ordenação inválido: {escolhido!r}; "
            f"esperado um de {list(CAMPOS_ORDENAVEIS)}")
    return Ordenacao(campo=escolhido, descendente=(ordem or "desc").lower() != "asc")


def montar_filtro(ativa: bool | None, icao: str | None) -> FiltroRotas:
    """Normaliza o filtro: ICAO em maiúsculas, vazio vira ausência de filtro."""
    codigo = (icao or "").strip().upper()
    return FiltroRotas(ativa=ativa, icao=codigo or None)
