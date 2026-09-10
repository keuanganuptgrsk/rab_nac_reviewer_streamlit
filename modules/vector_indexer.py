from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

import numpy as np
from rapidfuzz import fuzz, process


DEFAULT_MODEL = "LazarusNLP/all-indo-e5-small-v4"
LEGACY_DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MAX_SEMANTIC_CANDIDATES = 20
QUERY_BRIDGES = {
    "hidangan": "makanan makan minum konsumsi jamuan catering katering kudapan snack",
    "sajian": "makanan makan minum konsumsi jamuan catering katering kudapan snack",
    "makan minum": "makanan konsumsi jamuan catering katering snack",
    "running text": "publikasi iklan media banner spanduk brosur",
    "videotron": "publikasi iklan media banner spanduk",
    "alihdaya": "outsourcing management building satpam caraka office boy taman gedung",
    "alih daya": "outsourcing management building satpam caraka office boy taman gedung",
    "keamanan gedung": "management building satpam gedung",
}

_INDEX_CACHE: dict[str, dict[str, Any]] = {}
_MODEL_STATUS: dict[str, str] = {}


@lru_cache(maxsize=3)
def load_embedding_model(model_name: str = DEFAULT_MODEL):
    model_id = model_name or DEFAULT_MODEL
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_id)
        _MODEL_STATUS[model_id] = "loaded"
        return model
    except Exception as exc:
        _MODEL_STATUS[model_id] = f"error: {exc}"
        return None


def embed_texts(texts, model_name: str = DEFAULT_MODEL, *, kind: str = "passage"):
    model = load_embedding_model(model_name)
    if model is None:
        return None
    prepared = [_with_model_prefix(str(text or ""), model_name, kind) for text in texts]
    try:
        return model.encode(prepared, normalize_embeddings=True, show_progress_bar=False)
    except Exception as exc:
        _MODEL_STATUS[model_name or DEFAULT_MODEL] = f"error: {exc}"
        return None


def compute_cosine_similarity(query_embedding, matrix_embeddings):
    if query_embedding is None or matrix_embeddings is None or len(matrix_embeddings) == 0:
        return np.array([])
    query = np.asarray(query_embedding).reshape(1, -1)
    matrix = np.asarray(matrix_embeddings)
    qn = np.linalg.norm(query, axis=1, keepdims=True)
    mn = np.linalg.norm(matrix, axis=1, keepdims=True)
    return ((query / np.maximum(qn, 1e-9)) @ (matrix / np.maximum(mn, 1e-9)).T)[0]


def best_semantic_match(
    text: str,
    keyword_rows: list[dict[str, Any]],
    model_name: str = DEFAULT_MODEL,
    synonym_rows: list[dict[str, Any]] | None = None,
    feedback_rows: list[dict[str, Any]] | None = None,
    *,
    return_details: bool = False,
    max_candidates: int = MAX_SEMANTIC_CANDIDATES,
):
    if not keyword_rows:
        empty = (None, 0.0, _details("", "", "", model_name, "Tidak ada keyword aktif untuk semantic index."))
        return empty if return_details else empty[:2]

    model_id = model_name or DEFAULT_MODEL
    index = build_semantic_index(keyword_rows, synonym_rows or [], feedback_rows or [], model_id)
    candidates = index.get("candidates") or []
    embeddings = index.get("embeddings")
    if embeddings is None or len(candidates) == 0:
        reason = index.get("status") or "Semantic model belum tersedia; fallback lexical dipakai."
        empty = (None, 0.0, _details("", "", "", model_id, reason))
        return empty if return_details else empty[:2]

    query = embed_texts([text], model_id, kind="query")
    if query is None:
        reason = runtime_status(model_id).get("model_status") or "Query embedding gagal dibuat."
        empty = (None, 0.0, _details("", "", "", model_id, reason))
        return empty if return_details else empty[:2]

    selected_indices = _candidate_indices(text, candidates, max_candidates)
    subset_embeddings = np.asarray([embeddings[idx] for idx in selected_indices])
    sims = compute_cosine_similarity(query[0], subset_embeddings)
    if len(sims) == 0:
        empty = (None, 0.0, _details("", "", "", model_id, "Semantic index kosong."))
        return empty if return_details else empty[:2]

    max_similarity = float(np.max(sims))
    tied = [idx for idx, value in enumerate(sims) if max_similarity - float(value) <= 0.005]
    local_idx = max(
        tied,
        key=lambda idx: _lexical_support(text, candidates[selected_indices[idx]]),
    )
    candidate_idx = selected_indices[local_idx]
    candidate = candidates[candidate_idx]
    score = float(sims[local_idx] * 100)
    if score <= 0:
        empty = (None, 0.0, _details("", "", "", model_id, "Tidak ada kandidat semantic yang relevan."))
        return empty if return_details else empty[:2]
    details = _details(
        candidate.get("candidate_text", ""),
        candidate.get("candidate_source", ""),
        candidate.get("keyword_context", ""),
        model_id,
        f"Semantic similarity {score:.2f} terhadap konteks keyword '{candidate.get('keyword', '')}'.",
    )
    result = (candidate.get("row"), score, details)
    return result if return_details else result[:2]


def build_semantic_index(
    keyword_rows: list[dict[str, Any]],
    synonym_rows: list[dict[str, Any]] | None,
    feedback_rows: list[dict[str, Any]] | None,
    model_name: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    candidates = build_semantic_candidates(keyword_rows, synonym_rows or [], feedback_rows or [])
    signature = semantic_index_signature(candidates, model_name)
    cached = _INDEX_CACHE.get(signature)
    if cached:
        return cached

    texts = [candidate["keyword_context"] for candidate in candidates]
    embeddings = embed_texts(texts, model_name, kind="passage")
    if embeddings is None:
        return {
            "signature": signature,
            "candidates": candidates,
            "embeddings": None,
            "status": runtime_status(model_name).get("model_status") or "Semantic embedding gagal dibuat.",
        }

    if len(_INDEX_CACHE) >= 4:
        _INDEX_CACHE.clear()
    index = {
        "signature": signature,
        "candidates": candidates,
        "embeddings": np.asarray(embeddings),
        "status": "ready",
    }
    _INDEX_CACHE[signature] = index
    return index


def build_semantic_candidates(
    keyword_rows: list[dict[str, Any]],
    synonym_rows: list[dict[str, Any]] | None = None,
    feedback_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    synonyms_by_keyword: dict[int, list[str]] = {}
    for row in synonym_rows or []:
        keyword_id = _int_or_none(row.get("nac_keyword_id"))
        synonym = str(row.get("synonym") or "").strip()
        if keyword_id is not None and synonym:
            synonyms_by_keyword.setdefault(keyword_id, []).append(synonym)

    feedback_by_keyword: dict[str, list[str]] = {}
    for row in feedback_rows or []:
        if str(row.get("feedback_type") or "") != "Correct NAC":
            continue
        matched_keyword = str(row.get("matched_keyword") or "").strip().lower()
        sample = str(row.get("original_text") or "").strip()
        if matched_keyword and sample:
            feedback_by_keyword.setdefault(matched_keyword, []).append(sample)

    candidates = []
    for row in keyword_rows:
        keyword_id = _int_or_none(row.get("id"))
        keyword = str(row.get("keyword") or "").strip()
        synonyms = synonyms_by_keyword.get(keyword_id or -1, [])
        feedback_samples = feedback_by_keyword.get(keyword.lower(), [])[:4]
        context_parts = [
            keyword,
            row.get("category", ""),
            row.get("description", ""),
            row.get("notes", ""),
            row.get("transaction_type", ""),
            row.get("gl_account_description", ""),
            row.get("nac_group", ""),
            " ".join(synonyms),
            " ".join(feedback_samples),
        ]
        context = " | ".join(str(part).strip() for part in context_parts if str(part or "").strip())
        source_bits = []
        if synonyms:
            source_bits.append("synonyms")
        if row.get("transaction_type"):
            source_bits.append("transaction_type")
        if row.get("description") or row.get("notes"):
            source_bits.append("metadata")
        if feedback_samples:
            source_bits.append("feedback_correct_nac")
        candidates.append(
            {
                "row": row,
                "keyword_id": keyword_id,
                "keyword": keyword,
                "candidate_text": keyword,
                "candidate_source": ", ".join(source_bits) or "keyword",
                "keyword_context": context or keyword,
                "lexical_text": " ".join([keyword, " ".join(synonyms), str(row.get("transaction_type") or "")]).strip(),
            }
        )
    return candidates


def semantic_index_signature(candidates_or_keywords, model_name: str = DEFAULT_MODEL, synonym_rows=None, feedback_rows=None) -> str:
    if candidates_or_keywords and isinstance(candidates_or_keywords[0], dict) and "keyword_context" in candidates_or_keywords[0]:
        candidates = candidates_or_keywords
    else:
        candidates = build_semantic_candidates(candidates_or_keywords or [], synonym_rows or [], feedback_rows or [])
    payload = {
        "model": model_name or DEFAULT_MODEL,
        "candidates": [
            {
                "id": candidate.get("keyword_id"),
                "context": candidate.get("keyword_context", ""),
                "source": candidate.get("candidate_source", ""),
            }
            for candidate in candidates
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def clear_semantic_cache() -> None:
    _INDEX_CACHE.clear()
    load_embedding_model.cache_clear()
    _MODEL_STATUS.clear()


def runtime_status(model_name: str = DEFAULT_MODEL) -> dict[str, Any]:
    try:
        import sentence_transformers  # noqa: F401

        package_available = True
    except Exception:
        package_available = False
    model_id = model_name or DEFAULT_MODEL
    return {
        "package_available": package_available,
        "model": model_id,
        "model_status": _MODEL_STATUS.get(model_id, "not_loaded"),
        "cached_index_count": len(_INDEX_CACHE),
    }


def _lexical_support(text: str, candidate: dict[str, Any]) -> tuple[int, float]:
    query_tokens = set(str(text or "").lower().split())
    candidate_tokens = set(str(candidate.get("keyword_context") or "").lower().split())
    overlap = len(query_tokens & candidate_tokens)
    coverage = overlap / max(1, len(query_tokens))
    return overlap, coverage


def _candidate_indices(text: str, candidates: list[dict[str, Any]], limit: int) -> list[int]:
    limit = max(1, int(limit or MAX_SEMANTIC_CANDIDATES))
    if len(candidates) <= limit:
        return list(range(len(candidates)))
    choices = {idx: candidate.get("lexical_text") or candidate.get("keyword_context", "") for idx, candidate in enumerate(candidates)}
    matches = process.extract(_expanded_query(str(text or "")), choices, scorer=fuzz.token_set_ratio, limit=limit)
    indices = []
    for match in matches:
        key = match[2]
        if key not in indices:
            indices.append(key)
    return indices or list(range(min(limit, len(candidates))))


def _expanded_query(text: str) -> str:
    lowered = str(text or "").lower()
    additions = [value for key, value in QUERY_BRIDGES.items() if key in lowered]
    if not additions:
        return text
    return f"{text} {' '.join(additions)}"


def _with_model_prefix(text: str, model_name: str, kind: str) -> str:
    if "e5" not in str(model_name or "").lower():
        return text
    prefix = "query" if kind == "query" else "passage"
    return f"{prefix}: {text}"


def _details(candidate_text: str, source: str, context: str, model: str, reason: str) -> dict[str, str]:
    return {
        "semantic_candidate_text": candidate_text,
        "semantic_candidate_source": source,
        "semantic_context": context,
        "semantic_model": model or DEFAULT_MODEL,
        "semantic_reason": reason,
    }


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
