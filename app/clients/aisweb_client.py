"""Cliente HTTP da API AISWEB (DECEA), casca pura de IO, sem decisão de negócio."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from xml.etree import ElementTree

import httpx

_CHAVE_NA_URL = re.compile(r"(api(?:K|k)ey=|api(?:P|p)ass=)[^&\s]+")


def redigir(texto: str) -> str:
    """Substitui apiKey/apiPass por asteriscos em qualquer texto de saída."""
    return _CHAVE_NA_URL.sub(r"\1***", texto)


@dataclass(frozen=True)
class DiaSol:
    """Nascer e pôr do sol de um aeródromo, num dia em UTC."""
    data: date
    nascer_utc: datetime
    por_utc: datetime


@dataclass(frozen=True)
class DadosSol:
    dias: tuple[DiaSol, ...]


@dataclass(frozen=True)
class DadosAerodromo:
    """O que este cliente lê dos dados do aeródromo."""
    dentro_ctr_atz: bool
    # Nome e cidade entram para achar a CTR do aeródromo na Carta de Área:
    # ela leva o nome do aeródromo ("GALEÃO") ou o da cidade
    # ("FLORIANÓPOLIS") — ver app/core/espaco_aereo.py::nomes_alvo.
    nome: str = ""
    cidade: str = ""


@dataclass(frozen=True)
class CartaResumo:
    """Uma carta/publicação da AISWEB."""
    tipo: str       # "VAC", "ADC", "ARC"...
    amdt: str       # emenda AIRAC, ex.: "2604A1"
    dt_public: str  # data de publicação, como a API devolve
    link: str = ""  # URL de download (já com a chave embutida) — "" se ausente
    nome: str = ""  # nome da carta, ex.: "ARC RIO DE JANEIRO"


@dataclass(frozen=True)
class DadosCartas:
    itens: tuple[CartaResumo, ...]


@dataclass(frozen=True)
class FalhaHttp:
    status: int
    detalhe: str


@dataclass(frozen=True)
class FalhaRede:
    motivo: str


ResultadoSol = DadosSol | FalhaHttp | FalhaRede
ResultadoAerodromo = DadosAerodromo | FalhaHttp | FalhaRede
ResultadoCartas = DadosCartas | FalhaHttp | FalhaRede

# Callsigns de torre observados no ROTAER (COM tipo TORRE/TWR). Aeródromo com
# torre ativa opera dentro de CTR, por definição do espaço aéreo brasileiro,
# a API não expõe a geometria da CTR diretamente.
_PALAVRAS_DE_TORRE = ("TORRE", "TWR")


def descrever_falha(resultado: FalhaHttp | FalhaRede) -> str:
    """Texto curto para log."""
    if isinstance(resultado, FalhaHttp):
        return f"HTTP {resultado.status}: {resultado.detalhe[:120]}"
    return f"falha de rede: {resultado.motivo}"


class AiswebClient:
    """Acesso a nascer/pôr do sol e dados de aeródromo da AISWEB."""
    def __init__(self, base_url: str, api_key: str, api_pass: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.api_pass = api_pass
        self.client = httpx.AsyncClient()

    async def get_sol(self, icao: str, inicio: date, fim: date) -> ResultadoSol:
        """Nascer/pôr do sol do aeródromo para cada dia do período, numa chamada só."""
        resultado = await self._buscar({
            "apiKey": self.api_key, "apiPass": self.api_pass, "area": "sol",
            "icaoCode": icao, "dt_i": inicio.isoformat(), "dt_f": fim.isoformat(),
        })
        if isinstance(resultado, (FalhaHttp, FalhaRede)):
            return resultado
        return _extrair_sol(resultado)

    async def get_info_aerodromo(self, icao: str) -> ResultadoAerodromo:
        """Dados do aeródromo só extrai a presença de torre (COM/TWR)."""
        resultado = await self._buscar({
            "apiKey": self.api_key, "apiPass": self.api_pass, "area": "rotaer",
            "icaoCode": icao,
        })
        if isinstance(resultado, (FalhaHttp, FalhaRede)):
            return resultado
        return _extrair_aerodromo(resultado)

    async def get_cartas(self, icao: str | None = None,
                        tipo: str | None = None) -> ResultadoCartas:
        """Lista de cartas/publicações — por aeródromo, por tipo, ou os dois.
        Sem `icao` e com `tipo="ARC"` devolve as Cartas de Área do país
        inteiro (20 cartas), que é como a detecção de classe as busca.
        """
        params = {"apiKey": self.api_key, "apiPass": self.api_pass, "area": "cartas"}
        if icao:
            params["icaoCode"] = icao
        if tipo:
            params["tipo"] = tipo
        resultado = await self._buscar(params)
        if isinstance(resultado, (FalhaHttp, FalhaRede)):
            return resultado
        return _extrair_cartas(resultado)

    async def get_carta_pdf(self, link: str) -> bytes | FalhaHttp | FalhaRede:
        """Baixa o PDF de uma carta a partir do `link` que `get_cartas` devolveu.
        `link` já é uma URL absoluta com a chave embutida (formato de download
        da AISWEB, diferente do `area=` usado em `_buscar`) que chama direto.
        """
        try:
            resposta = await self.client.get(link, timeout=20.0, follow_redirects=True)
            resposta.raise_for_status()
        except httpx.HTTPStatusError as erro:
            return FalhaHttp(erro.response.status_code, redigir(erro.response.text[:200]))
        except httpx.RequestError as erro:
            return FalhaRede(redigir(f"{type(erro).__name__}: {erro}"))
        return resposta.content

    async def _buscar(self, params: dict) -> ElementTree.Element | FalhaHttp | FalhaRede:
        """Executa a chamada e traduz cada modo de falha."""
        try:
            resposta = await self.client.get(self.base_url, params=params, timeout=10.0)
            resposta.raise_for_status()
        except httpx.HTTPStatusError as erro:
            return FalhaHttp(erro.response.status_code, redigir(erro.response.text))
        except httpx.RequestError as erro:
            return FalhaRede(redigir(f"{type(erro).__name__}: {erro}"))
        try:
            return ElementTree.fromstring(resposta.text)
        except ElementTree.ParseError as erro:
            return FalhaHttp(resposta.status_code, f"XML inválido: {erro}")

    async def close(self) -> None:
        await self.client.aclose()


def _extrair_sol(raiz: ElementTree.Element) -> ResultadoSol:
    """Lê cada `<item>` ou equivalente com date/sunrise/sunset, em qualquer nível."""
    dias: list[DiaSol] = []
    for no in raiz.iter():
        data_txt = _texto_de(no, "date")
        nascer_txt = _texto_de(no, "sunrise")
        por_txt = _texto_de(no, "sunset")
        if data_txt is None or nascer_txt is None or por_txt is None:
            continue
        try:
            dia = date.fromisoformat(data_txt[:10])
            dias.append(DiaSol(
                data=dia,
                nascer_utc=_parse_hora(dia, nascer_txt),
                por_utc=_parse_hora(dia, por_txt)))
        except ValueError:
            continue
    return DadosSol(tuple(dias))


def _texto_de(no: ElementTree.Element, tag: str) -> str | None:
    filho = no.find(tag)
    return filho.text.strip() if filho is not None and filho.text else None


def _parse_hora(dia: date, valor: str) -> datetime:
    """Combina a data com um horário em 'HH:MM', 'HHMM' ou datetime ISO completo."""
    valor = valor.strip()
    if "T" in valor or "-" in valor[:5]:
        convertido = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        return convertido if convertido.tzinfo else convertido.replace(tzinfo=timezone.utc)
    digitos = valor.replace(":", "")
    hora, minuto = int(digitos[:2]), int(digitos[2:4])
    return datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=timezone.utc)


def _extrair_aerodromo(raiz: ElementTree.Element) -> DadosAerodromo:
    """Presença de torre: `<service type="COM"><type>Torre</type>...`.
    O atributo `type` (categoria: COM/NAV/AirportGroundService/...) e o
    elemento filho `<type>` (subtipo: Torre/Solo/Tráfego/ATIS/...) têm o mesmo
    nome mas significam coisas diferentes, `servico.get("type")` só lê o atributo.
    """
    nome = _primeiro_texto(raiz, "name")
    cidade = _primeiro_texto(raiz, "city")
    for servico in raiz.iter("service"):
        categoria = (servico.get("type") or "").upper()
        subtipo = (_texto_de(servico, "type") or "").upper()
        if categoria == "COM" and any(p in subtipo for p in _PALAVRAS_DE_TORRE):
            return DadosAerodromo(dentro_ctr_atz=True, nome=nome, cidade=cidade)
    return DadosAerodromo(dentro_ctr_atz=False, nome=nome, cidade=cidade)


def _primeiro_texto(raiz: ElementTree.Element, tag: str) -> str:
    """Primeiro valor da tag em qualquer profundidade."""
    for no in raiz.iter(tag):
        if no.text and no.text.strip():
            return no.text.strip()
    return ""


def _extrair_cartas(raiz: ElementTree.Element) -> DadosCartas:
    """Lê cada `<item>` com tipo/amdt/dtPublic/link, e ignora o que não tiver tipo e amdt."""
    itens: list[CartaResumo] = []
    for item in raiz.iter("item"):
        tipo = _texto_de(item, "tipo")
        amdt = _texto_de(item, "amdt")
        if tipo is None or amdt is None:
            continue
        itens.append(CartaResumo(
            tipo=tipo, amdt=amdt, dt_public=_texto_de(item, "dtPublic") or "",
            link=_texto_de(item, "link") or "", nome=_texto_de(item, "nome") or ""))
    return DadosCartas(tuple(itens))
