"""Gravação do cache de cartas: duas detecções simultâneas não podem brigar."""

from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from app.aisweb_cache import CacheAisweb


class SessaoQueGuardaOComando:
    """Sessão falsa: registra o comando SQL em vez de falar com o banco."""

    def __init__(self, registro: list) -> None:
        self._registro = registro

    async def __aenter__(self) -> "SessaoQueGuardaOComando":
        return self

    async def __aexit__(self, *_erro) -> bool:
        return False

    async def execute(self, comando) -> None:
        self._registro.append(comando)

    async def commit(self) -> None:
        pass


def _sql_da_gravacao(registro: list) -> str:
    return str(registro[0].compile(dialect=postgresql.dialect()))


async def test_gravacao_da_carta_resolve_conflito_em_vez_de_estourar():
    """Regressão de 20/09/2026: `merge()` estourava carta_texto_pkey quando a
    origem e o destino da mesma rota baixavam a mesma Carta de Área juntas."""
    registro: list = []
    cache = CacheAisweb(cliente=None, sessao_factory=lambda: SessaoQueGuardaOComando(registro))

    await cache.gravar_texto_de_carta("ARC SANTA MARIA", "2609A1", "texto da carta")

    sql = _sql_da_gravacao(registro)
    assert "INSERT INTO carta_texto" in sql
    assert "ON CONFLICT (nome) DO UPDATE" in sql


async def test_gravacao_da_carta_atualiza_texto_e_edicao():
    """Carta que mudou de AMDT precisa sobrescrever o texto guardado."""
    registro: list = []
    cache = CacheAisweb(cliente=None, sessao_factory=lambda: SessaoQueGuardaOComando(registro))

    antes = datetime.now(timezone.utc)
    await cache.gravar_texto_de_carta("ARC RIO DE JANEIRO", "2610A1", "texto novo")

    comando = registro[0]
    assert comando.compile(dialect=postgresql.dialect()).params["amdt"] == "2610A1"
    assert antes <= comando.compile(dialect=postgresql.dialect()).params["atualizado_em"]
