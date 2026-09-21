# DTOs da fronteira do histórico

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class LeituraOut(BaseModel):
    # Um ponto da série, como o gráfico precisa dele
    momento_utc: datetime
    tipo: str
    teto_ft: Optional[int] = None
    visibilidade_m: Optional[int] = None
    temperatura_c: Optional[int] = None
    pressao_hpa: Optional[int] = None
    status_operacional: Optional[str] = None
    mensagem_bruta: str

    class Config:
        from_attributes = True


class VariacaoOut(BaseModel):
    minimo: Optional[float] = None
    maximo: Optional[float] = None
    media: Optional[float] = None
    amplitude: Optional[float] = None


class ResumoDiaOut(BaseModel):
    dia: date
    teto: VariacaoOut
    visibilidade: VariacaoOut
    temperatura: VariacaoOut
    pressao: VariacaoOut
    leituras: int
    metares: int
    specis: int
    vfr: int
    vfr_especial: int
    abaixo_minimos: int
    indeterminado: int
    pior_teto_em: Optional[datetime] = None
    pior_visibilidade_em: Optional[datetime] = None
    sem_dado: bool


class HistoricoOut(BaseModel):
    # Série de um aeródromo: os pontos e o resumo por dia.

    icao: str
    dias: int
    leituras: List[LeituraOut]
    serie_diaria: List[ResumoDiaOut]


class HistoricoRotaOut(BaseModel):
    # Os dois aeródromos de uma rota, lado a lado.

    route_id: int
    origem: HistoricoOut
    destino: HistoricoOut


class ColetaOut(BaseModel):
    # O que o preenchimento conseguiu e o que não conseguiu.

    icaos: List[str]
    dias: int
    janelas: int
    lidas: int
    gravadas: int
    ignoradas: int
    janelas_vazias: int
    falhas: List[str]
    expurgadas: int
