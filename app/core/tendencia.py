# Tendência histórica, sem IO, recebe as mensagens já baixadas e devolve pontos e resumos. 

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

from app.core.espaco_aereo import ClasseConhecida, classe_de, classe_verificada
from app.core.observacoes import MensagemIgnorada, ler_recebimento
from app.core.sol import JanelasSol, diurno_em
from app.core.vfr_classifier import classificar_condicao_vfr, teto_de_metar
from app.parsers.metar_parser import metar_parser

METAR = "METAR"
SPECI = "SPECI"

# Os parsers marcam "sem camada significativa" (CAVOK) com este valor. 
# Ele é um sentinela, não uma medição, entrando na estatística, 
# pois a amplitude do teto de 99.999 ft achataria o gráfico. 
# Na análise ele conta como ausência de teto medido,o ponto some da curva 
# e a linha liga ao próximo.
TETO_SEM_CAMADA_FT = 99999


@dataclass(frozen=True)
class Leitura:
    icao: str
    momento_utc: datetime
    tipo: str
    mensagem_bruta: str
    teto_ft: int | None
    visibilidade_m: int | None
    temperatura_c: int | None
    pressao_hpa: int | None
    status_operacional: str
    base_legal: str


@dataclass(frozen=True)
class Variacao:
    """A variação de uma grandeza num período, `amplitude` é max − min."""
    minimo: float | None
    maximo: float | None
    media: float | None
    amplitude: float | None

    @property
    def vazia(self) -> bool:
        return self.minimo is None


VAZIA = Variacao(None, None, None, None)


@dataclass(frozen=True)
class ResumoDia:
    """O que aconteceu num dia, por aeródromo."""
    dia: date
    teto: Variacao
    visibilidade: Variacao
    temperatura: Variacao
    pressao: Variacao
    leituras: int
    metares: int
    specis: int
    vfr: int
    vfr_especial: int
    abaixo_minimos: int
    indeterminado: int
    pior_teto_em: datetime | None
    pior_visibilidade_em: datetime | None

    @property
    def sem_dado(self) -> bool:
        return self.leituras == 0


def tipo_da_mensagem(mensagem: str) -> str:
    """SPECI ou METAR, lido do início da própria mensagem."""
    return SPECI if mensagem.lstrip().upper().startswith(SPECI) else METAR


def leitura_de_envelope(bruto: dict, *, agora: datetime,
                        janelas_sol: JanelasSol | None = None,
                        dentro_ctr_atz_por_icao: dict[str, bool] | None = None,
                        classes_detectadas: dict[str, ClasseConhecida] | None = None,
                        ) -> Leitura | MensagemIgnorada:
    """Interpreta um envelope da REDEMET. 
    Para cada envelope, devolve um ponto ou uma mensagem ignorada.
    """
    mensagem = (bruto.get("mens") or "").strip()
    if not mensagem:
        return MensagemIgnorada(METAR, "mensagem ausente no envelope da API")
    icao = _icao_da_mensagem(mensagem)
    if icao is None:
        return MensagemIgnorada(tipo_da_mensagem(mensagem),
                                f"não foi possível ler o ICAO em {mensagem[:40]!r}")
    dados = metar_parser.parse(mensagem)
    momento = ler_recebimento(bruto.get("recebimento"), agora)
    classificacao = classificar_condicao_vfr(
        visibilidade_m=dados.get("visibilidade_m"),
        teto=teto_de_metar(teto_ft=dados.get("teto_ft"),
                           cavok=bool(dados.get("cavok")),
                           vv_presente=bool(dados.get("vv_presente"))),
        cavok=bool(dados.get("cavok")),
        classe_espaco_aereo=classe_de(icao, classes_detectadas),
        classe_verificada=classe_verificada(icao, classes_detectadas),
        diurno=diurno_em(icao, momento, janelas_sol or {}),
        dentro_ctr_atz=(dentro_ctr_atz_por_icao or {}).get(icao))
    return Leitura(
        icao=icao,
        momento_utc=momento,
        tipo=tipo_da_mensagem(mensagem),
        mensagem_bruta=mensagem,
        teto_ft=dados.get("teto_ft"),
        visibilidade_m=dados.get("visibilidade_m"),
        temperatura_c=dados.get("temperatura_c"),
        pressao_hpa=dados.get("pressao_hpa"),
        status_operacional=classificacao.status.value,
        base_legal=classificacao.base_legal)


def _icao_da_mensagem(mensagem: str) -> str | None:
    """Segundo grupo da mensagem: 'METAR SBSP ...' ou 'SPECI SBSP ...'."""
    partes = mensagem.split()
    for parte in partes[1:3]:
        if len(parte) == 4 and parte.isalnum() and parte[:2].isalpha():
            return parte.upper()
    return None


def leituras_de_envelopes(envelopes: Iterable[dict], *, agora: datetime,
                          janelas_sol: JanelasSol | None = None,
                          dentro_ctr_atz_por_icao: dict[str, bool] | None = None,
                          classes_detectadas: dict[str, ClasseConhecida] | None = None,
                          ) -> tuple[tuple[Leitura, ...], tuple[MensagemIgnorada, ...]]:
    """Interpreta um lote, separando o que virou ponto do que foi descartado."""
    resultados = [leitura_de_envelope(e, agora=agora, janelas_sol=janelas_sol,
                                      dentro_ctr_atz_por_icao=dentro_ctr_atz_por_icao,
                                      classes_detectadas=classes_detectadas)
                 for e in envelopes]
    lidas = tuple(r for r in resultados if isinstance(r, Leitura))
    ignoradas = tuple(r for r in resultados if isinstance(r, MensagemIgnorada))
    return tuple(sorted(lidas, key=lambda l: l.momento_utc)), ignoradas


def teto_medido(teto_ft: int | None) -> int | None:
    """Teto como medição, o sentinela de 'sem camada' vira ausência."""
    if teto_ft is None or teto_ft >= TETO_SEM_CAMADA_FT:
        return None
    return teto_ft


def variacao_de(valores: Sequence[float | int | None]) -> Variacao:
    """Mínimo, máximo, média e amplitude, ignorando ausências."""
    presentes = [v for v in valores if v is not None]
    if not presentes:
        return VAZIA
    menor, maior = min(presentes), max(presentes)
    media = round(sum(presentes) / len(presentes), 1)
    return Variacao(minimo=menor, maximo=maior, media=media, amplitude=maior - menor)


def resumir_dia(dia: date, leituras: Sequence[Leitura]) -> ResumoDia:
    """Agrega as leituras de um dia. SPECI conta junto com METAR."""
    if not leituras:
        return ResumoDia(dia, VAZIA, VAZIA, VAZIA, VAZIA, 0, 0, 0, 0, 0, 0, 0, None, None)
    return ResumoDia(
        dia=dia,
        teto=variacao_de([teto_medido(l.teto_ft) for l in leituras]),
        visibilidade=variacao_de([l.visibilidade_m for l in leituras]),
        temperatura=variacao_de([l.temperatura_c for l in leituras]),
        pressao=variacao_de([l.pressao_hpa for l in leituras]),
        leituras=len(leituras),
        metares=sum(1 for l in leituras if l.tipo == METAR),
        specis=sum(1 for l in leituras if l.tipo == SPECI),
        vfr=sum(1 for l in leituras if l.status_operacional == "VFR"),
        vfr_especial=sum(1 for l in leituras
                         if l.status_operacional == "VFR_ESPECIAL"),
        abaixo_minimos=sum(1 for l in leituras
                           if l.status_operacional == "ABAIXO_MINIMOS_VFR"),
        indeterminado=sum(1 for l in leituras
                          if l.status_operacional == "INDETERMINADO"),
        pior_teto_em=_momento_do_menor(leituras, lambda l: teto_medido(l.teto_ft)),
        pior_visibilidade_em=_momento_do_menor(leituras, lambda l: l.visibilidade_m))


def _momento_do_menor(leituras: Sequence[Leitura], grandeza) -> datetime | None:
    """Instante em que a grandeza atingiu o menor valor do conjunto."""
    com_valor = [l for l in leituras if grandeza(l) is not None]
    if not com_valor:
        return None
    return min(com_valor, key=grandeza).momento_utc


def serie_diaria(leituras: Sequence[Leitura], *, ate: date,
                 dias: int) -> tuple[ResumoDia, ...]:
    """Um resumo por dia, do mais antigo ao mais recente."""
    por_dia: dict[date, list[Leitura]] = {}
    for leitura in leituras:
        por_dia.setdefault(leitura.momento_utc.date(), []).append(leitura)
    primeiro = ate - timedelta(days=dias - 1)
    return tuple(resumir_dia(primeiro + timedelta(days=n),
                             por_dia.get(primeiro + timedelta(days=n), []))
                 for n in range(dias))
