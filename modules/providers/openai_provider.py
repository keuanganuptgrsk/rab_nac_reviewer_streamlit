from __future__ import annotations

import time
from typing import Any

from .base import ReviewProvider
from .contracts import ProviderBatchResponse


class OpenAIProvider(ReviewProvider):
    provider_name = "OpenAI API"

    def _client(self):
        from openai import OpenAI

        return OpenAI(api_key=self.api_key, timeout=45.0, max_retries=0)

    def review_batch(self, records: list[dict[str, Any]]) -> tuple[ProviderBatchResponse, int]:
        client = self._client()
        started = time.perf_counter()

        def request():
            return client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": "Anda adalah classifier audit NAC yang ketat."},
                    {"role": "user", "content": self.prompt(records)},
                ],
                text_format=ProviderBatchResponse,
                store=False,
            )

        response = self.with_retry(request)
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("OpenAI tidak mengembalikan structured output yang dapat diparsing.")
        return ProviderBatchResponse.model_validate(parsed), int((time.perf_counter() - started) * 1000)

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._client().models.retrieve(self.model)
        except Exception as exc:
            return False, f"Koneksi OpenAI gagal: {str(exc)[:180]}"
        return True, f"Koneksi OpenAI aktif. Model: {self.model}."
