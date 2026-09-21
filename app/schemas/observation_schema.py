# app/schemas/observation_schema.py
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class ObservationSchema(BaseModel):
    id: int
    route_id: int
    icao: str
    tipo: str
    mensagem_bruta: str
    teto_ft: Optional[int] = None
    visibilidade_m: Optional[int] = None
    status_operacional: Optional[str] = None
    base_legal: Optional[str] = None
    aviso_temporario: Optional[str] = None
    recebimento: datetime

    class Config:
        from_attributes = True


class PaginaDeObservacoes(BaseModel):
    itens: List[ObservationSchema]
    total: int
    pagina: int
    tamanho: int
    paginas: int