from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.clients.aisweb_client import (
    AiswebClient, DadosAerodromo, DadosCartas, DadosSol, descrever_falha,
)
from app.core.espaco_aereo import ClasseConhecida
from app.core.sol import JanelasSol
from app.core.vfr_classifier import ClasseEspacoAereo
from app.models.aisweb_cache import (
    AerodromoInfo, CartaAmdtVista, CartaTexto, ClasseEspacoAereoDetectada, SolDiario,
)

logger = logging.getLogger(__name__)

_VALIDADE_AERODROMO_INFO = timedelta(days=30)


class CacheAisweb:
    """
    `janelas_sol` e `dentro_ctr_atz_por_icao` para o núcleo, buscando
    na AISWEB só o que falta no cache.
    """
    def __init__(self, cliente: AiswebClient, sessao_factory) -> None:
        self._cliente = cliente
        self._sessao_factory = sessao_factory

    async def janela_sol(self, icao: str, inicio: date, fim: date) -> JanelasSol:
        # Nascer/pôr do sol de cada dia do período, uma chamada por lacuna, não por dia.
        async with self._sessao_factory() as sessao:
            linhas = (await sessao.execute(
                select(SolDiario).where(
                    SolDiario.icao == icao,
                    SolDiario.data >= inicio, SolDiario.data <= fim))).scalars().all()
        resultado: JanelasSol = {(icao, l.data): (l.nascer_utc, l.por_utc) for l in linhas}

        todos_os_dias = {inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)}
        faltando = todos_os_dias - {d for (_, d) in resultado}
        if not faltando:
            return resultado

        resposta = await self._cliente.get_sol(icao, min(faltando), max(faltando))
        if not isinstance(resposta, DadosSol):
            logger.warning("nascer/pôr do sol indisponível para %s: %s",
                           icao, descrever_falha(resposta))
            return resultado

        novos = [d for d in resposta.dias if d.data in faltando]
        if novos:
            async with self._sessao_factory() as sessao:
                for dia in novos:
                    await sessao.merge(SolDiario(
                        icao=icao, data=dia.data,
                        nascer_utc=dia.nascer_utc, por_utc=dia.por_utc))
                await sessao.commit()
        resultado.update({(icao, d.data): (d.nascer_utc, d.por_utc) for d in novos})
        return resultado

    async def dentro_ctr_atz(self, icao: str) -> bool | None:
        # Se o aeródromo opera com torre. `None` só se nunca respondeu e a AISWEB falhou.
        async with self._sessao_factory() as sessao:
            linha = (await sessao.execute(
                select(AerodromoInfo).where(AerodromoInfo.icao == icao))
                    ).scalar_one_or_none()
        if linha is not None and (
                datetime.now(timezone.utc) - linha.atualizado_em < _VALIDADE_AERODROMO_INFO):
            return linha.dentro_ctr_atz

        resposta = await self._cliente.get_info_aerodromo(icao)
        if not isinstance(resposta, DadosAerodromo):
            logger.warning("dados de aeródromo indisponíveis para %s: %s",
                           icao, descrever_falha(resposta))
            return linha.dentro_ctr_atz if linha is not None else None

        async with self._sessao_factory() as sessao:
            await sessao.merge(AerodromoInfo(
                icao=icao, dentro_ctr_atz=resposta.dentro_ctr_atz,
                atualizado_em=datetime.now(timezone.utc)))
            await sessao.commit()
        return resposta.dentro_ctr_atz

    async def dentro_ctr_atz_por_icao(self, icaos: list[str]) -> dict[str, bool]:
        # Atalho para várias localidades, usado pelo histórico, que coleta em lote.
        resultado = {}
        for icao in icaos:
            valor = await self.dentro_ctr_atz(icao)
            if valor is not None:
                resultado[icao] = valor
        return resultado

    async def checar_edicao_da_carta(self, icao: str, tipo: str) -> None:
        """
        Compara o AMDT atual da carta-fonte com o último visto e avisa se mudou.
        Chamado pela tarefa periódica de `app/main.py` para cada ICAO de
        `app/core/espaco_aereo.py::CLASSES_CONHECIDAS`. Só grava o novo AMDT como "visto" e
        loga um aviso quando ele mudou, pra alguém reconferir manualmente.
        """
        resposta = await self._cliente.get_cartas(icao)
        if not isinstance(resposta, DadosCartas):
            logger.warning("cartas indisponíveis para %s: %s", icao, descrever_falha(resposta))
            return
        atual = next((item.amdt for item in resposta.itens if item.tipo == tipo), None)
        if atual is None:
            logger.warning("carta tipo=%s não encontrada para %s ao checar edição", tipo, icao)
            return

        async with self._sessao_factory() as sessao:
            linha = (await sessao.execute(
                select(CartaAmdtVista).where(
                    CartaAmdtVista.icao == icao, CartaAmdtVista.tipo == tipo))
                    ).scalar_one_or_none()
            anterior = linha.amdt if linha is not None else None
            await sessao.merge(CartaAmdtVista(
                icao=icao, tipo=tipo, amdt=atual, atualizado_em=datetime.now(timezone.utc)))
            await sessao.commit()

        if anterior is not None and anterior != atual:
            logger.warning(
                "carta %s de %s mudou de edição (%s -> %s) — reconferir a classe de "
                "espaço aéreo gravada em app/core/espaco_aereo.py",
                tipo, icao, anterior, atual)

    async def classes_detectadas_por_icao(self, icaos: list[str]) -> dict[str, ClasseConhecida]:
        # Classes de espaço aéreo já detectadas automaticamente, só leitura.
        if not icaos:
            return {}
        async with self._sessao_factory() as sessao:
            linhas = (await sessao.execute(
                select(ClasseEspacoAereoDetectada)
                .where(ClasseEspacoAereoDetectada.icao.in_(icaos)))).scalars().all()
        return {linha.icao: _conhecida_de_linha(linha) for linha in linhas}

    async def textos_de_cartas(self) -> dict[str, tuple[str, str]]:
        # Texto já extraído de cada carta, por nome: `{nome: (amdt, texto)}`.
        async with self._sessao_factory() as sessao:
            linhas = (await sessao.execute(select(CartaTexto))).scalars().all()
        return {linha.nome: (linha.amdt, linha.texto) for linha in linhas}

    async def gravar_texto_de_carta(self, nome: str, amdt: str, texto: str) -> None:
        """Guarda o texto extraído de uma carta, sem brigar com quem gravar junto.

        `INSERT ... ON CONFLICT` no lugar de `merge()`: criar uma rota dispara a
        detecção da origem e do destino ao mesmo tempo, e as duas costumam cair
        na mesma Carta de Área. O `merge()` consulta e depois insere, então as
        duas viam "não existe" e as duas inseriam — a segunda estourava
        `UniqueViolationError: carta_texto_pkey` e a detecção daquele aeródromo
        falhava, caindo no fallback G (achado em 20/09/2026, num banco vazio,
        com SBBR e SBCF na mesma rota).
        """
        agora = datetime.now(timezone.utc)
        async with self._sessao_factory() as sessao:
            comando = insert(CartaTexto).values(
                nome=nome, amdt=amdt, texto=texto, atualizado_em=agora)
            await sessao.execute(comando.on_conflict_do_update(
                index_elements=["nome"],
                set_={"amdt": amdt, "texto": texto, "atualizado_em": agora}))
            await sessao.commit()

    async def gravar_classe_detectada(self, icao: str, conhecida: ClasseConhecida) -> None:
        async with self._sessao_factory() as sessao:
            await sessao.merge(ClasseEspacoAereoDetectada(
                icao=icao, classe=conhecida.classe.value, fonte_tipo=conhecida.fonte_tipo,
                fonte_amdt=conhecida.fonte_amdt, detectado_em=datetime.now(timezone.utc)))
            await sessao.commit()


def _conhecida_de_linha(linha: ClasseEspacoAereoDetectada) -> ClasseConhecida:
    return ClasseConhecida(
        classe=ClasseEspacoAereo(linha.classe), fonte_tipo=linha.fonte_tipo,
        fonte_amdt=linha.fonte_amdt, verificado_em=linha.detectado_em.date(), automatico=True)
