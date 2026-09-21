from datetime import datetime, timezone

import pytest

from app.parsers.metar_parser import metar_parser
from app.parsers.taf_parser import taf_parser

RECEBIMENTO = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)

METAR_SBSP = "METAR SBSP 070100Z 16013KT 9000 BKN007 OVC014 11/11 Q1025="
METAR_SBGL = "METAR SBGL 070100Z 30005KT 4000 -RA BR SCT009 BKN018 OVC035 17/15 Q1024="
TAF_SBGL = ("TAF SBGL 062027Z 0700/0806 24010KT 7000 BKN015 BKN030 "
            "TN16/0709Z TX19/0718Z=")
TAF_SBSP = "TAF SBSP 062015Z 0700/0712 15008KT 9999 OVC006 TX11/0700Z TN10/0708Z="


class TestMetarParser:
    def test_visibilidade_e_teto_da_camada_mais_baixa(self):
        dados = metar_parser.parse(METAR_SBSP)
        assert dados["visibilidade_m"] == 9000
        assert dados["teto_ft"] == 700  

    def test_ignora_camadas_scattered_no_teto(self):
        """SCT não forma teto; só BKN e OVC formam."""
        dados = metar_parser.parse(METAR_SBGL)
        assert dados["teto_ft"] == 1800 

    def test_vento_e_pressao(self):
        dados = metar_parser.parse(METAR_SBSP)
        assert dados["vento_direcao"] == "160"
        assert dados["vento_velocidade_kt"] == 13
        assert dados["pressao_hpa"] == 1025

    def test_cavok_marca_visibilidade_e_teto_ilimitados(self):
        dados = metar_parser.parse("METAR SBSP 070100Z 16013KT CAVOK 25/18 Q1015=")
        assert dados["cavok"] is True
        assert dados["visibilidade_m"] == 10000

    def test_parser_nao_devolve_horario_de_recebimento(self):
        # O recebimento vem do envelope da API, não do texto da mensagem.
        assert "recebimento" not in metar_parser.parse(METAR_SBSP)

    def test_mesma_entrada_mesma_saida(self):
        assert metar_parser.parse(METAR_SBSP) == metar_parser.parse(METAR_SBSP)


class TestTafParser:
    @pytest.mark.parametrize("mensagem,esperado", [
        (TAF_SBGL, 7000),   
        (TAF_SBSP, 10000),  
    ])
    def test_regressao_visibilidade_nao_vem_do_vento(self, mensagem, esperado):
        previsoes = taf_parser.parse(mensagem, RECEBIMENTO)["previsoes"]
        assert previsoes[0]["visibilidade_m"] == esperado

    def test_grupo_de_validade_nao_vira_visibilidade(self):
        previsoes = taf_parser.parse(TAF_SBGL, RECEBIMENTO)["previsoes"]
        assert previsoes[0]["visibilidade_m"] not in (700, 806)

    def test_teto_da_camada_mais_baixa(self):
        previsoes = taf_parser.parse(TAF_SBGL, RECEBIMENTO)["previsoes"]
        assert previsoes[0]["teto_ft"] == 1500  

    def test_validade_geral_e_convertida(self):
        dados = taf_parser.parse(TAF_SBGL, RECEBIMENTO)
        assert dados["validade_geral_inicio"] is not None
        assert dados["validade_geral_fim"] is not None

    def test_secoes_de_mudanca_viram_previsoes_separadas(self):
        mensagem = ("TAF SBSP 062015Z 0700/0712 15008KT 9999 SCT020 "
                    "BECMG 0703/0705 20010KT 5000 BKN008=")
        previsoes = taf_parser.parse(mensagem, RECEBIMENTO)["previsoes"]
        assert len(previsoes) >= 2
        assert previsoes[1]["tipo"] == "BECMG"
        assert previsoes[1]["visibilidade_m"] == 5000

    def test_recebimento_entra_por_parametro(self):
        outro = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
        assert (taf_parser.parse(TAF_SBGL, RECEBIMENTO)["validade_geral_inicio"]
                != taf_parser.parse(TAF_SBGL, outro)["validade_geral_inicio"])
