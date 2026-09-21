# app/schemas/taf_forecast_period_schema.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class TafForecastPeriodSchema(BaseModel):
    id: int
    observation_id: int
    tipo_periodo: str
    validade_inicio: datetime
    validade_fim: datetime
    mensagem_bruta_periodo: str
    teto_ft: Optional[int] = None
    visibilidade_m: Optional[int] = None
    status_operacional: Optional[str] = None
    base_legal: Optional[str] = None

    class Config:
        from_attributes = True
