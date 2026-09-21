# app/models/taf_forecast_period.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class TafForecastPeriod(Base):
    __tablename__ = "taf_forecast_periods"

    id = Column(Integer, primary_key=True, index=True)
    observation_id = Column(Integer, ForeignKey("observations.id"), nullable=False)
    tipo_periodo = Column(String(20), nullable=False) # INITIAL, BECMG, TEMPO, PROB
    validade_inicio = Column(DateTime(timezone=True), nullable=False)
    validade_fim = Column(DateTime(timezone=True), nullable=False)
    mensagem_bruta_periodo = Column(String, nullable=False) # A parte da mensagem TAF para este período
    teto_ft = Column(Integer, nullable=True)
    visibilidade_m = Column(Integer, nullable=True)
    status_operacional = Column(String(30), nullable=True)
    base_legal = Column(String(255), nullable=True)

    observation = relationship("Observation", back_populates="taf_forecast_periods")

    def __repr__(self):
        return f"<TafForecastPeriod(id={self.id}, tipo='{self.tipo_periodo}', validade='{self.validade_inicio}-{self.validade_fim}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "observation_id": self.observation_id,
            "tipo_periodo": self.tipo_periodo,
            "validade_inicio": self.validade_inicio,
            "validade_fim": self.validade_fim,
            "mensagem_bruta_periodo": self.mensagem_bruta_periodo,
            "teto_ft": self.teto_ft,
            "visibilidade_m": self.visibilidade_m,
            "status_operacional": self.status_operacional,
            "base_legal": self.base_legal,
        }