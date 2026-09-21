from datetime import datetime, timezone

from app.core.observacoes import (
    MensagemIgnorada, ObservacaoDecidida, decidir_metar, decidir_observacoes,
    decidir_taf, ler_recebimento,
)

AGORA = datetime(2026, 9, 6, 14, 0, tzinfo=timezone.utc)

METAR_BOM = "METAR SBSP 061800Z 27015KT 9999 BKN020 25/18 Q1015="
METAR_RUIM = "METAR SBSP 061800Z 27015KT 3000 BKN008 25/18 Q1015="
TAF_SIMPLES = "TAF SBSP 061700Z 0618/0718 27010KT 9999 BKN020="
TAF_COM_BECMG = ("TAF SBSP 061700Z 0618/0718 27010KT 9999 BKN020 "
                 "BECMG 0620/0622 27015KT 3000 BKN008=")
TAF_COM_TEMPO = ("TAF SBSP 061700Z 0618/0718 27010KT 9999 BKN020 "
                 "TEMPO 0620/0623 3000 BKN008=")


class TestLerRecebimento:
    def test_formato_iso_com_z(self):
        lido = ler_recebimento("2026-09-06T13:00:00Z", AGORA)
        assert lido == datetime(2026, 9, 6, 13, 0, tzinfo=timezone.utc)

    def test_valor_invalido_cai_no_padrao(self):
        assert ler_recebimento("nao é data", AGORA) == AGORA

    def test_valor_ausente_cai_no_padrao(self):
        assert ler_recebimento(None, AGORA) == AGORA


class TestDecidirMetar:
    def test_metar_com_teto_e_visibilidade_folgados_e_vfr(self):
        decisao = decidir_metar(icao="SBSP", route_id=1,
                                bruto={"mens": METAR_BOM}, agora=AGORA)
        assert isinstance(decisao, ObservacaoDecidida)
        assert decisao.status_operacional == "VFR"
        assert decisao.teto_ft == 2000
        assert decisao.visibilidade_m == 10000

    def test_visibilidade_baixa_fica_abaixo_dos_minimos(self):
        decisao = decidir_metar(icao="SBSP", route_id=1,
                                bruto={"mens": METAR_RUIM}, agora=AGORA)
        assert decisao.status_operacional == "ABAIXO_MINIMOS_VFR"

    def test_recebimento_vem_do_envelope_quando_existe(self):
        decisao = decidir_metar(
            icao="SBSP", route_id=1,
            bruto={"mens": METAR_BOM, "recebimento": "2026-09-06T13:30:00Z"},
            agora=AGORA)
        assert decisao.recebimento.hour == 13

    def test_recebimento_cai_no_agora_quando_ausente(self):
        decisao = decidir_metar(icao="SBSP", route_id=1,
                                bruto={"mens": METAR_BOM}, agora=AGORA)
        assert decisao.recebimento == AGORA

    def test_mensagem_ausente_e_ignorada_com_motivo(self):
        decisao = decidir_metar(icao="SBSP", route_id=1, bruto={}, agora=AGORA)
        assert isinstance(decisao, MensagemIgnorada)
        assert "ausente" in decisao.motivo


class TestDecidirTaf:
    def test_taf_completo_vira_observacao(self):
        decisao = decidir_taf(
            icao="SBSP", route_id=1,
            bruto={"mens": TAF_SIMPLES, "recebimento": "2026-09-06T17:00:00Z"},
            agora=AGORA)
        assert isinstance(decisao, ObservacaoDecidida)
        assert decisao.tipo == "TAF"

    def test_sem_recebimento_e_ignorado(self):
        decisao = decidir_taf(icao="SBSP", route_id=1,
                              bruto={"mens": TAF_SIMPLES}, agora=AGORA)
        assert isinstance(decisao, MensagemIgnorada)

    def test_becmg_ainda_nao_iniciado_mantem_a_base(self):
        # Recebido às 19Z, o BECMG só começa às 20Z, então BASE ainda vale.
        decisao = decidir_taf(
            icao="SBSP", route_id=1,
            bruto={"mens": TAF_COM_BECMG, "recebimento": "2026-09-06T19:00:00Z"},
            agora=AGORA)
        assert decisao.status_operacional == "VFR"
        assert decisao.aviso_temporario is None

    def test_becmg_ja_iniciado_vira_a_previsao_operativa(self):
        # Recebido às 21Z, dentro da janela do BECMG, teto 800 ft já vale.
        decisao = decidir_taf(
            icao="SBSP", route_id=1,
            bruto={"mens": TAF_COM_BECMG, "recebimento": "2026-09-06T21:00:00Z"},
            agora=AGORA)
        assert decisao.status_operacional == "ABAIXO_MINIMOS_VFR"
        assert decisao.teto_ft == 800

    def test_tempo_ativo_vira_aviso_mas_nao_muda_o_status(self):
        decisao = decidir_taf(
            icao="SBSP", route_id=1,
            bruto={"mens": TAF_COM_TEMPO, "recebimento": "2026-09-06T21:00:00Z"},
            agora=AGORA)
        assert decisao.status_operacional == "VFR"  # BASE, não o TEMPO
        assert "TEMPO" in decisao.aviso_temporario

    def test_tempo_fora_da_janela_nao_gera_aviso(self):
        decisao = decidir_taf(
            icao="SBSP", route_id=1,
            bruto={"mens": TAF_COM_TEMPO, "recebimento": "2026-09-06T19:00:00Z"},
            agora=AGORA)
        assert decisao.aviso_temporario is None


class TestDecidirObservacoes:
    def test_separa_o_que_grava_do_que_ignora(self):
        resultado = decidir_observacoes(
            icao="SBSP", route_id=1,
            metares=[{"mens": METAR_BOM}, {}],
            tafs=[{"mens": TAF_SIMPLES, "recebimento": "2026-09-06T17:00:00Z"}],
            agora=AGORA)
        assert len(resultado.observacoes) == 2
        assert len(resultado.ignoradas) == 1
        assert not resultado.vazio

    def test_sem_mensagens_o_resultado_e_vazio(self):
        resultado = decidir_observacoes(icao="SBSP", route_id=1, metares=[],
                                        tafs=[], agora=AGORA)
        assert resultado.vazio
        assert resultado.ignoradas == ()

    def test_decisao_nao_depende_do_relogio(self):
        # Mesma entrada, mesma saída, é o que permite testar sem infraestrutura."""
        argumentos = dict(icao="SBSP", route_id=1, metares=[{"mens": METAR_BOM}],
                          tafs=[], agora=AGORA)
        assert decidir_observacoes(**argumentos) == decidir_observacoes(**argumentos)
