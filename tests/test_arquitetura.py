import ast
from pathlib import Path

import pytest

NUCLEO = Path(__file__).resolve().parent.parent / "app" / "core"

INFRAESTRUTURA_PROIBIDA = {
    "sqlalchemy",   # ORM
    "httpx",        # cliente HTTP
    "requests",
    "fastapi",
    "apscheduler",
    "logging",      # log é preocupação transversal, decorator na borda
    "os",           # ambiente
}

MODULOS_DO_NUCLEO = sorted(p for p in NUCLEO.glob("*.py") if p.name != "__init__.py")


def _modulos_importados(caminho: Path) -> set[str]:
    # Nomes de topo de tudo que o arquivo importa.
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(alias.name.split(".")[0] for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module.split(".")[0])
    return nomes


@pytest.mark.parametrize("modulo", MODULOS_DO_NUCLEO, ids=lambda p: p.name)
def test_nucleo_nao_importa_infraestrutura(modulo: Path):
    proibidos = _modulos_importados(modulo) & INFRAESTRUTURA_PROIBIDA
    assert not proibidos, f"{modulo.name} importa infraestrutura: {sorted(proibidos)}"


def _chamadas_ao_relogio(caminho: Path) -> list[str]:
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    return [no.func.attr for no in ast.walk(arvore)
            if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
            and no.func.attr in {"now", "utcnow", "today"}]


@pytest.mark.parametrize("modulo", MODULOS_DO_NUCLEO, ids=lambda p: p.name)
def test_nucleo_nao_le_o_relogio(modulo: Path):
    chamadas = _chamadas_ao_relogio(modulo)
    assert not chamadas, f"{modulo.name} lê o relógio: {chamadas}"


def test_existe_uma_unica_implementacao_da_regra_vfr():
    classificadores = [p.name for p in NUCLEO.glob("*.py")
                       if "vfr" in p.name.lower() or "vrf" in p.name.lower()]
    assert classificadores == ["vfr_classifier.py"], classificadores
