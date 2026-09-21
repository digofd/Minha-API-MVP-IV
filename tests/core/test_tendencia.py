from datetime import date, datetime, timezone

import pytest

from app.core.observacoes import MensagemIgnorada
from app.core.tendencia import (
    Leitura, leitura_de_envelope, leituras_de_envelopes, resumir_dia, serie_diaria,
    teto_medido, tipo_da_mensagem, variacao_de,
)

AGORA = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)

# Mensagens reais do SBSP em 06/09/2026, colhidas da REDEMET.
METAR_VFR = "METAR SBSP 060000Z 09004KT 9999 BKN010 15/13 Q1018="
METAR_BAIXO = "METAR SBSP 060200Z 00000KT 4200 BR OVC005 15/14 Q1019="
SPECI_BAIXO = "SPECI SBSP 060230Z 00000KT 3000 BR OVC004 15/14 Q1019="
METAR_SEM_ORVALHO = "METAR SBSP 061000Z 16010KT 9000 BKN005 OVC007 10/// Q1025="


def _envelope(mensagem: str, recebimento: str) -> dict:
    return {"mens": mensagem, "recebimento": recebimento}


def _leitura(hora: int, *, teto=1000, vis=9999, temp=15, qnh=1018,
             status="VFR", tipo="METAR") -> Leitura:
    return Leitura(icao="SBSP", momento_utc=datetime(2026, 9, 6, hora, tzinfo=timezone.utc),
                   tipo=tipo, mensagem_bruta="x", teto_ft=teto, visibilidade_m=vis,
                   temperatura_c=temp, pressao_hpa=qnh, status_operacional=status,
                   base_legal="ICA 100-12")


class TestTipoDaMensagem:
    def test_reconhece_speci(self):
        assert tipo_da_mensagem(SPECI_BAIXO) == "SPECI"

    def test_o_resto_e_metar(self):
        assert tipo_da_mensagem(METAR_VFR) == "METAR"


class TestLeituraDeEnvelope:
    def test_interpreta_e_classifica(self):
        leitura = leitura_de_envelope(_envelope(METAR_VFR, "2026-09-06 00:01:00"),
                                      agora=AGORA)
        assert leitura.icao == "SBSP"
        assert leitura.teto_ft == 1000
        assert leitura.temperatura_c == 15
        assert leitura.pressao_hpa == 1018
        assert leitura.status_operacional == "VFR"

    def test_temperatura_sem_ponto_de_orvalho(self):
        leitura = leitura_de_envelope(_envelope(METAR_SEM_ORVALHO, "2026-09-06 10:01:00"),
                                      agora=AGORA)
        assert leitura.temperatura_c == 10

    def test_recebimento_sem_fuso_e_tratado_como_utc(self):
        leitura = leitura_de_envelope(_envelope(METAR_VFR, "2026-09-06 00:01:00"),
                                      agora=AGORA)
        assert leitura.momento_utc == datetime(2026, 9, 6, 0, 1, tzinfo=timezone.utc)

    def test_speci_vira_ponto_com_tipo_proprio(self):
        leitura = leitura_de_envelope(_envelope(SPECI_BAIXO, "2026-09-06 02:31:00"),
                                      agora=AGORA)
        assert leitura.tipo == "SPECI"
        assert leitura.status_operacional == "ABAIXO_MINIMOS_VFR"

    def test_mensagem_ausente_e_ignorada(self):
        assert isinstance(leitura_de_envelope({}, agora=AGORA), MensagemIgnorada)

    def test_mensagem_sem_icao_reconhecivel_e_ignorada(self):
        decisao = leitura_de_envelope(_envelope("LIXO", "2026-09-06 00:00:00"),
                                      agora=AGORA)
        assert isinstance(decisao, MensagemIgnorada)
        assert "ICAO" in decisao.motivo


class TestLeiturasDeEnvelopes:
    def test_separa_lidas_de_ignoradas_e_ordena_no_tempo(self):
        lidas, ignoradas = leituras_de_envelopes([
            _envelope(SPECI_BAIXO, "2026-09-06 02:31:00"),
            _envelope(METAR_VFR, "2026-09-06 00:01:00"),
            {},
        ], agora=AGORA)
        assert [l.tipo for l in lidas] == ["METAR", "SPECI"]
        assert len(ignoradas) == 1


class TestVariacao:
    @pytest.mark.parametrize("valores,esperado", [
        ([500, 1500], (500, 1500, 1000.0, 1000)),
        ([500, None, 1500], (500, 1500, 1000.0, 1000)),
        ([700], (700, 700, 700.0, 0)),
    ])
    def test_minimo_maximo_media_amplitude(self, valores, esperado):
        v = variacao_de(valores)
        assert (v.minimo, v.maximo, v.media, v.amplitude) == esperado

    def test_sem_valor_a_variacao_e_vazia(self):
        assert variacao_de([None, None]).vazia


class TestTetoMedido:

    def test_sentinela_de_cavok_vira_ausencia(self):
        assert teto_medido(99999) is None

    def test_teto_real_passa_intacto(self):
        assert teto_medido(800) == 800

    def test_ausencia_continua_ausencia(self):
        assert teto_medido(None) is None

    def test_dia_com_cavok_nao_distorce_a_amplitude(self):
        resumo = resumir_dia(date(2026, 9, 6), [
            _leitura(0, teto=99999), _leitura(6, teto=1200), _leitura(12, teto=700),
        ])
        assert resumo.teto.maximo == 1200
        assert resumo.teto.amplitude == 500

    def test_dia_inteiro_de_cavok_deixa_o_teto_vazio(self):
        resumo = resumir_dia(date(2026, 9, 6), [_leitura(0, teto=99999)])
        assert resumo.teto.vazia
        assert resumo.pior_teto_em is None


class TestResumirDia:
    def test_speci_conta_junto_com_metar(self):
        # SPECI é ponto extra e sem ele, o pior momento do dia sumiria.
        resumo = resumir_dia(date(2026, 9, 6), [
            _leitura(0, teto=1000, status="VFR"),
            _leitura(2, teto=400, status="ABAIXO_MINIMOS_VFR", tipo="SPECI"),
        ])
        assert resumo.leituras == 2
        assert resumo.metares == 1 and resumo.specis == 1
        assert resumo.teto.minimo == 400
        assert resumo.vfr == 1 and resumo.abaixo_minimos == 1

    def test_vfr_especial_conta_a_parte_de_vfr_e_de_abaixo(self):
        resumo = resumir_dia(date(2026, 9, 6), [
            _leitura(0, status="VFR"),
            _leitura(6, status="VFR_ESPECIAL"),
            _leitura(12, status="ABAIXO_MINIMOS_VFR"),
        ])
        assert resumo.vfr == 1
        assert resumo.vfr_especial == 1
        assert resumo.abaixo_minimos == 1

    def test_registra_quando_o_dia_apertou(self):
        resumo = resumir_dia(date(2026, 9, 6), [
            _leitura(0, teto=1000), _leitura(5, teto=300), _leitura(9, teto=800),
        ])
        assert resumo.pior_teto_em.hour == 5

    def test_dia_sem_leitura_fica_marcado_como_vazio(self):
        resumo = resumir_dia(date(2026, 9, 6), [])
        assert resumo.sem_dado
        assert resumo.teto.vazia


class TestSerieDiaria:
    def test_devolve_um_resumo_por_dia_do_periodo(self):
        serie = serie_diaria([_leitura(10)], ate=date(2026, 9, 6), dias=15)
        assert len(serie) == 15
        assert serie[-1].dia == date(2026, 9, 6)
        assert serie[0].dia == date(2026, 8, 23)

    def test_dia_sem_dado_entra_vazio_em_vez_de_sumir(self):
        serie = serie_diaria([_leitura(10)], ate=date(2026, 9, 6), dias=3)
        assert [d.sem_dado for d in serie] == [True, True, False]

    def test_agrupa_leituras_no_dia_certo(self):
        serie = serie_diaria([_leitura(0), _leitura(23)], ate=date(2026, 9, 6), dias=2)
        assert serie[-1].leituras == 2
