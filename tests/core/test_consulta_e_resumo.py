from datetime import datetime, timezone

import pytest

from app.core.consulta import (
    TAMANHO_MAXIMO, TAMANHO_PADRAO, montar_filtro, montar_ordenacao, montar_paginacao,
)
from app.core.resumo import LeituraObservacao, resumir


def _leitura(tipo="METAR", status="VFR", hora=12) -> LeituraObservacao:
    return LeituraObservacao(
        tipo=tipo, status_operacional=status,
        recebimento=datetime(2026, 9, 7, hora, tzinfo=timezone.utc))


class TestPaginacao:
    @pytest.mark.parametrize("pedido,esperado", [
        ((1, 20), (1, 20)),
        ((None, None), (1, TAMANHO_PADRAO)),
        ((-3, 5000), (1, TAMANHO_MAXIMO)),   # limites são fechados nos dois lados
        ((0, 0), (1, 1)),
    ])
    def test_normaliza_valores_fora_da_faixa(self, pedido, esperado):
        paginacao = montar_paginacao(*pedido)
        assert (paginacao.pagina, paginacao.tamanho) == esperado

    def test_offset_deriva_da_pagina(self):
        assert montar_paginacao(3, 20).offset == 40

    @pytest.mark.parametrize("total,paginas", [(0, 0), (1, 1), (20, 1), (21, 2), (40, 2)])
    def test_total_de_paginas_arredonda_para_cima(self, total, paginas):
        assert montar_paginacao(1, 20).total_de_paginas(total) == paginas


class TestOrdenacao:
    def test_padrao_e_mais_recente_primeiro(self):
        ordenacao = montar_ordenacao(None, None)
        assert ordenacao.campo == "criado_em"
        assert ordenacao.descendente is True

    def test_ordem_ascendente_explicita(self):
        assert montar_ordenacao("origem_icao", "asc").descendente is False

    def test_campo_desconhecido_e_recusado_com_o_valor_ofensor(self):
        # Aceitar qualquer string aqui seria injeção no ORDER BY.
        with pytest.raises(ValueError) as erro:
            montar_ordenacao("; DROP TABLE routes", "asc")
        assert "DROP TABLE" in str(erro.value)
        assert "criado_em" in str(erro.value)


class TestFiltro:
    def test_icao_e_normalizado_para_maiusculas(self):
        assert montar_filtro(None, " sbsp ").icao == "SBSP"

    def test_icao_vazio_significa_sem_filtro(self):
        assert montar_filtro(None, "   ").icao is None

    def test_ativa_falso_e_diferente_de_ausente(self):
        assert montar_filtro(False, None).ativa is False
        assert montar_filtro(None, None).ativa is None


class TestResumo:
    def test_sem_observacoes_o_resumo_e_zerado(self):
        resumo = resumir([])
        assert resumo.total == 0
        assert resumo.status_atual is None

    def test_conta_por_status_e_por_tipo(self):
        resumo = resumir([_leitura(), _leitura(status="ABAIXO_MINIMOS_VFR"),
                          _leitura(tipo="TAF")])
        assert resumo.total == 3
        assert resumo.por_status["VFR"] == 2
        assert resumo.total_metar == 2
        assert resumo.total_taf == 1

    def test_status_atual_vem_do_metar_mais_recente(self):
        resumo = resumir([_leitura(status="VFR", hora=10),
                          _leitura(status="ABAIXO_MINIMOS_VFR", hora=14)])
        assert resumo.status_atual == "ABAIXO_MINIMOS_VFR"

    def test_taf_nao_define_o_status_atual(self):
        # TAF é previsão e previsão não descreve a condição de agora.
        resumo = resumir([_leitura(status="VFR", hora=10),
                          _leitura(tipo="TAF", status="ABAIXO_MINIMOS_VFR", hora=23)])
        assert resumo.status_atual == "VFR"

    def test_status_nulo_conta_como_indeterminado(self):
        assert resumir([_leitura(status=None)]).por_status["INDETERMINADO"] == 1
