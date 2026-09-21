""" Núcleo puro: sem IO, sem relógio, sem log. Recebe dados, devolve decisão.

REFERÊNCIA NORMATIVA: ICA 100-12, Art. 104, Tabela 1 — conferida no documento
oficial. Visibilidade de 5 km e distância vertical de nuvens de 300 m (1.000 pés)
para a faixa de aeródromo.

LIMITAÇÕES ASSUMIDAS (explícitas de propósito):
  - O METAR informa teto, não distância a nuvens, então o teto é o proxy do
    afastamento vertical de 1.000 pés exigido pela norma.
  - Classes F e G têm, na Tabela 1, o critério "livre de nuvens e avistando o
    solo", que não se expressa como número. Aqui todas as classes usam o mesmo
    limiar numérico, o que é mais restritivo para F e G.
  - Assume-se asa fixa, condição de aeródromo (não de rota). A faixa de 8 km, a
    3.050 m (10.000 pés) AMSL ou acima, é de rota e está fora daqui.
  - VFR especial (ICA 100-12, Art. 134: teto >= 1.000 ft e visibilidade >=
    3.000 m, cumulativos, só em período diurno e dentro de CTR/ATZ), calculado com dado real: 
    `diurno` vem do horário de nascer/pôr do sol da API AISWEB (DECEA) para o aeródromo e o instante da leitura;
    `dentro_ctr_atz` vem da presença de torre (TWR) nos dados do aeródromo,
    também da AISWEB, o aeródromo com torre ativa opera dentro de CTR, por
    definição do espaço aéreo brasileiro (a API não expõe geometria de CTR/TMA
    diretamente). Nenhuma das duas é calculada, o núcleo só recebe os
    booleanos já prontos quem busca é a casca (`app/clients/aisweb_client.py`).
    Quando `diurno`/`dentro_ctr_atz` vêm `None` (indisponível) ou `False`, a
    leitura cai em `ABAIXO_MINIMOS_VFR`: decisão conservadora, já que o app é informativo, 
    não autoritativo, e um falso "VFR Especial" custa mais caro que um falso "abaixo dos mínimos".
  - O mínimo de visibilidade do VFR Especial (3.000 m) é o genérico do Art. 134.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ClasseEspacoAereo(str, Enum):
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    G = "G"


class StatusOperacional(str, Enum):
    VFR = "VFR"
    VFR_ESPECIAL = "VFR_ESPECIAL"
    ABAIXO_MINIMOS_VFR = "ABAIXO_MINIMOS_VFR"
    INDETERMINADO = "INDETERMINADO"


@dataclass(frozen=True)
class TetoIlimitado:
    """Sem camada BKN/OVC significativa, céu claro, ou apenas FEW/SCT."""


@dataclass(frozen=True)
class TetoMedido:
    """Base da camada BKN/OVC mais baixa, ou visibilidade vertical (VV)."""

    pes: int


@dataclass(frozen=True)
class TetoDesconhecido:
    """A mensagem não permitiu determinar o teto."""

Teto = TetoIlimitado | TetoMedido | TetoDesconhecido


# Mínimos VMC — ICA 100-12, Art. 104, Tabela 1 (conferidos no documento oficial)
# A tabela oficial tem três faixas de altitude. Este classificador avalia
# condição **de aeródromo**, que cai na faixa mais baixa (a 900 m (3.000 pés)
# AMSL ou abaixo, ou 300 m (1.000 pés) acima do terreno, o que for maior):
#   • Visibilidade em voo: 5 km para C/D/E/F/G — **8 km para Classe B**.
#   • Classes B, C, D, E: distância de nuvens de 1.500 m horizontal e
#     300 m (1.000 pés) verticalmente.
#   • Classes F e G: "livre de nuvens e avistando o solo".
#
# A faixa de 8 km (a 3.050 m/10.000 pés AMSL ou acima) é de altitude de rota e
# está fora do escopo desta função, que classifica o aeródromo.

_VISIBILIDADE_MINIMA_M = 5000
_VISIBILIDADE_MINIMA_CLASSE_B_M = 8000

# Distância vertical de nuvens: 300 m (1.000 pés), conforme a Tabela 1.
# O METAR não informa distância a nuvens, informa teto, então o teto é usado
# como proxy do afastamento vertical exigido pela norma.

_DISTANCIA_VERTICAL_NUVENS_FT = 1000

_MINIMOS_VMC: dict[ClasseEspacoAereo, dict[str, int]] = {
    classe: {
        "visibilidade_m": (_VISIBILIDADE_MINIMA_CLASSE_B_M
                           if classe is ClasseEspacoAereo.B else _VISIBILIDADE_MINIMA_M),
        "teto_ft": _DISTANCIA_VERTICAL_NUVENS_FT,
    }
    for classe in ClasseEspacoAereo
}

# VFR Especial (Art. 134): mesmo teto mínimo do VFR normal, visibilidade menor.
_VISIBILIDADE_MINIMA_ESPECIAL_M = 3000


@dataclass(frozen=True)
class ClassificacaoVfr:
    """Decisão do núcleo: o que foi decidido, por qual critério e com que base."""

    status: StatusOperacional
    base_legal: str
    motivo: str


def teto_de_metar(*, teto_ft: int | None, cavok: bool, vv_presente: bool) -> Teto:
    """Traduz a saída dos parsers para o tipo de teto do domínio.
    A ausência de camada é tratada como tetoilimitado, que é a semântica dos parsers atuais.
    Falta de dado é detectada pela visibilidade, na função de classificação.
    """
    if cavok:
        return TetoIlimitado()
    if vv_presente and teto_ft is not None:
        return TetoMedido(teto_ft)
    if teto_ft is None:
        return TetoIlimitado()
    return TetoMedido(teto_ft)


_AVISO_CLASSE_NAO_VERIFICADA = (
    " A classe do espaço aéreo deste aeródromo ainda não verificada, assumida G,fallback conservador."
)


def _base_legal(classe: ClasseEspacoAereo, *, verificada: bool = True) -> str:

    texto = (f"ICA 100-12, mínimos VMC - Classe {classe.value}, "
            f"abaixo de 3.000ft AMSL / 1.000ft AGL")
    return texto if verificada else texto + _AVISO_CLASSE_NAO_VERIFICADA


def _base_legal_especial(classe: ClasseEspacoAereo) -> str:
    """Base legal do VFR Especial, citação distinta da do VFR normal."""
    return f"ICA 100-12, Art. 134 (VFR Especial) - Classe {classe.value}"


def classificar_condicao_vfr(
    *,
    visibilidade_m: int | None,
    teto: Teto,
    cavok: bool = False,
    classe_espaco_aereo: ClasseEspacoAereo = ClasseEspacoAereo.G,
    classe_verificada: bool = True,
    diurno: bool | None = None,
    dentro_ctr_atz: bool | None = None,
) -> ClassificacaoVfr:
    """Classifica condição VFR, VFR Especial ou abaixo dos mínimos."""
    base_legal = _base_legal(classe_espaco_aereo, verificada=classe_verificada)
    if cavok:
        return ClassificacaoVfr(StatusOperacional.VFR, base_legal, "CAVOK")
    if visibilidade_m is None or isinstance(teto, TetoDesconhecido):
        return ClassificacaoVfr(StatusOperacional.INDETERMINADO, base_legal,
                                "dados insuficientes")
    return _avaliar_minimos(visibilidade_m, teto, _MINIMOS_VMC[classe_espaco_aereo],
                            base_legal, classe_espaco_aereo,
                            diurno=diurno, dentro_ctr_atz=dentro_ctr_atz)


def _avaliar_minimos(visibilidade_m: int, teto: Teto, minimos: dict[str, int],
                     base_legal: str, classe: ClasseEspacoAereo, *,
                     diurno: bool | None, dentro_ctr_atz: bool | None) -> ClassificacaoVfr:
    """Compara visibilidade e teto contra os mínimos, informando qual reprovou."""
    if isinstance(teto, TetoMedido) and teto.pes < minimos["teto_ft"]:
        return ClassificacaoVfr(
            StatusOperacional.ABAIXO_MINIMOS_VFR, base_legal,
            f"teto {teto.pes} ft < {minimos['teto_ft']} ft")
    if visibilidade_m >= minimos["visibilidade_m"]:
        return ClassificacaoVfr(StatusOperacional.VFR, base_legal, "mínimos atendidos")
    if (visibilidade_m >= _VISIBILIDADE_MINIMA_ESPECIAL_M
            and diurno is True and dentro_ctr_atz is True):
        return ClassificacaoVfr(
            StatusOperacional.VFR_ESPECIAL, _base_legal_especial(classe),
            f"visibilidade {visibilidade_m} m abaixo do VFR normal "
            f"({minimos['visibilidade_m']} m), dentro do mínimo do VFR Especial "
            f"({_VISIBILIDADE_MINIMA_ESPECIAL_M} m); diurno e dentro de CTR/ATZ confirmados")
    return ClassificacaoVfr(
        StatusOperacional.ABAIXO_MINIMOS_VFR, base_legal,
        f"visibilidade {visibilidade_m} m < {minimos['visibilidade_m']} m")
