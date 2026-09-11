from __future__ import annotations

import logging
import os
import re


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            secret = os.environ.get(name)
            if secret:
                message = message.replace(secret, "[REDACTED]")
        message = re.sub(r"(?i)(api[_ -]?key\s*[=:]\s*)\S+", r"\1[REDACTED]", message)
        record.msg = message[:2000]
        record.args = ()
        return True


def configure_logging() -> None:
    root = logging.getLogger("rab_nac")
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.addFilter(SecretFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(os.environ.get("RAB_NAC_LOG_LEVEL", "INFO").upper())
