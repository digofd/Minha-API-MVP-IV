# app/models/collection_log.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Identity
from sqlalchemy.sql import func
from app.database import Base

class CollectionLog(Base):
    __tablename__ = "collection_logs"
    id = Column(Integer, Identity(), primary_key=True, index=True) 
    icao = Column(String(255), nullable=False)
    sucesso = Column(Boolean, nullable=False)
    tentativas = Column(Integer, nullable=True)
    erro = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<CollectionLog(id={self.id}, icao='{self.icao}', sucesso={self.sucesso})>"
