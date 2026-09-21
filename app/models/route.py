# app/models/route.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    origem_icao = Column(String, index=True)
    destino_icao = Column(String, index=True)
    ativa = Column(Boolean, default=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    observations = relationship(
        "Observation",
        back_populates="route",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self):
        return f"<Route(id={self.id}, origem_icao='{self.origem_icao}', destino_icao='{self.destino_icao}')>"