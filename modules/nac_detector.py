from __future__ import annotations

import math
import re
from typing import Any

from rapidfuzz import fuzz, process

from . import db
from .confidence_engine import clamp_score, confidence_label
from .suggestion_engine import generate_suggestion, recommended_action
from .text_normalizer import normalize_text
from .vector_indexer import DEFAULT_MODEL, best_semantic_match


FIELD_WEIGHTS = {"item": 0.60, "section": 0.25, "title": 0.15}
FIELD_LABELS = {"item": "item", "section": "subjudul", "title": "judul"}
AMBIGUITY_MARGIN = 7.5
MATCH_PRIORITY = {"none": 0, "semantic": 1, "fuzzy": 2, "synonym": 3, "exact": 4}
SEVERITY_ADJUSTMENT = {"very_low": -4.0, "low": -1.0, "medium": 2.0, "high": 6.0, "very_high": 10.0}
TECHNICAL_ASSETS = {
    "pembangkit",
    "gardu",
    "transmisi",
    "distribusi",
    "jaringan",
    "ketenagalistrikan",
    "genset",
    "trafo",
}
TECHNICAL_ACTIVITIES = {"operasi", "pemeliharaan", "perbaikan", "instalasi", "pengujian", "commissioning"}


def _bool(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes", "ya", "on")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if value != value:
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _percentage_label(value: Any) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return ""
    if numeric.is_integer():
        return f"{int(numeric)}%"
    return f"{numeric:.2f}%"


def _contains_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    return re.search(rf"(?:^|\s){re.escape(phrase)}(?:$|\s)", text) is not None


def _candidate_key(row: dict[str, Any]) -> str:
    transaction = normalize_text(row.get("transaction_type", ""))
    if transaction:
        return f"transaction:{transaction}"
    keyword_id = row.get("id")
    if keyword_id not in (None, ""):
        return f"keyword:{keyword_id}"
    return f"keyword-text:{normalize_text(row.get('keyword', ''))}"


def _build_resources() -> dict[str, Any]:
    keywords = db.get_keywords(True)
    synonyms = db.get_synonyms(True)
    keyword_by_id = {int(row["id"]): row for row in keywords if row.get("id") not in (None, "")}
    phrase_entries: list[dict[str, Any]] = []
    for row in keywords:
        phrase = normalize_text(row.get("keyword", ""))
        if phrase:
            phrase_entries.append({"row": row, "phrase": phrase, "source": "keyword", "weight": 1.0})
    for synonym in synonyms:
        try:
            parent = keyword_by_id.get(int(synonym.get("nac_keyword_id")))
        except (TypeError, ValueError):
            parent = None
        phrase = normalize_text(synonym.get("synonym", ""))
        if parent and phrase:
            phrase_entries.append(
                {
                    "row": parent,
                    "phrase": phrase,
                    "source": "synonym",
                    "weight": _float_or_none(synonym.get("weight")) or 0.9,
                }
            )
    return {
        "keywords": keywords,
        "synonyms": synonyms,
        "allowable": db.get_allowable(True),
        "exceptions": db.get_exceptions(True),
        "feedback": db.get_feedback(),
        "phrase_entries": phrase_entries,
    }


def build_detection_resources() -> dict[str, Any]:
    """Public resource snapshot shared by deterministic and provider candidate passes."""
    return _build_resources()


def _exact_score(text: str, phrase: str, source: str, synonym_weight: float) -> float:
    text_tokens = max(1, len(text.split()))
    phrase_tokens = max(1, len(phrase.split()))
    coverage = min(1.0, phrase_tokens / text_tokens)
    if source == "keyword":
        return min(100.0, 88.0 + 12.0 * math.sqrt(coverage))
    score = min(98.0, max(72.0, synonym_weight * 100.0))
    if phrase_tokens == 1:
        score -= 7.0
    return min(98.0, score + 5.0 * coverage)


def _merge_signal(target: dict[str, dict[str, Any]], row: dict[str, Any], signal: dict[str, Any]) -> None:
    key = _candidate_key(row)
    current = target.get(key)
    if current is None:
        current = {
            "row": row,
            "score": 0.0,
            "match_type": "none",
            "matched_text": "",
            "exact_synonym_score": 0.0,
            "fuzzy_score": 0.0,
            "semantic_score": 0.0,
            "semantic_details": {},
        }
        target[key] = current

    current["exact_synonym_score"] = max(
        float(current.get("exact_synonym_score", 0)), float(signal.get("exact_synonym_score", 0))
    )
    current["fuzzy_score"] = max(float(current.get("fuzzy_score", 0)), float(signal.get("fuzzy_score", 0)))
    current["semantic_score"] = max(float(current.get("semantic_score", 0)), float(signal.get("semantic_score", 0)))
    previous_score = float(current.get("score", 0))
    new_score = float(signal.get("score", 0))
    same_score_better_type = (
        abs(new_score - previous_score) < 0.01
        and MATCH_PRIORITY.get(signal.get("match_type", "none"), 0)
        > MATCH_PRIORITY.get(current.get("match_type", "none"), 0)
    )
    new_priority = MATCH_PRIORITY.get(signal.get("match_type", "none"), 0)
    current_priority = MATCH_PRIORITY.get(current.get("match_type", "none"), 0)
    if new_priority > current_priority or (new_priority == current_priority and new_score > previous_score) or same_score_better_type:
        current.update(
            {
                "row": row,
                "match_type": signal.get("match_type", "none"),
                "matched_text": signal.get("matched_text", ""),
            }
        )
    current["score"] = max(previous_score, new_score)
    if signal.get("semantic_details"):
        current["semantic_details"] = signal["semantic_details"]


def _field_candidates(
    text: str,
    settings: dict[str, Any],
    resources: dict[str, Any],
) -> tuple[str, dict[str, dict[str, Any]]]:
    normalized = normalize_text(text, _bool(settings.get("enable_stemming", "false")))
    candidates: dict[str, dict[str, Any]] = {}
    if not normalized:
        return normalized, candidates

    phrase_entries = resources["phrase_entries"]
    for entry in phrase_entries:
        if _contains_phrase(normalized, entry["phrase"]):
            match_type = "exact" if entry["source"] == "keyword" else "synonym"
            score = _exact_score(normalized, entry["phrase"], entry["source"], entry["weight"])
            _merge_signal(
                candidates,
                entry["row"],
                {
                    "score": score,
                    "match_type": match_type,
                    "matched_text": entry["phrase"],
                    "exact_synonym_score": score,
                },
            )

    fuzzy_threshold = float(settings.get("fuzzy_threshold", 78))
    phrase_choices = [entry["phrase"] for entry in phrase_entries]
    if phrase_choices:
        fuzzy_matches = process.extract(
            normalized,
            phrase_choices,
            scorer=fuzz.token_set_ratio,
            limit=min(8, len(phrase_choices)),
            score_cutoff=fuzzy_threshold,
        )
        for _, score, index in fuzzy_matches:
            entry = phrase_entries[index]
            adjusted = float(score)
            if len(entry["phrase"].split()) == 1:
                adjusted -= 5.0
            if adjusted >= fuzzy_threshold:
                _merge_signal(
                    candidates,
                    entry["row"],
                    {
                        "score": adjusted,
                        "match_type": "fuzzy",
                        "matched_text": entry["phrase"],
                        "fuzzy_score": adjusted,
                    },
                )

    if _bool(settings.get("enable_semantic", "false")):
        semantic_threshold = float(settings.get("semantic_threshold", 70))
        semantic_row, semantic_score, details = best_semantic_match(
            normalized,
            resources["keywords"],
            settings.get("embedding_model"),
            resources["synonyms"],
            resources["feedback"],
            return_details=True,
        )
        if semantic_row and semantic_score >= semantic_threshold:
            details["semantic_reason"] = (
                f"{details.get('semantic_reason', '')} Skor melewati threshold {semantic_threshold:.0f}; "
                "sinyal semantic ikut dinilai pada field ini."
            ).strip()
            _merge_signal(
                candidates,
                semantic_row,
                {
                    "score": float(semantic_score),
                    "match_type": "semantic",
                    "matched_text": details.get("semantic_candidate_text", ""),
                    "semantic_score": float(semantic_score),
                    "semantic_details": details,
                },
            )

    return normalized, candidates


def _aggregate_candidates(field_candidates: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    for field, candidates in field_candidates.items():
        for key, signal in candidates.items():
            candidate = aggregated.setdefault(key, {"key": key, "row": signal["row"], "fields": {}})
            previous_scores = [value["score"] for value in candidate["fields"].values()]
            candidate["fields"][field] = signal
            if signal["score"] > max(previous_scores or [0]):
                candidate["row"] = signal["row"]

    for candidate in aggregated.values():
        fields = candidate["fields"]
        evidence_score = sum(FIELD_WEIGHTS[field] * float(signal["score"]) for field, signal in fields.items())
        support_weight = sum(FIELD_WEIGHTS[field] for field in fields)
        candidate["evidence_score"] = evidence_score
        candidate["context_consistency_score"] = min(100.0, support_weight * 100.0)
        candidate["consistency_bonus"] = _consistency_bonus(fields)
        candidate["corroboration_bonus"] = sum(
            FIELD_WEIGHTS[field] * 7.0
            for field, signal in fields.items()
            if float(signal.get("semantic_score", 0)) > 0
            and float(signal.get("exact_synonym_score", 0)) > 0
        )
        candidate["specificity_bonus"] = sum(
            FIELD_WEIGHTS[field]
            * 8.0
            * max(0, min(3, len(str(signal.get("matched_text") or "").split()) - 1))
            for field, signal in fields.items()
            if signal.get("match_type") in ("exact", "synonym")
        )
        candidate["item_supported"] = "item" in fields and float(fields["item"]["score"]) >= 45
        severity = str(candidate["row"].get("severity") or "medium").lower()
        candidate["severity_adjustment"] = SEVERITY_ADJUSTMENT.get(severity, 2.0)
        candidate["ranking_score"] = (
            evidence_score
            + candidate["consistency_bonus"]
            + candidate["corroboration_bonus"]
            + candidate["specificity_bonus"]
            + candidate["severity_adjustment"]
        )
    return sorted(aggregated.values(), key=lambda row: row["ranking_score"], reverse=True)


def _consistency_bonus(fields: dict[str, Any]) -> float:
    present = set(fields)
    if present == {"item", "section", "title"}:
        return 12.0
    if {"item", "section"}.issubset(present):
        return 8.0
    if {"item", "title"}.issubset(present):
        return 5.0
    if {"section", "title"}.issubset(present):
        return 3.0
    return 0.0


def _top_field_candidate(candidates: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return max(candidates.values(), key=lambda row: (float(row["score"]), MATCH_PRIORITY.get(row["match_type"], 0)))


def _conflict_penalty(selected: dict[str, Any], field_candidates: dict[str, dict[str, dict[str, Any]]]) -> float:
    penalty = 0.0
    for field, candidates in field_candidates.items():
        top = _top_field_candidate(candidates)
        if not top or _candidate_key(top["row"]) == selected["key"]:
            continue
        selected_signal = selected["fields"].get(field)
        if selected_signal is None or float(top["score"]) > float(selected_signal["score"]) + 5:
            penalty += FIELD_WEIGHTS[field] * 20.0
    return penalty


def _field_allowable(normalized: str, allowable_rows: list[dict[str, Any]]) -> tuple[float, str]:
    if not normalized:
        return 0.0, ""
    best_score = 0.0
    best_keyword = ""
    for row in allowable_rows:
        keyword = normalize_text(row.get("keyword", ""))
        if not keyword:
            continue
        score = 100.0 if _contains_phrase(normalized, keyword) else float(fuzz.token_set_ratio(keyword, normalized))
        if score < 86:
            score = 0.0
        if score > best_score:
            best_score = score
            best_keyword = _clean_text(row.get("keyword"))

    tokens = set(normalized.split())
    asset_hits = tokens & TECHNICAL_ASSETS
    activity_hits = tokens & TECHNICAL_ACTIVITIES
    technical_score = 0.0
    if asset_hits:
        technical_score = 66.0
    if asset_hits and activity_hits:
        technical_score = 82.0
    if technical_score > best_score:
        parts = sorted(activity_hits | asset_hits)
        return technical_score, f"konteks teknis: {', '.join(parts)}"
    return best_score, best_keyword


def _allowable_across_fields(
    normalized_fields: dict[str, str], allowable_rows: list[dict[str, Any]]
) -> tuple[float, str, str]:
    best = (0.0, "", "")
    field_multiplier = {"item": 1.0, "section": 0.8, "title": 0.6}
    for field, normalized in normalized_fields.items():
        score, keyword = _field_allowable(normalized, allowable_rows)
        adjusted = score * field_multiplier[field]
        if adjusted > best[0]:
            best = (adjusted, keyword, field)
    return best


def _exception_across_fields(
    normalized_fields: dict[str, str], keyword_id: Any, exception_rows: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, float, str]:
    field_multiplier = {"item": 1.0, "section": 0.8, "title": 0.6}
    best_row = None
    best_penalty = 0.0
    best_field = ""
    for field, normalized in normalized_fields.items():
        for row in exception_rows:
            pattern = normalize_text(row.get("pattern", ""))
            if not pattern or not _contains_phrase(normalized, pattern):
                continue
            exception_keyword_id = row.get("nac_keyword_id")
            linked_to_other_keyword = exception_keyword_id not in (None, "", keyword_id)
            action = row.get("action")
            if action == "ignore":
                penalty = 100.0
            elif action == "manual_review":
                penalty = 10.0
            else:
                penalty = _float_or_none(row.get("weight_adjustment")) or 25.0
            penalty *= field_multiplier[field]
            if linked_to_other_keyword:
                penalty *= 0.75
            if penalty > best_penalty:
                best_row, best_penalty, best_field = row, penalty, field
    return best_row, best_penalty, best_field


def _feedback_adjustment(text: str, keyword: str, feedback_rows: list[dict[str, Any]]) -> float:
    adjustment = 0.0
    text_lower = text.lower()
    for row in feedback_rows:
        sample = _clean_text(row.get("original_text")).lower()
        feedback_type = row.get("feedback_type")
        if keyword and row.get("matched_keyword") == keyword:
            if feedback_type == "Correct NAC":
                adjustment += 6
            elif feedback_type == "Not NAC":
                adjustment -= 8
        elif sample and sample[:30] in text_lower:
            if feedback_type == "Confidence Too High":
                adjustment -= 5
            elif feedback_type == "Confidence Too Low":
                adjustment += 5
    return max(-30.0, min(30.0, adjustment))


def _field_audit(candidates: dict[str, dict[str, Any]]) -> tuple[str, float]:
    top = _top_field_candidate(candidates)
    if not top:
        return "", 0.0
    return _clean_text(top["row"].get("keyword")), round(float(top["score"]), 2)


def _selected_semantic_details(selected: dict[str, Any] | None, settings: dict[str, Any]) -> dict[str, Any]:
    fallback = {
        "semantic_candidate_text": "",
        "semantic_candidate_source": "",
        "semantic_reason": "",
        "semantic_model": settings.get("embedding_model") or DEFAULT_MODEL,
    }
    if not selected:
        return fallback
    semantic_signals = [signal for signal in selected["fields"].values() if signal.get("semantic_details")]
    if not semantic_signals:
        return fallback
    strongest = max(semantic_signals, key=lambda signal: float(signal.get("semantic_score", 0)))
    details = dict(fallback)
    details.update(strongest.get("semantic_details") or {})
    return details


def _suggest_synonym(
    original: str,
    normalized: str,
    matched: dict[str, Any],
    selected_signal: dict[str, Any],
    settings: dict[str, Any],
) -> tuple[str, str, float, str]:
    if not matched or selected_signal.get("match_type") in ("exact", "synonym", "none"):
        return "", "", 0.0, ""
    signal = max(float(selected_signal.get("semantic_score", 0)), float(selected_signal.get("fuzzy_score", 0)))
    minimum = min(float(settings.get("semantic_threshold", 70)), float(settings.get("fuzzy_threshold", 78)))
    if signal < minimum:
        return "", "", 0.0, ""
    candidate = _candidate_phrase(original, normalized, matched.get("keyword", ""))
    if not candidate or candidate.lower() == _clean_text(matched.get("keyword")).lower():
        return "", "", 0.0, ""
    reason = (
        f"Kandidat sinonim berasal dari {selected_signal.get('match_type')} match pada item. "
        "Reviewer wajib memvalidasi sebelum menambahkannya ke database."
    )
    return candidate, matched.get("keyword", ""), round(signal, 2), reason


def _candidate_phrase(original: str, normalized: str, keyword: str) -> str:
    parts = [part.strip(" -:;,. ") for part in re.split(r"[|;\n\r]+", original) if part.strip(" -:;,. ")]
    if parts:
        for part in sorted(parts, key=len):
            if 4 <= len(part) <= 90:
                return part
    words = normalized.split()
    if 2 <= len(words) <= 10:
        return normalized
    if len(words) > 10:
        return " ".join(words[:10])
    return _clean_text(keyword)


def _decision_reason(
    selected: dict[str, Any] | None,
    alternative: dict[str, Any] | None,
    ambiguous: bool,
    conflict_penalty: float,
    percentage_status: str,
) -> str:
    if not selected:
        return "Tidak ada kandidat transaksi NAC yang melewati threshold lexical atau semantic."
    supported_fields = [FIELD_LABELS[field] for field in ("item", "section", "title") if field in selected["fields"]]
    reason = (
        f"Transaksi dipilih dari bukti {', '.join(supported_fields) or 'tanpa field kuat'} "
        f"dengan skor hierarkis {min(100.0, selected['ranking_score']):.2f} dan konsistensi konteks "
        f"{selected['context_consistency_score']:.0f}%."
    )
    if conflict_penalty:
        reason += f" Konflik antar-field memberi penalti {conflict_penalty:.2f}."
    if alternative:
        alternative_name = alternative["row"].get("transaction_type") or alternative["row"].get("keyword", "")
        reason += f" Kandidat kedua: {alternative_name} (skor {min(100.0, alternative['ranking_score']):.2f})."
    if ambiguous:
        reason += " Kandidat kuat memiliki aturan prosentase berbeda, sehingga keputusan angka ditahan untuk reviewer."
    elif percentage_status != "Diterapkan dari transaksi terpilih":
        reason += " Prosentase referensi belum diterapkan karena bukti utama pada item belum cukup kuat."
    return reason


def _explanation(
    selected: dict[str, Any] | None,
    allowable_score: float,
    allowable_keyword: str,
    allowable_field: str,
    exception: dict[str, Any] | None,
    exception_field: str,
    feedback_adjustment: float,
    semantic_details: dict[str, Any],
    percentage_status: str,
) -> str:
    parts: list[str] = []
    if selected:
        row = selected["row"]
        evidence = []
        for field in ("item", "section", "title"):
            signal = selected["fields"].get(field)
            if signal:
                evidence.append(f"{FIELD_LABELS[field]}={signal['match_type']} {signal['score']:.1f}")
        parts.append(f"Kandidat '{row.get('keyword')}' didukung oleh {', '.join(evidence)}.")
        if row.get("transaction_type"):
            parts.append(f"Type of Transaction: {row.get('transaction_type')}.")
        reference = _percentage_label(row.get("correction_percentage"))
        if reference:
            parts.append(f"Prosentase referensi transaksi: {reference}; status: {percentage_status}.")
        if semantic_details.get("semantic_candidate_text"):
            semantic_score = max(float(signal.get("semantic_score", 0)) for signal in selected["fields"].values())
            parts.append(
                f"Semantic cocok dengan '{semantic_details['semantic_candidate_text']}' ({semantic_score:.1f})."
            )
    else:
        parts.append("Tidak ada keyword NAC kuat yang cocok pada item, subjudul, maupun judul.")
    if allowable_score >= 40:
        parts.append(
            f"Sinyal allowable/teknis pada {FIELD_LABELS.get(allowable_field, allowable_field)}: "
            f"'{allowable_keyword}' ({allowable_score:.1f})."
        )
    if exception:
        parts.append(
            f"Exception cocok pada {FIELD_LABELS.get(exception_field, exception_field)}: "
            f"{exception.get('pattern')} - {exception.get('reason')}."
        )
    if feedback_adjustment:
        parts.append(f"Penyesuaian feedback historis: {feedback_adjustment:+.0f}.")
    parts.append("Confidence adalah keyakinan klasifikasi, bukan Prosentase NAC. Keputusan final tetap pada reviewer.")
    return " ".join(parts)


def detect_item(item: dict[str, Any], settings: dict[str, Any] | None = None, resources: dict[str, Any] | None = None):
    settings = settings or db.get_settings()
    resources = resources or _build_resources()
    original = _clean_text(item.get("original_text"))
    item_text = _clean_text(item.get("item_per_rab") or item.get("item_description") or original)
    section_text = _clean_text(item.get("section"))
    title_text = _clean_text(item.get("judul_rab"))
    field_texts = {"item": item_text, "section": section_text, "title": title_text}

    normalized_fields: dict[str, str] = {}
    field_candidates: dict[str, dict[str, dict[str, Any]]] = {}
    for field, text in field_texts.items():
        normalized, candidates = _field_candidates(text, settings, resources)
        normalized_fields[field] = normalized
        field_candidates[field] = candidates

    ranked = _aggregate_candidates(field_candidates)
    selected = ranked[0] if ranked else None
    alternative = ranked[1] if len(ranked) > 1 else None
    selected_row = selected["row"] if selected else {}
    selected_percentage = _float_or_none(selected_row.get("correction_percentage"))
    alternative_percentage = _float_or_none(alternative["row"].get("correction_percentage")) if alternative else None
    alternative_item_signal = alternative["fields"].get("item", {}) if alternative else {}
    alternative_phrase_tokens = len(str(alternative_item_signal.get("matched_text") or "").split())
    alternative_match_type = alternative_item_signal.get("match_type")
    alternative_is_specific = (
        (alternative_phrase_tokens >= 2 and alternative_match_type in ("exact", "synonym"))
        or alternative_match_type == "semantic"
        or (
            alternative_phrase_tokens >= 2
            and alternative_match_type == "fuzzy"
            and float(alternative_item_signal.get("score") or 0) >= 92
        )
    )
    alternative_is_strong = bool(
        alternative
        and alternative["ranking_score"] >= 45
        and alternative.get("item_supported")
        and alternative_is_specific
    )
    ambiguous = bool(
        selected
        and alternative_is_strong
        and abs(float(selected["ranking_score"]) - float(alternative["ranking_score"])) <= AMBIGUITY_MARGIN
        and selected_percentage is not None
        and alternative_percentage is not None
        and selected_percentage != alternative_percentage
    )

    conflict_penalty = _conflict_penalty(selected, field_candidates) if selected else 0.0
    allowable_score, allowable_keyword, allowable_field = _allowable_across_fields(
        normalized_fields, resources["allowable"]
    )
    exception, exception_penalty, exception_field = _exception_across_fields(
        normalized_fields, selected_row.get("id"), resources["exceptions"]
    )
    context_text = " | ".join(value for value in (title_text, section_text, item_text) if value)
    feedback_adjustment = _feedback_adjustment(
        context_text.lower(), _clean_text(selected_row.get("keyword")), resources["feedback"]
    )
    source_penalty = 8.0 if item.get("source_quality") == "ocr" else 0.0

    if selected:
        confidence = (
            float(selected["evidence_score"])
            + float(selected["consistency_bonus"])
            + float(selected["corroboration_bonus"])
            + float(selected["specificity_bonus"])
            + float(selected["severity_adjustment"])
            + feedback_adjustment
            - 0.20 * allowable_score
            - exception_penalty
            - conflict_penalty
            - source_penalty
        )
        if not selected["item_supported"]:
            confidence = min(confidence, 44.0)
        selected_types = {signal["match_type"] for signal in selected["fields"].values()}
        if selected_types == {"semantic"}:
            confidence = min(confidence, 64.0)
        confidence = clamp_score(confidence)
    else:
        confidence = 0.0

    if not selected:
        percentage_status = "Tidak teridentifikasi"
        applied_percentage = None
    elif ambiguous:
        percentage_status = "Perlu penentuan reviewer - Ambigu"
        applied_percentage = None
    elif selected_percentage is None:
        percentage_status = "Perlu penentuan reviewer - Aturan tidak tersedia"
        applied_percentage = None
    elif not selected["item_supported"] or confidence < 45:
        percentage_status = "Perlu penentuan reviewer - Confidence rendah"
        applied_percentage = None
    else:
        percentage_status = "Diterapkan dari transaksi terpilih"
        applied_percentage = selected_percentage

    percentage_display = _percentage_label(applied_percentage)
    if not percentage_display and selected:
        percentage_display = "Perlu penentuan reviewer"

    title_keyword, title_score = _field_audit(field_candidates["title"])
    section_keyword, section_score = _field_audit(field_candidates["section"])
    item_keyword, item_score = _field_audit(field_candidates["item"])
    semantic_details = _selected_semantic_details(selected, settings)
    selected_signal = (
        max(
            selected["fields"].items(),
            key=lambda pair: (
                FIELD_WEIGHTS[pair[0]] * float(pair[1]["score"]),
                MATCH_PRIORITY[pair[1]["match_type"]],
            ),
        )[1]
        if selected
        else {"match_type": "none", "score": 0.0, "fuzzy_score": 0.0, "semantic_score": 0.0}
    )
    match_type = selected_signal.get("match_type", "none")
    fuzzy_score = (
        max([float(signal.get("fuzzy_score", 0)) for signal in selected["fields"].values()] or [0])
        if selected
        else 0.0
    )
    semantic_score = (
        max([float(signal.get("semantic_score", 0)) for signal in selected["fields"].values()] or [0])
        if selected
        else 0.0
    )
    label = confidence_label(confidence)
    decision_reason = _decision_reason(selected, alternative, ambiguous, conflict_penalty, percentage_status)
    explanation = _explanation(
        selected,
        allowable_score,
        allowable_keyword,
        allowable_field,
        exception,
        exception_field,
        feedback_adjustment,
        semantic_details,
        percentage_status,
    )
    suggestion = generate_suggestion(
        item_text or original,
        selected_row.get("keyword", ""),
        selected_row.get("category", ""),
        confidence,
        allowable_score,
        exception is not None,
    )
    synonym_candidate, synonym_for, synonym_confidence, synonym_reason = _suggest_synonym(
        item_text,
        normalized_fields["item"],
        selected_row,
        selected_signal,
        settings,
    )
    manual = ambiguous or confidence >= 45 or bool(exception and exception.get("action") == "manual_review")
    if percentage_status.startswith("Perlu penentuan reviewer"):
        manual = True

    source_parts = [
        _clean_text(selected_row.get("source_reference")),
        f"slide {_clean_text(selected_row.get('source_slide'))}" if _clean_text(selected_row.get("source_slide")) else "",
    ]
    percentage_source = " | ".join(part for part in source_parts if part)
    alternative_transaction = ""
    if alternative:
        alternative_transaction = alternative["row"].get("transaction_type") or alternative["row"].get("keyword", "")

    return {
        "row_id": item.get("row_id"),
        "source_id": item.get("source_id") or item.get("row_id"),
        "source_file": item.get("source_file"),
        "page_or_sheet": item.get("page_or_sheet"),
        "source_location": item.get("source_location", ""),
        "source_row": item.get("source_row", ""),
        "source_coordinate": item.get("source_coordinate", ""),
        "item_no": item.get("item_no", item.get("row_id", "")),
        "display_sequence": item.get("display_sequence", ""),
        "original_text": original,
        "normalized_text": " | ".join(value for value in normalized_fields.values() if value),
        "item_description": item.get("item_description", item_text or original),
        "judul_rab": title_text,
        "section": section_text,
        "item_per_rab": item_text,
        "volume": item.get("volume", ""),
        "unit": item.get("unit", ""),
        "unit_price": item.get("unit_price", ""),
        "total_price": item.get("total_price", ""),
        "material_unit_price": item.get("material_unit_price", ""),
        "service_unit_price": item.get("service_unit_price", ""),
        "material_total": item.get("material_total", ""),
        "service_total": item.get("service_total", ""),
        "parser_strategy": item.get("parser_strategy", ""),
        "parser_confidence": item.get("parser_confidence", ""),
        "parser_warnings": item.get("parser_warnings", []),
        "provenance": item.get("provenance", {}),
        "raw_values": item.get("raw_values", {}),
        "matched_keyword_id": selected_row.get("id", ""),
        "matched_keyword": selected_row.get("keyword", ""),
        "matched_category": selected_row.get("category", ""),
        "nac_group": selected_row.get("nac_group", ""),
        "correction_percentage": applied_percentage if applied_percentage is not None else "",
        "correction_percentage_label": percentage_display,
        "reference_percentage": selected_percentage if selected_percentage is not None else "",
        "reference_percentage_label": _percentage_label(selected_percentage),
        "applied_nac_percentage": applied_percentage if applied_percentage is not None else "",
        "percentage_source": percentage_source,
        "percentage_status": percentage_status,
        "transaction_type": selected_row.get("transaction_type", ""),
        "selected_transaction_type": selected_row.get("transaction_type", ""),
        "gl_account": selected_row.get("gl_account", ""),
        "gl_account_description": selected_row.get("gl_account_description", ""),
        "source_reference": selected_row.get("source_reference", ""),
        "source_slide": selected_row.get("source_slide", ""),
        "alternative_transaction": alternative_transaction,
        "alternative_percentage": alternative_percentage if alternative_percentage is not None else "",
        "alternative_percentage_label": _percentage_label(alternative_percentage),
        "is_ambiguous": ambiguous,
        "match_type": match_type,
        "fuzzy_score": round(fuzzy_score, 2),
        "semantic_score": round(semantic_score, 2),
        "semantic_candidate_text": semantic_details.get("semantic_candidate_text", ""),
        "semantic_candidate_source": semantic_details.get("semantic_candidate_source", ""),
        "semantic_reason": semantic_details.get("semantic_reason", ""),
        "semantic_model": semantic_details.get("semantic_model", settings.get("embedding_model") or DEFAULT_MODEL),
        "title_match_keyword": title_keyword,
        "title_match_score": title_score,
        "section_match_keyword": section_keyword,
        "section_match_score": section_score,
        "item_match_keyword": item_keyword,
        "item_match_score": item_score,
        "context_consistency_score": round(float(selected["context_consistency_score"]), 2) if selected else 0.0,
        "context_conflict_penalty": round(conflict_penalty, 2),
        "allowable_score": round(allowable_score, 2),
        "allowable_keyword": allowable_keyword,
        "exception_pattern": exception.get("pattern", "") if exception else "",
        "final_confidence": round(confidence, 2),
        "confidence_label": label,
        "decision_reason": decision_reason,
        "explanation": explanation,
        "recommended_action": "Perlu Review Manual" if manual else recommended_action(confidence, allowable_score),
        "redaction_suggestion": suggestion,
        "suggested_synonym_candidate": synonym_candidate,
        "suggested_synonym_for_keyword": synonym_for,
        "synonym_suggestion_confidence": synonym_confidence,
        "synonym_suggestion_reason": synonym_reason,
        "user_feedback": "",
        "reviewer_notes": "",
        "engine": "Python Lokal",
        "provider_model": "deterministic-nac-engine",
        "prompt_version": "local-rules-1.0",
        "analysis_timestamp": "",
        "deterministic_confidence": round(confidence, 2),
        "ai_confidence": 0.0,
        "decision_source": "deterministic_local",
        "rule_pack_version": settings.get("keyword_pack_version", ""),
    }


def detect_items(items: list[dict[str, Any]], settings: dict[str, Any] | None = None):
    settings = settings or db.get_settings()
    resources = _build_resources()
    return [detect_item(item, settings, resources) for item in items]


def build_detection_resources() -> dict[str, Any]:
    return _build_resources()


def trusted_rule_candidates(
    item: dict[str, Any],
    settings: dict[str, Any] | None = None,
    resources: dict[str, Any] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return auditable rule candidates for provider ranking without exposing percentage in prompts."""
    settings = settings or db.get_settings()
    resources = resources or _build_resources()
    field_texts = {
        "item": _clean_text(item.get("item_per_rab") or item.get("item_description") or item.get("original_text")),
        "section": _clean_text(item.get("section")),
        "title": _clean_text(item.get("judul_rab")),
    }
    normalized_fields = {}
    field_candidates = {}
    for field, text in field_texts.items():
        normalized, candidates = _field_candidates(text, settings, resources)
        normalized_fields[field] = normalized
        field_candidates[field] = candidates
    ranked = _aggregate_candidates(field_candidates)
    allowable_score, _, _ = _allowable_across_fields(normalized_fields, resources["allowable"])
    source_penalty = 8.0 if item.get("source_quality") == "ocr" else 0.0
    context_text = " | ".join(value for value in field_texts.values() if value)
    output = []
    for candidate in ranked[:limit]:
        row = candidate["row"]
        exception, exception_penalty, _ = _exception_across_fields(
            normalized_fields, row.get("id"), resources["exceptions"]
        )
        feedback_adjustment = _feedback_adjustment(
            context_text.lower(), _clean_text(row.get("keyword")), resources["feedback"]
        )
        conflict_penalty = _conflict_penalty(candidate, field_candidates)
        confidence = (
            float(candidate["evidence_score"])
            + float(candidate["consistency_bonus"])
            + float(candidate["corroboration_bonus"])
            + float(candidate["specificity_bonus"])
            + float(candidate["severity_adjustment"])
            + feedback_adjustment
            - 0.20 * allowable_score
            - exception_penalty
            - conflict_penalty
            - source_penalty
        )
        if not candidate["item_supported"]:
            confidence = min(confidence, 44.0)
        confidence = clamp_score(confidence)
        evidence_terms = []
        for field, signal in candidate["fields"].items():
            evidence_terms.append(
                f"{FIELD_LABELS.get(field, field)}:{signal.get('matched_text') or row.get('keyword')}:{float(signal.get('score') or 0):.1f}"
            )
        output.append(
            {
                "candidate_id": str(row.get("id") or candidate["key"]),
                "keyword": row.get("keyword", ""),
                "category": row.get("category", ""),
                "transaction_type": row.get("transaction_type", ""),
                "deterministic_confidence": round(confidence, 2),
                "evidence_terms": evidence_terms,
                "guard_conflict": bool(allowable_score >= 60 or exception),
                "rule": dict(row),
            }
        )
    return output
