# app/core/espaco_aereo.py

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from app.core.vfr_classifier import ClasseEspacoAereo


@dataclass(frozen=True)
class ClasseConhecida:
    """Uma classe de espaço aéreo confirmada, com a fonte exata da checagem."""

    classe: ClasseEspacoAereo
    fonte_tipo: str    # tipo de carta AISWEB usado (ex.: "VAC", "ADC")
    fonte_amdt: str    # AMDT (emenda AIRAC) da carta no momento da checagem
    verificado_em: date
    # False = checagem manual (CLASSES_CONHECIDAS) 
    # True = extração automática de PDF (app/deteccao_classe_espaco_aereo.py)
    automatico: bool = False


# Uma linha por ICAO checado manualmente contra a carta oficial da AISWEB.
CLASSES_CONHECIDAS: dict[str, ClasseConhecida] = {
    "SBSP": ClasseConhecida(ClasseEspacoAereo.D, "VAC", "2604A1", date(2026, 9, 8)),
}


def classe_de(icao: str, detectadas: dict[str, ClasseConhecida] | None = None) -> ClasseEspacoAereo:
    """Classe real se conhecida (manual ou detectada); G como default conservador."""
    conhecida = _resolver(icao, detectadas)
    return conhecida.classe if conhecida else ClasseEspacoAereo.G


def classe_verificada(icao: str, detectadas: dict[str, ClasseConhecida] | None = None) -> bool:
    """Se a classe deste ICAO veio de uma fonte real, não do fallback G."""
    return _resolver(icao, detectadas) is not None


def _resolver(icao: str, detectadas: dict[str, ClasseConhecida] | None) -> ClasseConhecida | None:
    chave = icao.strip().upper()
    return CLASSES_CONHECIDAS.get(chave) or (detectadas or {}).get(chave)


# A tabela de espaços aéreos da Carta de Área (ARC) sai do PDF como linhas
# soltas:
#     'GALEÃO'      <- nome da CTR
#     '- 2000 ft'   <- limite superior
#     'CTR'         <- tipo
#     'D GND '      <- classe + limite inferior
# A âncora é a linha "classe + GND/SFC": **CTR e ATZ sempre começam no solo**,
# então exigir GND/SFC descarta as linhas de CTA/TMA vizinhas (que começam em
# FL ou em altitude) e que, sem isso, seriam atribuídas ao aeródromo errado.
# Aceita "D GND" e também "C GND - FL 045", que algumas cartas põem na mesma
# linha. 
_ANCORA_CLASSE = re.compile(r"^([BCDEG])\s+(?:GND|SFC)\b")

_TIPOS_DE_ZONA = ("CTR", "ATZ")

# Quantas linhas ao redor do nome ainda contam como "a mesma entrada da tabela" 
# 5 cobre nome + limites + tipo + frequências sem alcançar a entrada seguinte
_JANELA = 5


def normalizar(texto: str) -> str:
    """Maiúsculas sem acento nem pontuação para bater o nome da carta com ROTAER."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]", " ", sem_acento)).strip().upper()


def nomes_alvo(nome_aerodromo: str | None, cidade: str | None) -> frozenset[str]:
    """Nomes pelos quais a CTR do aeródromo pode aparecer na carta.
    A CTR leva o nome do aeródromo (GALEÃO, para SBGL) ou o da cidade
    (FLORIANÓPOLIS, para SBFL), os dois entram como candidatos. O nome do
    aeródromo é cortado no primeiro hífen porque o ROTAER traz
    "Galeão - Antônio Carlos Jobim", e a carta traz só "GALEÃO".
    """
    alvos = set()
    if nome_aerodromo:
        alvos.add(normalizar(nome_aerodromo.split("-")[0]))
    if cidade:
        alvos.add(normalizar(cidade))
    return frozenset(a for a in alvos if a)


def classe_em_carta(linhas: list[str], alvos: frozenset[str]) -> ClasseEspacoAereo | None:
    """Classe do CTR/ATZ de um aeródromo, lida da tabela de uma Carta de Área.
    Procura as linhas que são exatamente um dos `alvos`, confirma que há
    "CTR"/"ATZ" na vizinhança (senão é TMA/CTA/FIR, que não valem aqui) e usa
    a âncora de classe **mais próxima** do nome, a tabela intercala entradas,
    então a mais distante costuma ser de outro espaço aéreo.
    `None` quando não acha, quando duas âncoras empatam em distância com
    classes diferentes, ou quando cartas diferentes discordam, fallback.
    Casa primeiro pelo nome exato, só se nada casar tenta a variante com
    sufixo numérico ("PORTO ALEGRE 1"), há algumas cartas que nomeiam setor de TMA,
    por isso fica como segunda tentativa.
    """
    for exigir_exato in (True, False):
        achadas = _classes_para(linhas, alvos, exigir_exato=exigir_exato)
        if len(achadas) == 1:
            return achadas.pop()
        if achadas:
            return None  # discordância: não promove
    return None


def _classes_para(linhas: list[str], alvos: frozenset[str], *,
                  exigir_exato: bool) -> set[ClasseEspacoAereo]:
    """Classes encontradas para os nomes alvo, uma por ocorrência reconhecida."""
    achadas: set[ClasseEspacoAereo] = set()
    for i, linha in enumerate(linhas):
        if not _e_nome_alvo(normalizar(linha), alvos, exigir_exato=exigir_exato):
            continue
        classe = _classe_mais_proxima(linhas, i)
        if classe is not None:
            achadas.add(classe)
    return achadas


def _e_nome_alvo(linha: str, alvos: frozenset[str], *, exigir_exato: bool) -> bool:
    if linha in alvos:
        return True
    if exigir_exato:
        return False
    return any(re.fullmatch(rf"{re.escape(alvo)} \d", linha) for alvo in alvos)


def _classe_mais_proxima(linhas: list[str], indice: int) -> ClasseEspacoAereo | None:
    """Âncora de classe mais perto do nome, se a vizinhança for de CTR/ATZ."""
    janela = range(max(0, indice - _JANELA), min(len(linhas), indice + _JANELA + 1))
    if not any(linhas[j].strip() in _TIPOS_DE_ZONA for j in janela):
        return None
    melhor: str | None = None
    menor_distancia = _JANELA + 1
    for j in janela:
        casou = _ANCORA_CLASSE.match(linhas[j].strip())
        if casou is None:
            continue
        distancia = abs(j - indice)
        if distancia < menor_distancia:
            melhor, menor_distancia = casou.group(1), distancia
        elif distancia == menor_distancia and casou.group(1) != melhor:
            melhor = None  # empate com classes diferentes, não dá pra decidir
    return ClasseEspacoAereo(melhor) if melhor else None
