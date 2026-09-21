# app/models/aisweb_cache.py

from sqlalchemy import Boolean, Column, Date, DateTime, String, Text
from sqlalchemy.sql import func

from app.database import Base


class SolDiario(Base):
    __tablename__ = "sol_diario"

    # Chave composta (não um id à parte): é exatamente o que identifica um
    # registro de nascer/pôr do sol, e permite `session.merge()` como upsert.
    icao = Column(String(4), primary_key=True)
    data = Column(Date, primary_key=True)
    nascer_utc = Column(DateTime(timezone=True), nullable=False)
    por_utc = Column(DateTime(timezone=True), nullable=False)


class AerodromoInfo(Base):
    __tablename__ = "aerodromo_info"

    icao = Column(String(4), primary_key=True)
    dentro_ctr_atz = Column(Boolean, nullable=False)
    atualizado_em = Column(DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now(), nullable=False)


class CartaAmdtVista(Base):
    __tablename__ = "carta_amdt_vista"

    # Chave composta: uma carta é identificada por aeródromo + tipo (ex.:
    # SBSP + VAC). `amdt` é o valor visto na última checagem, que será comparado
    # contra a próxima pra saber se a carta mudou de edição.
    icao = Column(String(4), primary_key=True)
    tipo = Column(String(10), primary_key=True)
    amdt = Column(String(20), nullable=False)
    atualizado_em = Column(DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now(), nullable=False)


class CartaTexto(Base):
    __tablename__ = "carta_texto"

    nome = Column(String(80), primary_key=True)
    amdt = Column(String(20), nullable=False)
    texto = Column(Text, nullable=False)
    atualizado_em = Column(DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now(), nullable=False)


class ClasseEspacoAereoDetectada(Base):
    # Classe de espaço aéreo achada automaticamente numa carta.
    __tablename__ = "classe_espaco_aereo_detectada"

    icao = Column(String(4), primary_key=True)
    classe = Column(String(1), nullable=False)
    # Guarda o nome da carta de onde a classe saiu ("ARC RIO DE JANEIRO")
    fonte_tipo = Column(String(80), nullable=False)
    fonte_amdt = Column(String(20), nullable=False)
    detectado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
