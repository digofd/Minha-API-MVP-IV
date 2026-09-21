# app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

# Cria o motor assíncrono do SQLAlchemy
engine = create_async_engine(settings.database_url, echo=settings.db_echo)

# Cria uma base declarativa para os modelos ORM
Base = declarative_base()

# Cria uma sessão assíncrona
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Função para obter uma sessão de banco de dados
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session