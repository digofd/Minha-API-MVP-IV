# Modelo do histórico, uma linha por leitura, por aeródromo.

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from app.historico.database import BaseHistorico


class LeituraHistorica(BaseHistorico):
    """Uma mensagem METAR ou SPECI já interpretada guardada por 15 dias.
    A chave é o aeródromo e não a rota: o mesmo SBSP serve várias rotas e não
    faz sentido coletar e guardar a mesma leitura de SBSPmais de uma vez.
    """

    __tablename__ = "leituras_historicas"
    __table_args__ = (
        # Torna a recoleta única e acomoda vários SPECI na mesma hora.
        UniqueConstraint("icao", "momento_utc", "tipo", "mensagem_bruta",
                         name="uq_leitura_historica"),
    )

    id = Column(Integer, primary_key=True, index=True)
    icao = Column(String(4), index=True, nullable=False)
    momento_utc = Column(DateTime(timezone=True), index=True, nullable=False)
    tipo = Column(String(6), nullable=False)  # METAR ou SPECI
    mensagem_bruta = Column(String, nullable=False)

    teto_ft = Column(Integer, nullable=True)
    visibilidade_m = Column(Integer, nullable=True)
    temperatura_c = Column(Integer, nullable=True)
    pressao_hpa = Column(Integer, nullable=True)

    status_operacional = Column(String(30), nullable=True)
    base_legal = Column(String(255), nullable=True)
