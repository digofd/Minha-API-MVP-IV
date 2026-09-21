import os

for _nome, _valor in {
    "DATABASE_URL": "postgresql+asyncpg://teste:teste@localhost:1/teste",
    "HISTORICO_DATABASE_URL": "postgresql+asyncpg://teste:teste@localhost:1/teste",
    "REDEMET_BASE_URL": "http://redemet.invalido",
    "REDEMET_API_KEY": "chave-de-teste",
}.items():
    os.environ.setdefault(_nome, _valor)

from types import SimpleNamespace  

from app.config import settings  
from app.historico.coletor import ResultadoPreenchimento  
from app.routes.historico import coletar  


class ColetorHistoricoFalso:

    def __init__(self) -> None:
        self.dias_preenchidos: int | None = None
        self.dias_expurgados: int | None = None

    async def preencher(self, icaos: list[str], *, dias: int) -> ResultadoPreenchimento:
        self.dias_preenchidos = dias
        return ResultadoPreenchimento(1, 0, 0, 0, 1, ())

    async def expurgar(self, *, dias: int) -> int:
        self.dias_expurgados = dias
        return 0


class ResultadoConsultaFalso:
    def __init__(self, linhas: list[tuple[str, str]]) -> None:
        self._linhas = linhas

    def all(self) -> list[tuple[str, str]]:
        return self._linhas


class SessaoOperacionalFalsa:
    # Devolve as rotas ativas como o SELECT de origem/destino devolveria.
    async def execute(self, _consulta) -> ResultadoConsultaFalso:
        return ResultadoConsultaFalso([("SBSP", "SBGL")])


def _requisicao_com(coletor: ColetorHistoricoFalso) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(coletor_historico=coletor)))


async def test_janela_curta_coleta_pouco_mas_expurga_pela_retencao():
    coletor = ColetorHistoricoFalso()
    await coletar(_requisicao_com(coletor), dias=1, db=SessaoOperacionalFalsa())
    assert coletor.dias_preenchidos == 1
    assert coletor.dias_expurgados == settings.historico_dias


async def test_sem_dias_coleta_a_retencao_inteira():
    coletor = ColetorHistoricoFalso()
    await coletar(_requisicao_com(coletor), dias=None, db=SessaoOperacionalFalsa())
    assert coletor.dias_preenchidos == settings.historico_dias
