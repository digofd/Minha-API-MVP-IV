from datetime import date

from app.core.espaco_aereo import (
    CLASSES_CONHECIDAS, ClasseConhecida, classe_de, classe_em_carta, classe_verificada,
    nomes_alvo,
)
from app.core.vfr_classifier import ClasseEspacoAereo


class TestClasseDe:
    def test_icao_conhecido_devolve_a_classe_gravada(self):
        assert classe_de("SBSP") == ClasseEspacoAereo.D

    def test_e_insensivel_a_caixa_e_espaco(self):
        assert classe_de(" sbsp ") == ClasseEspacoAereo.D

    def test_icao_desconhecido_cai_no_fallback_g(self):
        assert classe_de("SBZZ") == ClasseEspacoAereo.G


class TestClasseVerificada:
    def test_icao_conhecido_e_verdadeiro(self):
        assert classe_verificada("SBSP") is True

    def test_icao_desconhecido_e_falso(self):
        assert classe_verificada("SBZZ") is False


def test_toda_entrada_conhecida_tem_fonte_citada():
    for icao, conhecida in CLASSES_CONHECIDAS.items():
        assert conhecida.fonte_tipo, icao
        assert conhecida.fonte_amdt, icao
        assert conhecida.verificado_em is not None, icao


class TestClasseComDetectadas:

    DETECTADA = {
        "SBFL": ClasseConhecida(ClasseEspacoAereo.C, "VAC", "2407A1",
                                date(2026, 9, 8), automatico=True),
    }

    def test_usa_a_detectada_quando_nao_ha_manual(self):
        assert classe_de("SBFL", self.DETECTADA) == ClasseEspacoAereo.C
        assert classe_verificada("SBFL", self.DETECTADA) is True

    def test_manual_vence_a_detectada_em_conflito(self):
        conflito = {"SBSP": ClasseConhecida(ClasseEspacoAereo.G, "VAC", "0000A0", date.today(),
                                             automatico=True)}
        assert classe_de("SBSP", conflito) == ClasseEspacoAereo.D  # a manual, não a detectada

    def test_sem_detectada_e_sem_manual_cai_no_fallback(self):
        assert classe_de("SBZZ", self.DETECTADA) == ClasseEspacoAereo.G
        assert classe_verificada("SBZZ", self.DETECTADA) is False


class TestNomesAlvo:
    def test_corta_o_nome_no_primeiro_hifen(self):
        # A carta traz 'GALEÃO'; o ROTAER traz 'Galeão - Antônio Carlos Jobim'.
        assert "GALEAO" in nomes_alvo("Galeão - Antônio Carlos Jobim", "Rio de Janeiro")

    def test_inclui_a_cidade(self):
        # Algumas CTR levam o nome da cidade, não o do aeródromo (SBFL).
        assert "FLORIANOPOLIS" in nomes_alvo("Hercílio Luz", "Florianópolis")

    def test_ignora_vazios(self):
        assert nomes_alvo(None, None) == frozenset()


class TestClasseEmCarta:

    LINHAS_GALEAO = ["TWR", "GALEÃO", "- 2000 ft", "CTR", "D GND ", "119.450 "]
    # ARC FLORIANÓPOLIS: a CTR de Navegantes (C) vem logo depois da de
    # Florianópolis (D), a âncora mais próxima do nome é que vale.
    LINHAS_FLORIPA = ["- 4500 ft", "FLORIANÓPOLIS", "128.950 129.450", "D GND", "APP",
                     "CTR", "- 1500 ft", "119.500 120.325", "C GND", "NAVEGANTES"]

    def test_le_a_classe_da_ctr_do_galeao(self):
        assert classe_em_carta(self.LINHAS_GALEAO,
                               frozenset({"GALEAO"})) == ClasseEspacoAereo.D

    def test_usa_a_ancora_mais_proxima_do_nome(self):
        assert classe_em_carta(self.LINHAS_FLORIPA,
                               frozenset({"FLORIANOPOLIS"})) == ClasseEspacoAereo.D

    def test_aceita_classe_e_limites_na_mesma_linha(self):
        # Algumas cartas escrevem 'C GND - FL 045' numa linha só (ARC Vitória).
        linhas = ["CTR", "VITÓRIA", "C GND - FL 045", "APP"]
        assert classe_em_carta(linhas, frozenset({"VITORIA"})) == ClasseEspacoAereo.C

    def test_nome_ausente_devolve_none(self):
        assert classe_em_carta(self.LINHAS_GALEAO, frozenset({"CONGONHAS"})) is None

    def test_sem_ctr_ou_atz_na_vizinhanca_nao_conta(self):
        """TMA e CTA aparecem na mesma tabela e não valem como classe de aeródromo."""
        linhas = ["TMA", "VITÓRIA", "C 4500 ft - FL 145", "APP"]
        assert classe_em_carta(linhas, frozenset({"VITORIA"})) is None

    def test_ancora_que_nao_comeca_no_solo_e_ignorada(self):
        """CTR/ATZ sempre começam em GND/SFC; 'D FL 115' é de CTA vizinha."""
        linhas = ["MACAÉ", "CTR", "D FL 115", "CURITIBA 2"]
        assert classe_em_carta(linhas, frozenset({"MACAE"})) is None

    def test_cartas_que_discordam_nao_promovem(self):
        linhas = ["ALDEIA 2", "CTR", "C GND", "x", "x", "x",
                  "ALDEIA 2", "CTR", "D GND"]
        assert classe_em_carta(linhas, frozenset({"ALDEIA 2"})) is None

    def test_sufixo_numerico_so_entra_se_o_exato_falhar(self):
        """'PORTO ALEGRE 1' casa quando 'PORTO ALEGRE' puro não existe na carta."""
        linhas = ["PORTO ALEGRE 1", "CTR", "C GND", "- 1500 ft"]
        assert classe_em_carta(linhas, frozenset({"PORTO ALEGRE"})) == ClasseEspacoAereo.C
