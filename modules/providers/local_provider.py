from __future__ import annotations

from typing import Any

from .base import ReviewProvider
from .contracts import ProviderBatchResponse, ProviderDecision


class LocalProvider(ReviewProvider):
    provider_name = "Python Lokal"

    def __init__(self):
        super().__init__(api_key="", model="deterministic-nac-engine")

    def review_batch(self, records: list[dict[str, Any]]) -> tuple[ProviderBatchResponse, int]:
        decisions = []
        for record in records:
            candidates = record.get("candidates", [])
            ranked = [str(candidate["candidate_id"]) for candidate in candidates]
            decisions.append(
                ProviderDecision(
                    source_id=record["source_id"],
                    ranked_candidate_ids=ranked,
                    selected_candidate_id=ranked[0] if ranked else None,
                    ai_confidence=0,
                    ambiguity=False,
                    manual_review=not bool(ranked),
                    evidence_terms=[],
                    reason="Hasil deterministic lokal; tidak ada data yang dikirim ke provider cloud.",
                )
            )
        return ProviderBatchResponse(decisions=decisions), 0

    def test_connection(self) -> tuple[bool, str]:
        return True, "Python Lokal siap dan tidak memerlukan credential."
