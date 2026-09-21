"""Decide quais observações devem ser gravadas a partir das mensagens coletadas.
Núcleo puro: recebe as mensagens já buscadas e devolve decisões. Não busca,
não grava, não loga, não olha o relógio, o instante de referência entra por
parâmetro. Quem executa é o coletor, em `app/jobs/hourly_collector.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.espaco_aereo import ClasseConhecida, classe_de, classe_verificada
from app.core.sol import JanelasSol, diurno_em
from app.core.vfr_classifier import classificar_condicao_vfr, teto_de_metar
from app.parsers.metar_parser import metar_parser
from app.parsers.taf_parser import taf_parser

METAR = "METAR"
TAF = "TAF"


@dataclass(frozen=True)
class ObservacaoDecidida:
    """Uma observação pronta para ser persistida, já classificada."""
    route_id: int
    icao: str
    tipo: str
    mensagem_bruta: str
    teto_ft: int | None
    visibilidade_m: int | None
    status_operacional: str
    base_legal: str
    recebimento: datetime
    aviso_temporario: str | None = None


@dataclass(frozen=True)
class MensagemIgnorada:
    """Uma mensagem que não virou observação, e o motivo."""
    tipo: str
    motivo: str


@dataclass(frozen=True)
class ResultadoDecisao:
    """O que gravar e o que foi descartado, tudo que o coletor precisa saber."""
    observacoes: tuple[ObservacaoDecidida, ...]
    ignoradas: tuple[MensagemIgnorada, ...]

    @property
    def vazio(self) -> bool:
        return not self.observacoes


def ler_recebimento(valor: object, padrao: datetime) -> datetime:
    """Converte o campo `recebimento` do envelope da API e cai no padrão se falhar.
    A REDEMET envia o instante em UTC, sem marcar o fuso ("2026-08-24 00:00:18").
    """
    if not isinstance(valor, str):
        return padrao
    try:
        lido = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return padrao
    if lido.tzinfo is None:
        lido = lido.replace(tzinfo=timezone.utc)
    return lido.astimezone(padrao.tzinfo)


def decidir_metar(*, icao: str, route_id: int, bruto: dict, agora: datetime,
                  janelas_sol: JanelasSol | None = None,
                  dentro_ctr_atz_por_icao: dict[str, bool] | None = None,
                  classes_detectadas: dict[str, ClasseConhecida] | None = None,
                  ) -> ObservacaoDecidida | MensagemIgnorada:
    """Classifica um METAR já baixado, pela observação no recebimento."""
    mensagem = bruto.get("mens")
    if not mensagem:
        return MensagemIgnorada(METAR, "mensagem ausente no envelope da API")
    dados = metar_parser.parse(mensagem)
    return _observacao(icao=icao, route_id=route_id, tipo=METAR, mensagem=mensagem,
                       dados=dados,
                       recebimento=ler_recebimento(bruto.get("recebimento"), agora),
                       janelas_sol=janelas_sol,
                       dentro_ctr_atz_por_icao=dentro_ctr_atz_por_icao,
                       classes_detectadas=classes_detectadas)


def decidir_taf(*, icao: str, route_id: int, bruto: dict, agora: datetime,
                janelas_sol: JanelasSol | None = None,
                dentro_ctr_atz_por_icao: dict[str, bool] | None = None,
                classes_detectadas: dict[str, ClasseConhecida] | None = None,
                ) -> ObservacaoDecidida | MensagemIgnorada:
    """Classifica um TAF já baixado, pela previsão operativa no recebimento."""
    mensagem = bruto.get("mens")
    recebido_em = bruto.get("recebimento")
    if not mensagem or not recebido_em:
        return MensagemIgnorada(TAF, "mensagem ou recebimento ausentes no envelope")
    recebimento = ler_recebimento(recebido_em, agora)
    previsoes = taf_parser.parse(mensagem, recebimento).get("previsoes") or []
    if not previsoes:
        return MensagemIgnorada(TAF, "nenhuma previsão reconhecida na mensagem")
    return _observacao(icao=icao, route_id=route_id, tipo=TAF, mensagem=mensagem,
                       dados=_becmg_operativo(previsoes, recebimento),
                       recebimento=recebimento, janelas_sol=janelas_sol,
                       dentro_ctr_atz_por_icao=dentro_ctr_atz_por_icao,
                       classes_detectadas=classes_detectadas,
                       aviso_temporario=_aviso_temporario_ativo(previsoes, recebimento))


def _becmg_operativo(previsoes: list[dict], momento: datetime) -> dict:
    """A previsão em vigor no instante: BASE, ou o BECMG mais recente já iniciado."""
    operativo = previsoes[0]
    inicio_do_operativo = None
    for previsao in previsoes:
        inicio = previsao.get("validade_inicio")
        if previsao["tipo"] != "BECMG" or inicio is None or inicio > momento:
            continue
        if inicio_do_operativo is None or inicio > inicio_do_operativo:
            operativo, inicio_do_operativo = previsao, inicio
    return operativo


def _aviso_temporario_ativo(previsoes: list[dict], momento: datetime) -> str | None:
    """Descreve um TEMPO/PROB em vigor no instante, não muda o status principal."""
    for previsao in previsoes:
        if previsao["tipo"] in ("BASE", "BECMG"):
            continue
        inicio, fim = previsao.get("validade_inicio"), previsao.get("validade_fim")
        if inicio and fim and inicio <= momento <= fim:
            return f"{previsao['tipo']} em vigor: {previsao['mensagem_secao_bruta']}"
    return None


def _observacao(*, icao: str, route_id: int, tipo: str, mensagem: str, dados: dict,
                recebimento: datetime, janelas_sol: JanelasSol | None,
                dentro_ctr_atz_por_icao: dict[str, bool] | None,
                classes_detectadas: dict[str, ClasseConhecida] | None = None,
                aviso_temporario: str | None = None) -> ObservacaoDecidida:
    """Monta a observação classificada a partir dos dados já extraídos."""
    cavok = bool(dados.get("cavok", False))
    teto = teto_de_metar(teto_ft=dados.get("teto_ft"), cavok=cavok,
                         vv_presente=bool(dados.get("vv_presente", False)))
    classificacao = classificar_condicao_vfr(
        visibilidade_m=dados.get("visibilidade_m"), teto=teto, cavok=cavok,
        classe_espaco_aereo=classe_de(icao, classes_detectadas),
        classe_verificada=classe_verificada(icao, classes_detectadas),
        diurno=diurno_em(icao, recebimento, janelas_sol or {}),
        dentro_ctr_atz=(dentro_ctr_atz_por_icao or {}).get(icao))
    return ObservacaoDecidida(
        route_id=route_id, icao=icao, tipo=tipo, mensagem_bruta=mensagem,
        teto_ft=dados.get("teto_ft"), visibilidade_m=dados.get("visibilidade_m"),
        status_operacional=classificacao.status.value,
        base_legal=classificacao.base_legal, recebimento=recebimento,
        aviso_temporario=aviso_temporario)


def decidir_observacoes(*, icao: str, route_id: int, metares: list[dict],
                        tafs: list[dict], agora: datetime,
                        janelas_sol: JanelasSol | None = None,
                        dentro_ctr_atz_por_icao: dict[str, bool] | None = None,
                        classes_detectadas: dict[str, ClasseConhecida] | None = None,
                        ) -> ResultadoDecisao:
    """Decide tudo que deve ser gravado para um aeródromo."""
    decisoes = [decidir_metar(icao=icao, route_id=route_id, bruto=b, agora=agora,
                              janelas_sol=janelas_sol,
                              dentro_ctr_atz_por_icao=dentro_ctr_atz_por_icao,
                              classes_detectadas=classes_detectadas)
                for b in metares]
    decisoes += [decidir_taf(icao=icao, route_id=route_id, bruto=b, agora=agora,
                             janelas_sol=janelas_sol,
                             dentro_ctr_atz_por_icao=dentro_ctr_atz_por_icao,
                             classes_detectadas=classes_detectadas)
                 for b in tafs]
    observacoes = tuple(d for d in decisoes if isinstance(d, ObservacaoDecidida))
    ignoradas = tuple(d for d in decisoes if isinstance(d, MensagemIgnorada))
    return ResultadoDecisao(observacoes=observacoes, ignoradas=ignoradas)
