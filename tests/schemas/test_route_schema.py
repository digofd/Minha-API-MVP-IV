import pytest
from pydantic import ValidationError

from app.schemas.route import RouteCreate


def test_icao_e_normalizado_para_maiusculas():
    rota = RouteCreate(origem_icao="sbsp", destino_icao="SBGL")
    assert (rota.origem_icao, rota.destino_icao) == ("SBSP", "SBGL")


def test_origem_igual_ao_destino_e_recusada_com_o_valor_ofensor():
    with pytest.raises(ValidationError, match="SBSP"):
        RouteCreate(origem_icao="SBSP", destino_icao="SBSP")


def test_igualdade_e_checada_depois_de_normalizar():
    with pytest.raises(ValidationError, match="origem e destino iguais"):
        RouteCreate(origem_icao="sbsp", destino_icao="SBSP")
