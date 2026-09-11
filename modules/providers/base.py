from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any, Callable

from .contracts import ProviderBatchResponse


PROMPT_VERSION = "nac-ranker-1.0"
SYSTEM_INSTRUCTION = """Anda membantu reviewer finance Indonesia merangking kandidat aturan NAC.
Pilih hanya candidate_id yang disediakan. Jangan membuat kandidat, prosentase, nilai koreksi, atau aturan baru.
Gunakan judul RAB, section/subjudul, dan item sebagai konteks. Item adalah bukti utama.
Jika bukti kurang, pilih null dan tandai manual_review. Kembalikan output sesuai schema saja."""


class ReviewProvider(ABC):
    provider_name = "AI"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    @abstractmethod
    def review_batch(self, records: list[dict[str, Any]]) -> tuple[ProviderBatchResponse, int]:
        raise NotImplementedError

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        raise NotImplementedError

    def prompt(self, records: list[dict[str, Any]]) -> str:
        payload = json.dumps({"rows": records}, ensure_ascii=False, separators=(",", ":"))
        return f"{SYSTEM_INSTRUCTION}\n\nData review:\n{payload}"

    def with_retry(self, operation: Callable[[], Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if not _retryable(exc) or attempt >= 2:
                    raise
                time.sleep(0.6 * (2**attempt))
        if last_error is not None:
            raise last_error
        raise RuntimeError("Provider operation failed without an exception.")


def _retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in {400, 401, 403}:
        return False
    if status == 429 or (isinstance(status, int) and status >= 500):
        return True
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    return "timeout" in name or "timeout" in text or "temporar" in text or "connection" in name
