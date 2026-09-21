# Cliente HTTP da REDEMET, casca pura de IO, sem decisão de negócio.

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import httpx

""" A REDEMET recebe a chave como query string, então ela aparece em URL de erro e
em mensagem de exceção, nada que saia deste módulo pode carregá-la."""
_CHAVE_NA_URL = re.compile(r"(api_key=)[^&\s]+", re.IGNORECASE)


def redigir(texto: str) -> str:
    """Substitui a chave de API por asteriscos em qualquer texto de saída."""
    return _CHAVE_NA_URL.sub(r"\1***", texto)


@dataclass(frozen=True)
class Dados:
    """A consulta funcionou, a lista pode estar vazia."""
    mensagens: list[dict]


@dataclass(frozen=True)
class FalhaHttp:
    """O serviço respondeu com erro (401 de chave inválida, 500, etc.)."""
    status: int
    detalhe: str


@dataclass(frozen=True)
class FalhaRede:
    """Não houve resposta: timeout, DNS, conexão recusada."""
    motivo: str


ResultadoBusca = Dados | FalhaHttp | FalhaRede


def descrever(resultado: ResultadoBusca) -> str:
    if isinstance(resultado, Dados):
        return f"{len(resultado.mensagens)} mensagem(ns)"
    if isinstance(resultado, FalhaHttp):
        return f"HTTP {resultado.status}: {resultado.detalhe[:120]}"
    return f"falha de rede: {resultado.motivo}"


def mensagens_de(resultado: ResultadoBusca) -> list[dict]:
    return resultado.mensagens if isinstance(resultado, Dados) else []


class RedemetClient:
    """Acesso às mensagens METAR e TAF da REDEMET."""
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.AsyncClient()

    async def get_metar(self, icao: str, data_ini: datetime,
                        data_fim: datetime) -> ResultadoBusca:
        """Busca METARs do período informado."""
        params = {
            "api_key": self.api_key,
            "data_ini": data_ini.strftime("%Y%m%d%H"),
            "data_fim": data_fim.strftime("%Y%m%d%H"),
        }
        return await self._buscar(f"{self.base_url}/mensagens/metar/{icao}", params)

    async def get_metar_periodo(self, icaos: list[str], inicio: datetime,
                                fim: datetime) -> ResultadoBusca:
        """Busca METAR e SPECI de vários aeródromos num intervalo.
        A API aceita ICAOs separados por vírgula e devolve tudo o que houver
        na janela de tempo, mas não filtra por aeródromo, se um aeródromo não tiver
        mensagens no período, ele não aparece na resposta.
        """
        params = {
            "api_key": self.api_key,
            "data_ini": inicio.strftime("%Y%m%d%H"),
            "data_fim": fim.strftime("%Y%m%d%H"),
        }
        alvo = ",".join(icao.strip().upper() for icao in icaos if icao)
        return await self._buscar(f"{self.base_url}/mensagens/metar/{alvo}", params)

    async def get_taf(self, icao: str) -> ResultadoBusca:
        """Busca os TAFs válidos mais recentes. A API não filtra TAF por período, 
        então esta função não recebe datas.
        """
        return await self._buscar(f"{self.base_url}/mensagens/taf/{icao}",
                                  {"api_key": self.api_key})

    async def _buscar(self, url: str, params: dict) -> ResultadoBusca:
        """Executa a chamada e traduz cada modo de falha num caso distinto."""
        try:
            resposta = await self.client.get(url, params=params, timeout=10.0)
            resposta.raise_for_status()
        except httpx.HTTPStatusError as erro:
            return FalhaHttp(erro.response.status_code, redigir(erro.response.text))
        except httpx.RequestError as erro:
            return FalhaRede(redigir(f"{type(erro).__name__}: {erro}"))
        return _extrair_mensagens(resposta)

    async def close(self) -> None:
        await self.client.aclose()


def _extrair_mensagens(resposta: httpx.Response) -> ResultadoBusca:
    """Lê o corpo da resposta, não há lista vazia."""
    try:
        corpo = resposta.json()
    except ValueError as erro:
        return FalhaHttp(resposta.status_code, f"corpo não é JSON: {erro}")
    dados = corpo.get("data", {}) if isinstance(corpo, dict) else {}
    mensagens = dados.get("data", []) if isinstance(dados, dict) else []
    return Dados(mensagens if isinstance(mensagens, list) else [])
