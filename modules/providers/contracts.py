from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=200)
    ranked_candidate_ids: list[str] = Field(default_factory=list, max_length=5)
    selected_candidate_id: str | None = Field(default=None, max_length=100)
    ai_confidence: float = Field(ge=0, le=100)
    ambiguity: bool = False
    manual_review: bool = False
    evidence_terms: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(default="", max_length=400)

    @field_validator("ranked_candidate_ids")
    @classmethod
    def unique_ranked_ids(cls, value: list[str]) -> list[str]:
        result = []
        for item in value:
            clean = str(item).strip()
            if clean and clean not in result:
                result.append(clean)
        return result

    @field_validator("evidence_terms")
    @classmethod
    def clean_evidence(cls, value: list[str]) -> list[str]:
        return [str(item)[:80].strip() for item in value if str(item).strip()][:8]


class ProviderBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[ProviderDecision]


class ProviderAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    provider: str
    provider_model: str
    ranked_candidate_ids: list[str] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    ai_confidence: float = 0.0
    ambiguity: bool = False
    manual_review: bool = False
    evidence_terms: list[str] = Field(default_factory=list)
    reason: str = ""
    latency_ms: int = 0
    error: str = ""
    prompt_version: str = ""
    analysis_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    cache_hit: bool = False
    decision_source: str = "deterministic_fallback"

    def to_result_fields(self) -> dict[str, Any]:
        return {
            "engine": self.provider,
            "provider_model": self.provider_model,
            "prompt_version": self.prompt_version,
            "analysis_timestamp": self.analysis_timestamp,
            "ai_confidence": round(self.ai_confidence, 2),
            "ai_ranked_candidate_ids": ", ".join(self.ranked_candidate_ids),
            "ai_selected_candidate_id": self.selected_candidate_id or "",
            "ai_ambiguity": self.ambiguity,
            "ai_manual_review": self.manual_review,
            "ai_evidence_terms": ", ".join(self.evidence_terms),
            "ai_reason": self.reason,
            "provider_latency_ms": self.latency_ms,
            "provider_error": self.error,
            "provider_cache_hit": self.cache_hit,
            "decision_source": self.decision_source,
        }
