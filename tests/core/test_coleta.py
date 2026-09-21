from datetime import datetime, timezone

from app.core.coleta import (
    AlvoColeta, alvos_de_coleta, dias_para_recuperar, janela_de_coleta,
)


def _utc(**kwargs) -> datetime:
    base = {"year": 2026, "month": 9, "day": 6, "tzinfo": timezone.utc}
    return datetime(**{**base, **kwargs})


class TestJanelaDeColeta:
    def test_fecha_a_hora_corrente(self):
        janela = janela_de_coleta(_utc(hour=14, minute=37, second=52))
        assert janela.fim == _utc(hour=14, minute=0)
        assert janela.inicio == _utc(hour=13, minute=0)

    def test_virada_de_dia(self):
        janela = janela_de_coleta(_utc(hour=0, minute=5))
        assert janela.inicio == _utc(day=5, hour=23, minute=0)

    def test_janela_maior_por_parametro(self):
        janela = janela_de_coleta(_utc(hour=12), horas=3)
        assert janela.inicio == _utc(hour=9)


class TestAlvosDeColeta:
    def test_cada_rota_gera_origem_e_destino(self):
        alvos = alvos_de_coleta([(1, "SBSP", "SBRJ")])
        assert alvos == (AlvoColeta("SBSP", 1), AlvoColeta("SBRJ", 1))

    def test_nao_repete_o_mesmo_par_aerodromo_rota(self):
        alvos = alvos_de_coleta([(1, "SBSP", "SBSP")])
        assert alvos == (AlvoColeta("SBSP", 1),)

    def test_mesmo_icao_em_rotas_diferentes_gera_dois_alvos(self):
        # A observação é gravada por rota, então o par é que importa.
        alvos = alvos_de_coleta([(1, "SBSP", "SBRJ"), (2, "SBSP", "SBCF")])
        assert AlvoColeta("SBSP", 1) in alvos
        assert AlvoColeta("SBSP", 2) in alvos
        assert len(alvos) == 4

    def test_icao_vazio_e_descartado(self):
        assert alvos_de_coleta([(1, "SBSP", "")]) == (AlvoColeta("SBSP", 1),)

    def test_sem_rotas_nao_ha_alvos(self):
        assert alvos_de_coleta([]) == ()


class TestDiasParaRecuperar:
    AGORA = _utc(day=16, hour=13, minute=30)

    def test_sem_aerodromos_nao_ha_o_que_recuperar(self):
        assert dias_para_recuperar({}, self.AGORA, maximo=15) == 0

    def test_leitura_recente_nao_e_buraco(self):
        # A tarefa horária já cobre as últimas 2 horas.
        ultimas = {"SBSP": _utc(day=16, hour=11, minute=30)}
        assert dias_para_recuperar(ultimas, self.AGORA, maximo=15) == 0

    def test_buraco_conta_do_dia_da_ultima_leitura_ate_hoje(self):
        ultimas = {"SBSP": _utc(day=14, hour=23)}
        assert dias_para_recuperar(ultimas, self.AGORA, maximo=15) == 3

    def test_aerodromo_mais_atrasado_manda(self):
        ultimas = {"SBSP": _utc(day=16, hour=12), "SBGL": _utc(day=12, hour=8)}
        assert dias_para_recuperar(ultimas, self.AGORA, maximo=15) == 5

    def test_aerodromo_sem_leitura_pede_a_janela_inteira(self):
        ultimas = {"SBSP": _utc(day=16, hour=12), "SBKP": None}
        assert dias_para_recuperar(ultimas, self.AGORA, maximo=15) == 15

    def test_buraco_maior_que_a_retencao_e_limitado_ao_maximo(self):
        ultimas = {"SBSP": _utc(month=8, day=1, hour=0)}
        assert dias_para_recuperar(ultimas, self.AGORA, maximo=15) == 15
