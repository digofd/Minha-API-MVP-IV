# app/models/observation.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("route_id", "icao", "tipo", "mensagem_bruta", "recebimento",
                         name="uq_observation_natural_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id"), index=True, nullable=False)
    icao = Column(String(4), index=True, nullable=False)
    tipo = Column(String(10), nullable=False) # METAR ou TAF
    mensagem_bruta = Column(String, nullable=False)
    teto_ft = Column(Integer, nullable=True)
    visibilidade_m = Column(Integer, nullable=True)
    status_operacional = Column(String(30), nullable=True) # VFR, MVFR, IFR, LIFR
    base_legal = Column(String(255), nullable=True) # "ICA 100-12"
    recebimento = Column(DateTime(timezone=True), server_default=func.now())
    aviso_temporario = Column(String(255), nullable=True)

    # Adiciona o relacionamento com Route
    route = relationship("Route", back_populates="observations")