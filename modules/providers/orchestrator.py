from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable

from .base import PROMPT_VERSION, ReviewProvider
from .contracts import ProviderAudit, ProviderDecision
from .gemini_provider import GeminiProvider
from .local_provider import LocalProvider
from .openai_provider import OpenAIProvider


DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
CACHE_TTL_SECONDS = 24 * 60 * 60
CACHE_MAX_ENTRIES = 2048
MAX_BATCH_SIZE = 20
MAX_ROW_PAYLOAD_CHARS = 12000
_CACHE: OrderedDict[str, tuple[float, ProviderAudit]] = OrderedDict()


def provider_credentials(secrets: Any | None = None) -> dict[str, str]:
    def value(name: str) -> str:
        if secrets is not None:
            try:
                secret_value = secrets.get(name, "")
                if secret_value:
                    return str(secret_value)
            except Exception:
                pass
        return str(os.environ.get(name, ""))

    return {
        "openai_key": value("OPENAI_API_KEY"),
        "gemini_key": value("GEMINI_API_KEY") or value("GOOGLE_API_KEY"),
        "openai_model": value("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
        "gemini_model": value("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
    }


def provider_runtime_status(engine: str, secrets: Any | None = None) -> dict[str, Any]:
    credentials = provider_credentials(secrets)
    if engine == "Python Lokal":
        return {"available": True, "package": True, "credential": True, "model": "deterministic-nac-engine", "mode": "offline"}
    if engine == "OpenAI API":
        return {
            "available": _module_available("openai") and bool(credentials["openai_key"]),
            "package": _module_available("openai"),
            "credential": bool(credentials["openai_key"]),
            "model": credentials["openai_model"],
            "mode": "cloud",
        }
    return {
        "available": _module_available("google.genai") and bool(credentials["gemini_key"]),
        "package": _module_available("google.genai"),
        "credential": bool(credentials["gemini_key"]),
        "model": credentials["gemini_model"],
        "mode": "cloud",
    }


def make_provider(engine: str, secrets: Any | None = None) -> ReviewProvider:
    credentials = provider_credentials(secrets)
    if engine == "Python Lokal":
        return LocalProvider()
    if engine == "OpenAI API":
        if not credentials["openai_key"]:
            raise ValueError("OPENAI_API_KEY belum tersedia pada Streamlit secrets atau environment.")
        return OpenAIProvider(credentials["openai_key"], credentials["openai_model"])
    if engine == "Gemini Flash API":
        if not credentials["gemini_key"]:
            raise ValueError("GEMINI_API_KEY belum tersedia pada Streamlit secrets atau environment.")
        return GeminiProvider(credentials["gemini_key"], credentials["gemini_model"])
    raise ValueError(f"Engine review tidak dikenali: {engine}")


def review_with_provider(
    items: list[dict[str, Any]],
    deterministic_results: list[dict[str, Any]],
    candidate_sets: list[list[dict[str, Any]]],
    engine: str,
    rule_pack_version: str,
    secrets: Any | None = None,
    progress_callback: Callable[[int, int, int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if engine == "Python Lokal":
        return [_local_audit(result, rule_pack_version) for result in deterministic_results], {
            "called": 0,
            "cache_hits": 0,
            "failed": 0,
        }
    provider = make_provider(engine, secrets)
    records = [_provider_record(item, candidates) for item, candidates in zip(items, candidate_sets)]
    audits: dict[str, ProviderAudit] = {}
    misses: list[tuple[dict[str, Any], str]] = []
    cache_hits = 0
    for record in records:
        cache_key = _cache_key(record, provider.provider_name, provider.model, rule_pack_version)
        cached = _cache_get(cache_key)
        if cached:
            cached = cached.model_copy(update={"cache_hit": True})
            audits[record["source_id"]] = cached
            cache_hits += 1
        else:
            misses.append((record, cache_key))

    failed = 0
    called = 0
    for start in range(0, len(misses), MAX_BATCH_SIZE):
        batch_pairs = misses[start : start + MAX_BATCH_SIZE]
        batch = [record for record, _ in batch_pairs]
        called += len(batch)
        try:
            response, latency_ms = provider.review_batch(batch)
            decisions = {decision.source_id: decision for decision in response.decisions}
            for record, cache_key in batch_pairs:
                decision = decisions.get(record["source_id"])
                audit = _validated_audit(record, decision, provider, latency_ms)
                if audit.error:
                    failed += 1
                audits[record["source_id"]] = audit
                _cache_put(cache_key, audit)
        except Exception as exc:
            failed += len(batch)
            for record, _ in batch_pairs:
                audits[record["source_id"]] = ProviderAudit(
                    source_id=record["source_id"],
                    provider=provider.provider_name,
                    provider_model=provider.model,
                    error=_safe_error(exc, provider.api_key),
                    prompt_version=PROMPT_VERSION,
                    decision_source="deterministic_fallback",
                )
        if progress_callback:
            progress_callback(min(start + len(batch_pairs), len(misses)), len(misses), cache_hits, failed)

    merged = []
    for result, candidates in zip(deterministic_results, candidate_sets):
        source_id = str(result.get("source_id") or result.get("row_id") or "")
        audit = audits.get(source_id) or ProviderAudit(
            source_id=source_id,
            provider=provider.provider_name,
            provider_model=provider.model,
            error="Provider tidak mengembalikan keputusan untuk source_id ini.",
            prompt_version=PROMPT_VERSION,
        )
        merged.append(_apply_audit(result, candidates, audit, rule_pack_version))
    return merged, {"called": called, "cache_hits": cache_hits, "failed": failed}


def test_provider_connection(engine: str, secrets: Any | None = None) -> tuple[bool, str]:
    provider: ReviewProvider | None = None
    try:
        provider = make_provider(engine, secrets)
        return provider.test_connection()
    except Exception as exc:
        key = provider.api_key if provider is not None else ""
        return False, _safe_error(exc, key)


def clear_provider_cache() -> None:
    _CACHE.clear()


def _provider_record(item: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    source_id = str(item.get("source_id") or item.get("row_id") or "")
    record = {
        "source_id": source_id,
        "judul_rab": str(item.get("judul_rab") or "")[:1200],
        "section": str(item.get("section") or "")[:1200],
        "item": str(item.get("item_per_rab") or item.get("item_description") or item.get("original_text") or "")[:4000],
        "candidates": [
            {
                "candidate_id": str(candidate["candidate_id"]),
                "transaction": str(candidate.get("transaction_type") or candidate.get("keyword") or "")[:500],
                "category": str(candidate.get("category") or "")[:300],
                "keyword": str(candidate.get("keyword") or "")[:500],
                "deterministic_score": round(float(candidate.get("deterministic_confidence") or 0), 2),
                "evidence": [str(term)[:120] for term in candidate.get("evidence_terms", [])[:8]],
                "guard_conflict": bool(candidate.get("guard_conflict")),
            }
            for candidate in candidates[:5]
        ],
    }
    if len(json.dumps(record, ensure_ascii=False)) > MAX_ROW_PAYLOAD_CHARS:
        record["judul_rab"] = record["judul_rab"][:400]
        record["section"] = record["section"][:400]
        record["item"] = record["item"][:1800]
    return record


def _validated_audit(
    record: dict[str, Any],
    decision: ProviderDecision | None,
    provider: ReviewProvider,
    latency_ms: int,
) -> ProviderAudit:
    valid_ids = [candidate["candidate_id"] for candidate in record["candidates"]]
    if decision is None:
        return ProviderAudit(
            source_id=record["source_id"],
            provider=provider.provider_name,
            provider_model=provider.model,
            latency_ms=latency_ms,
            error="Structured output tidak memuat source_id yang diminta.",
            prompt_version=PROMPT_VERSION,
        )
    ranked = [candidate_id for candidate_id in decision.ranked_candidate_ids if candidate_id in valid_ids]
    if len(ranked) != len(decision.ranked_candidate_ids):
        return ProviderAudit(
            source_id=record["source_id"],
            provider=provider.provider_name,
            provider_model=provider.model,
            latency_ms=latency_ms,
            error="Provider mengembalikan ranked candidate_id di luar rule pack tepercaya.",
            prompt_version=PROMPT_VERSION,
        )
    selected = decision.selected_candidate_id
    if selected is not None and selected not in valid_ids:
        return ProviderAudit(
            source_id=record["source_id"],
            provider=provider.provider_name,
            provider_model=provider.model,
            latency_ms=latency_ms,
            error="Provider mengembalikan candidate_id di luar rule pack tepercaya.",
            prompt_version=PROMPT_VERSION,
        )
    return ProviderAudit(
        source_id=record["source_id"],
        provider=provider.provider_name,
        provider_model=provider.model,
        ranked_candidate_ids=ranked,
        selected_candidate_id=selected,
        ai_confidence=decision.ai_confidence,
        ambiguity=decision.ambiguity,
        manual_review=decision.manual_review,
        evidence_terms=decision.evidence_terms,
        reason=decision.reason,
        latency_ms=latency_ms,
        prompt_version=PROMPT_VERSION,
        decision_source="ai_ranked",
    )


def _apply_audit(
    result: dict[str, Any],
    candidates: list[dict[str, Any]],
    audit: ProviderAudit,
    rule_pack_version: str,
) -> dict[str, Any]:
    merged = dict(result)
    deterministic_confidence = float(result.get("final_confidence") or 0)
    merged["deterministic_confidence"] = round(deterministic_confidence, 2)
    merged["rule_pack_version"] = rule_pack_version
    merged.update(audit.to_result_fields())
    if audit.error or not audit.selected_candidate_id:
        merged["decision_source"] = "deterministic_fallback"
        return merged
    candidates_by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    selected = candidates_by_id.get(audit.selected_candidate_id)
    current_id = str(result.get("matched_keyword_id") or "")
    if audit.ambiguity or audit.manual_review:
        merged.update(
            {
                "correction_percentage": "",
                "applied_nac_percentage": "",
                "correction_percentage_label": "Perlu penentuan reviewer",
                "percentage_status": "Perlu penentuan reviewer - Provider menandai ambigu",
                "recommended_action": "Perlu Review Manual",
                "decision_source": "manual_review_ai_ambiguous",
            }
        )
        return merged
    if selected is None or audit.selected_candidate_id == current_id:
        merged["decision_source"] = "deterministic_confirmed_by_ai"
        return merged
    can_apply = (
        audit.ai_confidence >= 80
        and not audit.ambiguity
        and not audit.manual_review
        and deterministic_confidence < 75
        and not selected.get("guard_conflict")
    )
    if can_apply:
        rule = selected.get("rule", {})
        percentage = rule.get("correction_percentage")
        merged.update(
            {
                "matched_keyword_id": rule.get("id", ""),
                "matched_keyword": rule.get("keyword", ""),
                "matched_category": rule.get("category", ""),
                "nac_group": rule.get("nac_group", ""),
                "transaction_type": rule.get("transaction_type", ""),
                "selected_transaction_type": rule.get("transaction_type", ""),
                "reference_percentage": percentage if percentage is not None else "",
                "reference_percentage_label": _percentage_label(percentage),
                "correction_percentage": percentage if percentage is not None else "",
                "applied_nac_percentage": percentage if percentage is not None else "",
                "correction_percentage_label": _percentage_label(percentage) if percentage is not None else "Perlu penentuan reviewer",
                "percentage_status": "Diterapkan dari kandidat rule tepercaya yang dirangking AI",
                "percentage_source": " | ".join(
                    value for value in (str(rule.get("source_reference") or ""), str(rule.get("source_slide") or "")) if value
                ),
                "gl_account": rule.get("gl_account", ""),
                "gl_account_description": rule.get("gl_account_description", ""),
                "final_confidence": round(float(selected.get("deterministic_confidence") or 0), 2),
                "confidence_label": _confidence_label(float(selected.get("deterministic_confidence") or 0)),
                "decision_source": "ai_ranked_trusted_rule",
            }
        )
        return merged
    merged.update(
        {
            "correction_percentage": "",
            "applied_nac_percentage": "",
            "correction_percentage_label": "Perlu penentuan reviewer",
            "percentage_status": "Perlu penentuan reviewer - AI berbeda dengan deterministic",
            "recommended_action": "Perlu Review Manual",
            "decision_source": "manual_review_ai_disagreement",
        }
    )
    return merged


def _local_audit(result: dict[str, Any], rule_pack_version: str) -> dict[str, Any]:
    merged = dict(result)
    confidence = float(result.get("final_confidence") or 0)
    merged.update(
        {
            "engine": "Python Lokal",
            "provider_model": "deterministic-nac-engine",
            "prompt_version": "local-rules-1.0",
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_id": result.get("source_id") or result.get("row_id"),
            "deterministic_confidence": round(confidence, 2),
            "ai_confidence": 0.0,
            "decision_source": "deterministic_local",
            "rule_pack_version": rule_pack_version,
            "provider_error": "",
            "provider_cache_hit": False,
        }
    )
    return merged


def _cache_key(record: dict[str, Any], provider: str, model: str, rule_pack_version: str) -> str:
    payload = json.dumps(
        {
            "record": record,
            "provider": provider,
            "model": model,
            "prompt": PROMPT_VERSION,
            "rule_pack": rule_pack_version,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> ProviderAudit | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    created, audit = entry
    if time.time() - created > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    _CACHE.move_to_end(key)
    return audit


def _cache_put(key: str, audit: ProviderAudit) -> None:
    _CACHE[key] = (time.time(), audit.model_copy(update={"cache_hit": False}))
    _CACHE.move_to_end(key)
    while len(_CACHE) > CACHE_MAX_ENTRIES:
        _CACHE.popitem(last=False)


def _module_available(name: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _safe_error(exc: Exception, *additional_secrets: str) -> str:
    text = str(exc).replace("\n", " ").replace("\r", " ")
    secrets = [
        os.environ.get("OPENAI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GOOGLE_API_KEY", ""),
        *additional_secrets,
    ]
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text[:300]


def _percentage_label(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{int(number)}%" if number.is_integer() else f"{number:.2f}%"


def _confidence_label(score: float) -> str:
    if score >= 85:
        return "Sangat tinggi"
    if score >= 70:
        return "Tinggi"
    if score >= 45:
        return "Sedang"
    if score >= 20:
        return "Rendah"
    return "Sangat rendah"
