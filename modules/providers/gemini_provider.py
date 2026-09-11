from __future__ import annotations

import time
from typing import Any

from .base import ReviewProvider
from .contracts import ProviderBatchResponse


class GeminiProvider(ReviewProvider):
    provider_name = "Gemini Flash API"

    def _client(self):
        from google import genai

        return genai.Client(api_key=self.api_key)

    def review_batch(self, records: list[dict[str, Any]]) -> tuple[ProviderBatchResponse, int]:
        client = self._client()
        started = time.perf_counter()

        def request():
            return client.models.generate_content(
                model=self.model,
                contents=self.prompt(records),
                config={
                    "response_mime_type": "application/json",
                    "response_schema": ProviderBatchResponse,
                },
            )

        response = self.with_retry(request)
        parsed = getattr(response, "parsed", None)
        if parsed is None:
            parsed = ProviderBatchResponse.model_validate_json(response.text)
        return ProviderBatchResponse.model_validate(parsed), int((time.perf_counter() - started) * 1000)

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._client().models.get(model=self.model)
        except Exception as exc:
            return False, f"Koneksi Gemini gagal: {str(exc)[:180]}"
        return True, f"Koneksi Gemini aktif. Model: {self.model}."
