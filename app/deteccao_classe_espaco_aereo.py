# app/deteccao_classe_espaco_aereo.py

from __future__ import annotations

import logging
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from app.aisweb_cache import CacheAisweb
from app.clients.aisweb_client import (
    AiswebClient, DadosAerodromo, DadosCartas, descrever_falha,
)
from app.core.espaco_aereo import (
    CLASSES_CONHECIDAS, ClasseConhecida, classe_em_carta, nomes_alvo,
)

logger = logging.getLogger(__name__)

TIPO_CARTA_DE_AREA = "ARC"


class DetectorDeClasse:
    """Acha e grava a classe de um ICAO a partir das Cartas de Área.
    Recebe `AiswebClient` (busca) e `CacheAisweb` (persistência) prontos, a
    raiz de composição (`app/main.py`) monta os dois uma vez só.
    """
    def __init__(self, cliente: AiswebClient, cache: CacheAisweb) -> None:
        self._cliente = cliente
        self._cache = cache

    async def detectar_e_gravar(self, icao: str) -> ClasseConhecida | None:
        # Detecta a classe de `icao`, se ainda não houver uma conhecida.
        chave = icao.strip().upper()
        if chave in CLASSES_CONHECIDAS:
            return CLASSES_CONHECIDAS[chave]
        ja_detectada = await self._cache.classes_detectadas_por_icao([chave])
        if chave in ja_detectada:
            return ja_detectada[chave]

        alvos = await self._nomes_do_aerodromo(chave)
        if not alvos:
            logger.info("sem nome/cidade no ROTAER para %s — sem como achar a CTR "
                        "na Carta de Área; continua no fallback G", chave)
            return None

        cartas = await self._cartas_de_area()
        if not cartas:
            return None

        classes = {}
        for nome_carta, amdt, linhas in cartas:
            classe = classe_em_carta(linhas, alvos)
            if classe is not None:
                classes.setdefault(classe, []).append((nome_carta, amdt))
        if not classes:
            logger.info("nenhuma Carta de Área trouxe a CTR de %s (%s) — continua no "
                        "fallback G", chave, ", ".join(sorted(alvos)))
            return None
        if len(classes) > 1:
            logger.warning("cartas discordam sobre a classe de %s (%s) — não promove "
                           "nenhuma, continua no fallback G", chave,
                           {c.value: [n for n, _ in v] for c, v in classes.items()})
            return None

        classe, fontes = next(iter(classes.items()))
        nome_carta, amdt = fontes[0]
        conhecida = ClasseConhecida(classe=classe, fonte_tipo=nome_carta, fonte_amdt=amdt,
                                    verificado_em=date.today(), automatico=True)
        await self._cache.gravar_classe_detectada(chave, conhecida)
        logger.warning("classe de espaço aéreo detectada para %s: Classe %s (fonte %s, "
                       "AMDT %s; %s carta(s) concordando)", chave, classe.value,
                       nome_carta, amdt, len(fontes))
        return conhecida

    async def _nomes_do_aerodromo(self, icao: str) -> frozenset[str]:
        # Nome e cidade do ROTAER, normalizados, chave de busca na carta
        resposta = await self._cliente.get_info_aerodromo(icao)
        if not isinstance(resposta, DadosAerodromo):
            logger.warning("ROTAER indisponível para %s: %s", icao, descrever_falha(resposta))
            return frozenset()
        return nomes_alvo(resposta.nome, resposta.cidade)

    async def _cartas_de_area(self) -> list[tuple[str, str, list[str]]]:
        # Texto de cada Carta de Área, do cache, baixa e extrai o que faltar.
        resposta = await self._cliente.get_cartas(tipo=TIPO_CARTA_DE_AREA)
        if not isinstance(resposta, DadosCartas):
            logger.warning("lista de Cartas de Área indisponível: %s",
                           descrever_falha(resposta))
            return []

        em_cache = await self._cache.textos_de_cartas()
        cartas: list[tuple[str, str, list[str]]] = []
        for item in resposta.itens:
            if not item.nome or not item.link:
                continue
            guardado = em_cache.get(item.nome)
            if guardado is not None and guardado[0] == item.amdt:
                cartas.append((item.nome, item.amdt, guardado[1].split("\n")))
                continue
            texto = await self._texto_da_carta(item.link)
            if texto is None:
                continue
            await self._cache.gravar_texto_de_carta(item.nome, item.amdt, texto)
            logger.info("Carta de Área lida e guardada: %s (AMDT %s)", item.nome, item.amdt)
            cartas.append((item.nome, item.amdt, texto.split("\n")))
        return cartas

    async def _texto_da_carta(self, link: str) -> str | None:
        # Baixa o PDF e devolve o texto de todas as páginas ou `None` na falha.
        pdf = await self._cliente.get_carta_pdf(link)
        if not isinstance(pdf, bytes):
            logger.warning("carta indisponível ao detectar classe: %s", descrever_falha(pdf))
            return None
        try:
            leitor = PdfReader(BytesIO(pdf))
            return "".join(pagina.extract_text() or "" for pagina in leitor.pages)
        except Exception:
            logger.exception("falha ao ler PDF de carta")
            return None
