from __future__ import annotations

import json
import logging

FORMATO = "%(asctime)s %(levelname)s %(name)s %(message)s"

# Tudo o que um LogRecord já traz de nascença e o que sobrar veio do `extra`.
ATRIBUTOS_PADRAO = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message", "asctime"}


class FormatadorComExtras(logging.Formatter):
    # Formato de texto habitual, com os campos do `extra` anexados como JSON.
    def formatMessage(self, record: logging.LogRecord) -> str:
        texto = super().formatMessage(record)
        extras = {chave: valor for chave, valor in vars(record).items()
                  if chave not in ATRIBUTOS_PADRAO}
        if not extras:
            return texto
        return f"{texto} {json.dumps(extras, ensure_ascii=False, default=str)}"


def configurar_logging(nivel: int = logging.INFO) -> None:
    # Liga o formatador com extras no logger raiz.
    saida = logging.StreamHandler()
    saida.setFormatter(FormatadorComExtras(FORMATO))
    logging.basicConfig(level=nivel, handlers=[saida], force=True)
