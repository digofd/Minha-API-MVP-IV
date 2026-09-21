import json
import logging

from app.logging_config import FormatadorComExtras


def _formatar(mensagem: str, extra: dict | None = None) -> str:
    registro = logging.getLogger("teste").makeRecord(
        "teste", logging.INFO, __file__, 1, mensagem, None, None, extra=extra)
    return FormatadorComExtras("%(levelname)s %(message)s").format(registro)


def test_extras_sao_anexados_como_json():
    linha = _formatar("coleta finalizada", {"alvos": 6, "icaos": ["SBSP", "SBGL"]})
    texto, _, anexo = linha.partition(" {")
    assert texto == "INFO coleta finalizada"
    assert json.loads("{" + anexo) == {"alvos": 6, "icaos": ["SBSP", "SBGL"]}


def test_sem_extras_a_linha_fica_intacta():
    assert _formatar("aplicação iniciada") == "INFO aplicação iniciada"


def test_valor_nao_serializavel_vira_texto():
    linha = _formatar("rota", {"objeto": object()})
    assert '"objeto": "<object object at' in linha
