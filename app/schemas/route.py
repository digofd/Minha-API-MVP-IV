# DTOs da fronteira HTTP.

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.observation_schema import ObservationSchema


class RouteCreate(BaseModel):
    # Entrada de criação. O ICAO é normalizado aqui, na borda, uma vez só.

    origem_icao: str = Field(min_length=4, max_length=4, examples=["SBSP"])
    destino_icao: str = Field(min_length=4, max_length=4, examples=["SBGL"])
    ativa: bool = True

    @field_validator("origem_icao", "destino_icao")
    @classmethod
    def normalizar_icao(cls, valor: str) -> str:
        codigo = valor.strip().upper()
        if not codigo.isalnum():
            raise ValueError(f"código ICAO inválido: {valor!r}; esperado 4 caracteres "
                             "alfanuméricos, como 'SBSP'")
        return codigo

    @model_validator(mode="after")
    def origem_diferente_do_destino(self) -> "RouteCreate":
        # Rota de um aeródromo para ele mesmo não é rota.
        if self.origem_icao == self.destino_icao:
            raise ValueError(f"origem e destino iguais: {self.origem_icao!r}; esperado "
                             "dois aeródromos diferentes, como SBSP → SBGL")
        return self


class RouteUpdate(BaseModel):
    # Entrada do PUT: ativa ou desativa a rota na coleta horária.
    ativa: bool

class RouteOut(BaseModel):
    id: int
    origem_icao: str
    destino_icao: str
    ativa: bool
    criado_em: datetime
    total_observations: int = 0
    # Só as mais recentes `LIMITE_OBSERVACOES_DETALHE` em app/routes/routes.py.
    observations: List[ObservationSchema] = []

    class Config:
        from_attributes = True


class PaginaDeRotas(BaseModel):
    # Envelope de paginação: os itens mais o que o usuário precisa para navegar.
    itens: List[RouteOut]
    total: int
    pagina: int
    tamanho: int
    paginas: int


class ResumoRotaOut(BaseModel):
    # Resumo operacional de uma rota, para o painel.

    route_id: int
    origem_icao: str
    destino_icao: str
    total: int
    por_status: dict[str, int]
    status_atual: Optional[str] = None
    ultima_leitura: Optional[datetime] = None
    total_metar: int
    total_taf: int
