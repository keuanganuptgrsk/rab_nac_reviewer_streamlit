import re

from rapidfuzz import fuzz, process

from . import db
from .confidence_engine import calculate_confidence, confidence_label
from .suggestion_engine import generate_suggestion, recommended_action
from .text_normalizer import normalize_text
from .vector_indexer import best_semantic_match


def _bool(value):
    return str(value).lower() in ("1", "true", "yes", "ya", "on")


def _feedback_adjustment(text, keyword):
    rows = db.get_feedback()
    adj = 0
    text_l = (text or "").lower()
    for row in rows:
        sample = (row.get("original_text") or "").lower()
        if keyword and row.get("matched_keyword") == keyword:
            if row.get("feedback_type") == "Correct NAC":
                adj += 6
            elif row.get("feedback_type") == "Not NAC":
                adj -= 8
        elif sample and sample[:30] in text_l:
            if row.get("feedback_type") == "Confidence Too High":
                adj -= 5
            elif row.get("feedback_type") == "Confidence Too Low":
                adj += 5
    return max(-30, min(30, adj))


def _allowable_score(norm_text, allowable_rows):
    best = 0
    best_kw = ""
    for row in allowable_rows:
        kw = normalize_text(row.get("keyword", ""))
        score = 100 if kw and kw in norm_text else fuzz.token_set_ratio(kw, norm_text)
        if score < 88:
            score = 0
        if score > best:
            best, best_kw = score, row.get("keyword", "")
    return float(best), best_kw


def _exception(norm_text, keyword_id=None):
    for row in db.get_exceptions(True):
        pattern = normalize_text(row.get("pattern", ""))
        if pattern and pattern in norm_text:
            if row.get("nac_keyword_id") in (None, "", keyword_id) or not row.get("nac_keyword_id"):
                return row
    return None


def _suggest_synonym(original, norm_text, matched, best, settings):
    if not matched:
        return "", "", 0.0, ""
    if best["match_type"] in ("exact", "synonym"):
        return "", "", 0.0, ""
    signal = max(float(best.get("semantic", 0)), float(best.get("fuzzy", 0)))
    min_signal = min(float(settings.get("semantic_threshold", 60)), float(settings.get("fuzzy_threshold", 78)))
    if signal < min_signal:
        return "", "", 0.0, ""
    candidate = _candidate_phrase(original, norm_text, matched.get("keyword", ""))
    if not candidate or candidate.lower() == str(matched.get("keyword", "")).lower():
        return "", "", 0.0, ""
    reason = (
        f"Kandidat sinonim dari {best['match_type']} match. "
        "Reviewer harus validasi sebelum ditambahkan ke database."
    )
    return candidate, matched.get("keyword", ""), round(signal, 2), reason


def _candidate_phrase(original, norm_text, keyword):
    text = str(original or "").strip()
    parts = [p.strip(" -:;,.") for p in re.split(r"[|;\n\r]+", text) if p.strip(" -:;,.")]
    if parts:
        parts = sorted(parts, key=len)
        for part in parts:
            if 4 <= len(part) <= 90:
                return part
    words = norm_text.split()
    if 2 <= len(words) <= 10:
        return norm_text
    if len(words) > 10:
        return " ".join(words[:10])
    return str(keyword or "").strip()


def detect_item(item, settings=None):
    settings = settings or db.get_settings()
    original = item.get("original_text", "")
    norm = normalize_text(original, _bool(settings.get("enable_stemming", "false")))
    keywords = db.get_keywords(True)
    synonyms = db.get_synonyms(True)
    allowable = db.get_allowable(True)
    fuzzy_threshold = float(settings.get("fuzzy_threshold", 78))
    semantic_threshold = float(settings.get("semantic_threshold", 60))

    best = {"row": None, "match_type": "none", "exact_syn": 0, "fuzzy": 0, "semantic": 0}
    for row in keywords:
        kw_norm = normalize_text(row.get("keyword", ""))
        if kw_norm and kw_norm in norm:
            best = {"row": row, "match_type": "exact", "exact_syn": 100, "fuzzy": 100, "semantic": 0}
            break
    if not best["row"]:
        for row in synonyms:
            syn_norm = normalize_text(row.get("synonym", ""))
            if syn_norm and syn_norm in norm:
                best = {
                    "row": {"id": row.get("nac_keyword_id"), "keyword": row.get("parent_keyword"), "category": row.get("category"), "severity": row.get("severity", "medium")},
                    "match_type": "synonym",
                    "exact_syn": float(row.get("weight", 0.9)) * 100,
                    "fuzzy": 95,
                    "semantic": 0,
                }
                break
    if not best["row"] and keywords:
        choices = {r["keyword"]: r for r in keywords}
        match = process.extractOne(norm, list(choices), scorer=fuzz.partial_ratio)
        if match and match[1] >= fuzzy_threshold:
            best = {"row": choices[match[0]], "match_type": "fuzzy", "exact_syn": 0, "fuzzy": float(match[1]), "semantic": 0}
    if _bool(settings.get("enable_semantic", "true")):
        sem_row, sem_score = best_semantic_match(norm, keywords, settings.get("embedding_model"))
        if sem_row and sem_score >= semantic_threshold and sem_score > best.get("semantic", 0):
            if not best["row"] or sem_score > max(best["fuzzy"], best["exact_syn"]):
                best = {"row": sem_row, "match_type": "semantic", "exact_syn": 0, "fuzzy": best.get("fuzzy", 0), "semantic": sem_score}
            else:
                best["semantic"] = sem_score

    matched = best["row"] or {}
    allowable_score, allowable_kw = _allowable_score(norm, allowable)
    exc = _exception(norm, matched.get("id"))
    exception_penalty = 0
    exception_hit = False
    if exc:
        exception_hit = True
        action = exc.get("action")
        if action == "ignore":
            exception_penalty = 100
        elif action == "manual_review":
            exception_penalty = 10
        else:
            exception_penalty = float(exc.get("weight_adjustment") or 25)
    feedback_adj = _feedback_adjustment(norm, matched.get("keyword"))
    if item.get("source_quality") == "ocr":
        feedback_adj -= 8

    score = calculate_confidence(
        best["exact_syn"],
        best["fuzzy"],
        best["semantic"],
        matched.get("severity", "medium"),
        feedback_adj,
        allowable_score,
        exception_penalty,
        settings,
    )
    label = confidence_label(score)
    manual = score >= 45 or (score >= 35 and allowable_score >= 60) or (exception_hit and exc.get("action") == "manual_review")
    explanation = _explanation(best, matched, allowable_score, allowable_kw, exc, feedback_adj)
    suggestion = generate_suggestion(original, matched.get("keyword", ""), matched.get("category", ""), score, allowable_score, exception_hit)
    synonym_candidate, synonym_for, synonym_confidence, synonym_reason = _suggest_synonym(original, norm, matched, best, settings)
    return {
        "row_id": item.get("row_id"),
        "source_file": item.get("source_file"),
        "page_or_sheet": item.get("page_or_sheet"),
        "original_text": original,
        "normalized_text": norm,
        "item_description": item.get("item_description", original),
        "judul_rab": item.get("judul_rab", ""),
        "section": item.get("section", ""),
        "item_per_rab": item.get("item_per_rab", item.get("item_description", original)),
        "volume": item.get("volume", ""),
        "unit": item.get("unit", ""),
        "unit_price": item.get("unit_price", ""),
        "total_price": item.get("total_price", ""),
        "matched_keyword": matched.get("keyword", ""),
        "matched_category": matched.get("category", ""),
        "match_type": best["match_type"],
        "fuzzy_score": round(best["fuzzy"], 2),
        "semantic_score": round(best["semantic"], 2),
        "allowable_score": round(allowable_score, 2),
        "final_confidence": round(score, 2),
        "confidence_label": label,
        "explanation": explanation,
        "recommended_action": "Perlu Review Manual" if manual else recommended_action(score, allowable_score),
        "redaction_suggestion": suggestion,
        "suggested_synonym_candidate": synonym_candidate,
        "suggested_synonym_for_keyword": synonym_for,
        "synonym_suggestion_confidence": synonym_confidence,
        "synonym_suggestion_reason": synonym_reason,
        "user_feedback": "",
        "reviewer_notes": "",
    }


def detect_items(items, settings=None):
    settings = settings or db.get_settings()
    return [detect_item(item, settings) for item in items]


def _explanation(best, matched, allowable_score, allowable_kw, exc, feedback_adj):
    parts = []
    if matched:
        parts.append(f"Terindikasi melalui {best['match_type']} terhadap '{matched.get('keyword')}'.")
    else:
        parts.append("Tidak ada keyword NAC kuat yang cocok.")
    if allowable_score >= 60:
        parts.append(f"Ada sinyal allowable/teknis: '{allowable_kw}' ({allowable_score:.0f}).")
    if exc:
        parts.append(f"Exception cocok: {exc.get('pattern')} - {exc.get('reason')}.")
    if feedback_adj:
        parts.append(f"Penyesuaian feedback historis: {feedback_adj:+.0f}.")
    parts.append("Hasil adalah bantuan awal dan perlu validasi reviewer.")
    return " ".join(parts)
