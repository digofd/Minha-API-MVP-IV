# Conexão com o banco de histórico separada da operacional.

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

engine_historico = create_async_engine(settings.historico_database_url,
                                       echo=settings.db_echo)

"""Base própria, pois os modelos do histórico não compartilham metadata com os
operacionais. Um `create_all` criaria tabela no banco errado.
"""
BaseHistorico = declarative_base()
HistoricoSessionLocal = sessionmaker(
    engine_historico, class_=AsyncSession, expire_on_commit=False
)

async def get_db_historico():
    """Sessão do banco de histórico, para injeção nos endpoints."""
    async with HistoricoSessionLocal() as sessao:
        yield sessao
