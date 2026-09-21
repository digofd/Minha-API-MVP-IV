import pytest

from app.core.vfr_classifier import (
    ClasseEspacoAereo, StatusOperacional, TetoDesconhecido, TetoIlimitado, TetoMedido,
    classificar_condicao_vfr, teto_de_metar,
)

VFR = StatusOperacional.VFR
VFR_ESPECIAL = StatusOperacional.VFR_ESPECIAL
ABAIXO = StatusOperacional.ABAIXO_MINIMOS_VFR
INDETERMINADO = StatusOperacional.INDETERMINADO

# Mínimos da ICA 100-12, Art. 104, Tabela 1 (faixa de aeródromo)
CASOS = [
    # (descrição, visibilidade_m, teto, cavok, status esperado)
    ("CAVOK dispensa os demais critérios", None, TetoDesconhecido(), True, VFR),
    ("teto e visibilidade folgados", 10000, TetoMedido(2000), False, VFR),
    ("teto exatamente no mínimo da norma", 10000, TetoMedido(1000), False, VFR),
    ("visibilidade exatamente no mínimo", 5000, TetoMedido(2000), False, VFR),
    ("céu sem camada significativa", 6000, TetoIlimitado(), False, VFR),
    ("teto entre o antigo proxy e a norma", 10000, TetoMedido(1200), False, VFR),
    ("visibilidade um metro abaixo", 4999, TetoMedido(2000), False, ABAIXO),
    ("teto um pé abaixo do mínimo", 10000, TetoMedido(999), False, ABAIXO),
    ("VV baixa reprova pelo teto", 10000, TetoMedido(300), False, ABAIXO),
    ("sem visibilidade não dá para decidir", None, TetoMedido(2000), False, INDETERMINADO),
    ("teto desconhecido não dá para decidir", 9999, TetoDesconhecido(), False, INDETERMINADO),
]


@pytest.mark.parametrize("descricao,visibilidade_m,teto,cavok,esperado", CASOS)
def test_classificacao(descricao, visibilidade_m, teto, cavok, esperado):
    resultado = classificar_condicao_vfr(
        visibilidade_m=visibilidade_m, teto=teto, cavok=cavok)
    assert resultado.status is esperado, descricao


def test_motivo_diz_qual_criterio_reprovou():
    resultado = classificar_condicao_vfr(visibilidade_m=3000, teto=TetoMedido(2000))
    assert "visibilidade" in resultado.motivo
    assert "3000" in resultado.motivo


def test_base_legal_cita_a_classe_de_espaco_aereo():
    resultado = classificar_condicao_vfr(
        visibilidade_m=9999, teto=TetoMedido(2000),
        classe_espaco_aereo=ClasseEspacoAereo.C)
    assert "Classe C" in resultado.base_legal


class TestClasseB:
    # Classe B exige 8 km, não os 5 km das demais 
    def test_visibilidade_entre_5_e_8km_reprova_em_b(self):
        resultado = classificar_condicao_vfr(
            visibilidade_m=6000, teto=TetoMedido(2000),
            classe_espaco_aereo=ClasseEspacoAereo.B)
        assert resultado.status is ABAIXO

    def test_mesma_visibilidade_e_vfr_em_c(self):
        resultado = classificar_condicao_vfr(
            visibilidade_m=6000, teto=TetoMedido(2000),
            classe_espaco_aereo=ClasseEspacoAereo.C)
        assert resultado.status is VFR

    def test_8km_exato_e_vfr_em_b(self):
        resultado = classificar_condicao_vfr(
            visibilidade_m=8000, teto=TetoMedido(2000),
            classe_espaco_aereo=ClasseEspacoAereo.B)
        assert resultado.status is VFR


class TestClasseVerificada:
    # `classe_verificada` marca no texto quando a classe é o fallback G, não um dado conferido

    def test_default_nao_marca_a_classe_como_nao_verificada(self):
        resultado = classificar_condicao_vfr(visibilidade_m=9999, teto=TetoMedido(2000))
        assert "não verificada" not in resultado.base_legal

    def test_falso_acrescenta_o_aviso(self):
        resultado = classificar_condicao_vfr(
            visibilidade_m=9999, teto=TetoMedido(2000), classe_verificada=False)
        assert "não verificada" in resultado.base_legal

    def test_verdadeiro_explicito_nao_acrescenta_o_aviso(self):
        resultado = classificar_condicao_vfr(
            visibilidade_m=9999, teto=TetoMedido(2000),
            classe_espaco_aereo=ClasseEspacoAereo.D, classe_verificada=True)
        assert "não verificada" not in resultado.base_legal
        assert "Classe D" in resultado.base_legal


def test_regressao_argumentos_trocados_nao_compilam():
    with pytest.raises(TypeError):
        classificar_condicao_vfr(2000, TetoMedido(5000))  

    correto = classificar_condicao_vfr(visibilidade_m=2000, teto=TetoMedido(5000))
    assert correto.status is ABAIXO
    assert "visibilidade" in correto.motivo


class TestVfrEspecial:
    def test_visibilidade_intermediaria_diurno_e_ctr_confirmados(self):
        resultado = classificar_condicao_vfr(
            visibilidade_m=4000, teto=TetoMedido(2000),
            diurno=True, dentro_ctr_atz=True)
        assert resultado.status is VFR_ESPECIAL
        assert "Art. 134" in resultado.base_legal

    def test_visibilidade_no_minimo_especial_conta(self):
        resultado = classificar_condicao_vfr(
            visibilidade_m=3000, teto=TetoMedido(1000),
            diurno=True, dentro_ctr_atz=True)
        assert resultado.status is VFR_ESPECIAL

    def test_um_metro_abaixo_do_minimo_especial_nao_conta(self):
        resultado = classificar_condicao_vfr(
            visibilidade_m=2999, teto=TetoMedido(2000),
            diurno=True, dentro_ctr_atz=True)
        assert resultado.status is ABAIXO

    def test_sem_confirmar_diurno_cai_em_abaixo(self):
        resultado = classificar_condicao_vfr(
            visibilidade_m=4000, teto=TetoMedido(2000),
            diurno=False, dentro_ctr_atz=True)
        assert resultado.status is ABAIXO

    def test_sem_confirmar_ctr_cai_em_abaixo(self):
        resultado = classificar_condicao_vfr(
            visibilidade_m=4000, teto=TetoMedido(2000),
            diurno=True, dentro_ctr_atz=False)
        assert resultado.status is ABAIXO

    def test_dado_indisponivel_cai_em_abaixo(self):
       # `None` do AISWEB fora do ar, por exemplo, não é suposição de sucesso.
        resultado = classificar_condicao_vfr(
            visibilidade_m=4000, teto=TetoMedido(2000),
            diurno=None, dentro_ctr_atz=None)
        assert resultado.status is ABAIXO

    def test_teto_abaixo_do_minimo_reprova_mesmo_com_diurno_e_ctr(self):
        # O teto mínimo é o mesmo do VFR normal, reprova os dois.
        resultado = classificar_condicao_vfr(
            visibilidade_m=4000, teto=TetoMedido(999),
            diurno=True, dentro_ctr_atz=True)
        assert resultado.status is ABAIXO
        assert "teto" in resultado.motivo


class TestTetoDeMetar:
    # Tradução da saída dos parsers para o tipo de teto do domínio.

    def test_cavok_e_teto_ilimitado(self):
        assert teto_de_metar(teto_ft=99999, cavok=True, vv_presente=False) == TetoIlimitado()

    def test_sem_camada_bkn_ovc_e_teto_ilimitado(self):
        assert teto_de_metar(teto_ft=None, cavok=False, vv_presente=False) == TetoIlimitado()

    def test_camada_medida_vira_teto_medido(self):
        assert teto_de_metar(teto_ft=800, cavok=False, vv_presente=False) == TetoMedido(800)

    def test_visibilidade_vertical_vira_teto_medido(self):
        assert teto_de_metar(teto_ft=300, cavok=False, vv_presente=True) == TetoMedido(300)
