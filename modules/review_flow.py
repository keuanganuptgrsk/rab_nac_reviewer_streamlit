from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from . import db
from .excel_loader import (
    combine_selected_text_columns,
    detect_columns,
    load_excel_or_csv,
    load_rab_excel_items,
    normalize_dataframe,
)
from .adaptive_parser import parse_document, preview_dataframe
from .nac_detector import build_detection_resources, detect_item, detect_items, trusted_rule_candidates
from .ocr_engine import extract_text_from_image, extract_text_from_pdf_scan, ocr_runtime_status
from .pdf_loader import extract_text_from_pdf, ocr_text_document, parse_pdf_document
from .providers import provider_runtime_status, review_with_provider, test_provider_connection
from . import vector_indexer


BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_DIR = Path(os.environ.get("RAB_NAC_UPLOAD_DIR", BASE_DIR / "runtime" / "uploads"))
SUPPORTED_EXTENSIONS = [".xlsx", ".xls", ".csv", ".pdf", ".png", ".jpg", ".jpeg"]
MAX_UPLOAD_BYTES = int(os.environ.get("RAB_NAC_MAX_UPLOAD_MB", "100")) * 1024 * 1024
UPLOAD_TTL_SECONDS = 24 * 60 * 60
SEMANTIC_MODEL_OPTIONS = {
    "LazarusNLP/all-indo-e5-small-v4": "LazarusNLP/all-indo-e5-small-v4",
    "intfloat/multilingual-e5-small": "intfloat/multilingual-e5-small",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "firqaaa/indo-sentence-bert-base": "firqaaa/indo-sentence-bert-base",
    "BAAI/bge-m3 (lokal/server kuat)": "BAAI/bge-m3",
}

DISCLAIMER = (
    "Hasil deteksi adalah bantuan awal untuk review internal. Keputusan final tetap harus divalidasi oleh reviewer "
    "yang memahami PMK, kebijakan internal, dan konteks pekerjaan."
)


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "upload"))
    return cleaned.strip("._") or "upload"


def _context_value(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or fallback


def save_uploaded_file(
    uploaded_file: Any,
    upload_dir: Path | None = None,
    session_id: str | None = None,
) -> Path:
    upload_dir = upload_dir or UPLOAD_DIR
    cleanup_stale_uploads(upload_dir)
    session_dir = upload_dir / (safe_filename(session_id) if session_id else uuid.uuid4().hex)
    session_dir.mkdir(parents=True, exist_ok=True)
    name = safe_filename(getattr(uploaded_file, "name", "upload"))
    data = uploaded_file.getbuffer() if hasattr(uploaded_file, "getbuffer") else uploaded_file.read()
    raw = bytes(data)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Ukuran file melebihi batas {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Format file tidak didukung.")
    _validate_file_signature(raw, suffix)
    path = session_dir / name
    path.write_bytes(raw)
    return path


def save_database_upload(
    uploaded_file: Any,
    upload_dir: Path | None = None,
    session_id: str | None = None,
) -> Path:
    upload_dir = upload_dir or UPLOAD_DIR
    cleanup_stale_uploads(upload_dir)
    session_dir = upload_dir / (safe_filename(session_id) if session_id else uuid.uuid4().hex)
    session_dir.mkdir(parents=True, exist_ok=True)
    name = safe_filename(getattr(uploaded_file, "name", "restore.db"))
    if Path(name).suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise ValueError("Ekstensi backup SQLite tidak didukung.")
    data = uploaded_file.getbuffer() if hasattr(uploaded_file, "getbuffer") else uploaded_file.read()
    raw = bytes(data)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Ukuran backup melebihi batas {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not raw.startswith(b"SQLite format 3\x00"):
        raise ValueError("File restore bukan database SQLite yang valid.")
    path = session_dir / name
    path.write_bytes(raw)
    return path


def cleanup_stale_uploads(upload_dir: Path | None = None, ttl_seconds: int = UPLOAD_TTL_SECONDS) -> None:
    upload_dir = upload_dir or UPLOAD_DIR
    if not upload_dir.exists():
        return
    cutoff = time.time() - ttl_seconds
    for child in upload_dir.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child)
            elif child.is_file() and child.stat().st_mtime < cutoff:
                child.unlink()
        except OSError:
            continue


def _validate_file_signature(data: bytes, suffix: str) -> None:
    signatures = {
        ".xlsx": (b"PK\x03\x04",),
        ".xls": (b"\xd0\xcf\x11\xe0",),
        ".pdf": (b"%PDF",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
    }
    expected = signatures.get(suffix)
    if expected and not any(data.startswith(prefix) for prefix in expected):
        raise ValueError("Isi file tidak sesuai dengan ekstensi yang dipilih.")
    if suffix == ".csv" and b"\x00" in data[:8192]:
        raise ValueError("CSV mengandung data biner dan tidak dapat diproses.")


def load_uploaded_path(
    file_path: str | Path,
    manual_mappings: dict[str, dict[str, Any]] | None = None,
    confirm_low_confidence: bool = False,
) -> dict[str, Any]:
    path = Path(file_path)
    suffix = path.suffix.lower()
    empty_mapping = {"choices": [], "value": None}
    if suffix not in SUPPORTED_EXTENSIONS:
        return {
            "preview": pd.DataFrame(),
            "columns": [],
            "text_defaults": [],
            "detected": {},
            "mapping": {key: empty_mapping for key in ["volume", "unit", "unit_price", "total_price"]},
            "message": "Format file tidak didukung.",
            "state": {},
        }

    if suffix in [".xlsx", ".xls", ".csv"]:
        document = parse_document(path, manual_mappings)
        if confirm_low_confidence:
            document.review_blocked = False
        return _document_upload_payload(path, document)

    if suffix == ".pdf":
        document = parse_pdf_document(path, manual_mappings)
        settings = db.get_settings()
        if not document.items:
            ocr_text, ocr_note = extract_text_from_pdf_scan(path, settings.get("ocr_mode", "auto"))
            if ocr_text.strip():
                document = ocr_text_document(path, ocr_text, "OCR PDF")
                document.warnings.append(ocr_note)
            else:
                document.warnings.append(ocr_note)
        if confirm_low_confidence:
            document.review_blocked = False
        return _document_upload_payload(path, document)

    text, note = extract_text_from_image(path, db.get_settings().get("ocr_mode", "auto"))
    document = ocr_text_document(path, text, "Image OCR")
    document.warnings.append(note)
    if confirm_low_confidence:
        document.review_blocked = False
    return _document_upload_payload(path, document)


def _document_upload_payload(path: Path, document: Any) -> dict[str, Any]:
    preview = preview_dataframe(document).head(100)
    state = {
        "kind": "canonical",
        "path": str(path),
        "data": [item.to_dict() for item in document.items],
        "items": [item.to_dict() for item in document.items],
        "regions": [region.to_dict() for region in document.regions],
        "warnings": document.warnings,
        "review_blocked": document.review_blocked,
        "source_quality": document.source_quality,
        "parser_strategy": document.parser_strategy,
        "columns": list(preview.columns),
        "detected": {
            "description": "item_per_rab",
            "work_title": "judul_rab",
            "volume": "volume",
            "unit": "unit",
            "unit_price": "unit_price",
            "total_price": "total_price",
        },
    }
    labels = ", ".join(
        f"{region.diagnostic.region_id}: {region.diagnostic.confidence_label} {region.diagnostic.confidence:.1f}%"
        for region in document.regions
    ) or "tidak ada region"
    warnings = sum(len(region.diagnostic.warnings) for region in document.regions) + len(document.warnings)
    blocked = " Review diblokir sampai mapping dikonfirmasi." if document.review_blocked else ""
    extracted = " Berhasil ekstrak teks PDF digital." if document.source_quality == "digital_pdf" else ""
    return {
        "preview": preview,
        "columns": list(preview.columns),
        "text_defaults": ["item_per_rab"],
        "detected": state["detected"],
        "mapping": {},
        "message": (
            f"Parser adaptif menemukan {len(document.items)} item pada {len(document.regions)} region. "
            f"Confidence struktur: {labels}. Warning: {warnings}.{extracted}{blocked}"
        ),
        "state": state,
    }


def reload_with_manual_mapping(
    upload_state: dict[str, Any],
    manual_mappings: dict[str, dict[str, Any]],
    confirm_low_confidence: bool = False,
) -> dict[str, Any]:
    return load_uploaded_path(
        upload_state.get("path", ""),
        manual_mappings=manual_mappings,
        confirm_low_confidence=confirm_low_confidence,
    )


def build_items(
    upload_state: dict[str, Any],
    text_columns: list[str] | None,
    volume_col: str | None = None,
    unit_col: str | None = None,
    unit_price_col: str | None = None,
    total_price_col: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if not upload_state:
        return [], "Upload file dahulu."
    path = Path(upload_state.get("path", ""))
    if upload_state.get("kind") == "canonical":
        if upload_state.get("review_blocked"):
            return [], "Mapping ber-confidence rendah atau ambigu dan belum dikonfirmasi reviewer."
        items = [dict(item) for item in upload_state.get("items", upload_state.get("data", []))]
        return items, f"{len(items)} item kanonis siap direview."
    if upload_state.get("kind") == "table":
        frame = pd.DataFrame(upload_state["data"])
        combined = combine_selected_text_columns(frame, text_columns or [])
        detected = upload_state.get("detected", {})
        title_col = detected.get("work_title")
        item_col = detected.get("material_service_name") or detected.get("description")
        items = []
        for idx, text in combined.items():
            row = frame.loc[idx]
            title_text = _context_value(row.get("judul_rab"))
            if not title_text and title_col:
                title_text = _context_value(row.get(title_col))
            section_text = _context_value(row.get("section"))
            item_text = _context_value(row.get("item_per_rab"))
            if not item_text and item_col:
                item_text = _context_value(row.get(item_col))
            item_text = item_text or _context_value(text)
            original_text = _context_value(text) or " | ".join(
                part for part in (title_text, section_text, item_text) if part
            )
            items.append(
                {
                    "row_id": str(row.get("row_id", idx + 1)),
                    "source_file": path.name,
                    "page_or_sheet": row.get("sheet", upload_state.get("sheet", "")),
                    "original_text": original_text,
                    "item_description": item_text,
                    "judul_rab": title_text,
                    "item_per_rab": item_text,
                    "section": section_text,
                    "volume": row.get(volume_col, "") if volume_col else "",
                    "unit": row.get(unit_col, "") if unit_col else "",
                    "unit_price": row.get(unit_price_col, "") if unit_price_col else "",
                    "total_price": row.get(total_price_col, "") if total_price_col else "",
                    "source_quality": "table",
                }
            )
        return items, f"{len(items)} baris siap direview."

    items = []
    for i, chunk in enumerate(upload_state.get("data", []), start=1):
        text = chunk.get("text", "")
        for part_no, part in enumerate(chunk_text(text), start=1):
            items.append(
                {
                    "row_id": f"{i}.{part_no}",
                    "source_file": path.name,
                    "page_or_sheet": chunk.get("page_or_sheet", ""),
                    "original_text": part,
                    "item_description": part,
                    "item_per_rab": part,
                    "source_quality": upload_state.get("source_quality", "text"),
                }
            )
    return items, f"{len(items)} chunk teks siap direview."


def chunk_text(text: str, max_len: int = 900) -> list[str]:
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    chunks, current = [], ""
    for line in lines:
        if len(current) + len(line) > max_len and current:
            chunks.append(current)
            current = line
        else:
            current = f"{current} {line}".strip()
    if current:
        chunks.append(current)
    return chunks or ([text] if text else [])


def default_mapping(upload_state: dict[str, Any]) -> dict[str, Any]:
    if upload_state.get("kind") == "canonical":
        return {
            "text_columns": ["item_per_rab"],
            "volume_col": "volume",
            "unit_col": "unit",
            "unit_price_col": "unit_price",
            "total_price_col": "total_price",
        }
    detected = upload_state.get("detected", {})
    columns = upload_state.get("columns", [])
    text_columns = ["review_text"] if "review_text" in columns else [
        col for key, col in detected.items() if key in ("work_title", "description", "material_service_name", "notes")
    ]
    return {
        "text_columns": text_columns or columns[:1],
        "volume_col": detected.get("volume") or ("volume" if "volume" in columns else None),
        "unit_col": detected.get("unit") or ("unit" if "unit" in columns else None),
        "unit_price_col": detected.get("unit_price") or ("unit_price" if "unit_price" in columns else None),
        "total_price_col": detected.get("total_price") or ("total_price" if "total_price" in columns else None),
    }


def run_review(
    upload_state: dict[str, Any],
    text_columns: list[str] | None,
    volume_col: str | None,
    unit_col: str | None,
    unit_price_col: str | None,
    total_price_col: str | None,
    engine: str = "Python Lokal",
    secrets: Any | None = None,
    progress_callback: Any | None = None,
) -> tuple[list[dict[str, Any]], str]:
    items, msg = build_items(upload_state, text_columns, volume_col, unit_col, unit_price_col, total_price_col)
    if not items:
        return [], f"Review belum dapat dijalankan. {msg}"
    settings = db.get_settings()
    resources = build_detection_resources()
    results = [detect_item(item, settings, resources) for item in items]
    candidate_sets = [trusted_rule_candidates(item, settings, resources) for item in items]
    rule_pack_version = settings.get("keyword_pack_version", "")
    results, provider_stats = review_with_provider(
        items,
        results,
        candidate_sets,
        engine,
        rule_pack_version,
        secrets=secrets,
        progress_callback=progress_callback,
    )
    provider_note = ""
    if engine != "Python Lokal":
        provider_note = (
            f" Provider cloud memproses {provider_stats['called']} baris; "
            f"cache hit {provider_stats['cache_hits']}; gagal {provider_stats['failed']}."
        )
    return results, f"Review selesai dengan {engine}. {msg}{provider_note} {DISCLAIMER}"


def cloud_payload_preview(upload_state: dict[str, Any], limit: int = 50) -> pd.DataFrame:
    items, _ = build_items(upload_state, ["item_per_rab"], "volume", "unit", "unit_price", "total_price")
    if not items:
        return pd.DataFrame(columns=["Source ID", "Judul", "Section", "Item", "Kandidat Transaksi"])
    settings = db.get_settings()
    resources = build_detection_resources()
    rows = []
    for item in items[:limit]:
        candidates = trusted_rule_candidates(item, settings, resources)
        rows.append(
            {
                "Source ID": item.get("source_id") or item.get("row_id"),
                "Judul": item.get("judul_rab", ""),
                "Section": item.get("section", ""),
                "Item": item.get("item_per_rab") or item.get("item_description") or "",
                "Kandidat Transaksi": "; ".join(
                    f"{candidate['candidate_id']}:{candidate.get('transaction_type') or candidate.get('keyword')}"
                    for candidate in candidates
                ),
            }
        )
    return pd.DataFrame(rows)


def analyze_redaction(text: str, judul_rab: str = "", section: str = "") -> dict[str, Any] | None:
    text = str(text or "").strip()
    if not text:
        return None
    return detect_item(
        {
            "row_id": "redaksi",
            "source_file": "input_manual",
            "page_or_sheet": "Analisa Redaksi",
            "original_text": text,
            "item_description": text,
            "item_per_rab": text,
            "judul_rab": str(judul_rab or "").strip(),
            "section": str(section or "").strip(),
        },
        db.get_settings(),
    )


def review_summary_dataframe(results: list[dict[str, Any]] | None) -> pd.DataFrame:
    frame = pd.DataFrame(results or [])
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "Row",
                "Item per RAB",
                "Prosentase NAC",
                "Status Prosentase",
                "Confidence",
                "Confidence Level",
                "Type of Transaction",
                "Kategori",
                "Keyword",
                "Judul",
                "Bagian",
                "Konsistensi Konteks",
                "Match Item",
                "Skor Item",
                "Match Subjudul",
                "Skor Subjudul",
                "Match Judul",
                "Skor Judul",
                "Prosentase Referensi",
                "Alternatif Transaksi",
                "Alternatif Prosentase",
                "Tipe Deteksi",
                "Kandidat Semantic",
                "Alasan Semantic",
                "Alasan Keputusan",
                "Alasan Deteksi",
                "Sugesti Perubahan Redaksi",
                "File",
                "Sheet",
            ]
        )
    columns = [
        "source_id",
        "row_id",
        "source_coordinate",
        "item_per_rab",
        "unit",
        "volume",
        "unit_price",
        "total_price",
        "correction_percentage_label",
        "percentage_status",
        "final_confidence",
        "confidence_label",
        "selected_transaction_type",
        "matched_category",
        "matched_keyword",
        "judul_rab",
        "section",
        "context_consistency_score",
        "item_match_keyword",
        "item_match_score",
        "section_match_keyword",
        "section_match_score",
        "title_match_keyword",
        "title_match_score",
        "reference_percentage_label",
        "alternative_transaction",
        "alternative_percentage_label",
        "match_type",
        "semantic_candidate_text",
        "semantic_reason",
        "decision_reason",
        "explanation",
        "redaction_suggestion",
        "engine",
        "provider_model",
        "deterministic_confidence",
        "ai_confidence",
        "decision_source",
        "rule_pack_version",
        "parser_confidence",
        "source_file",
        "page_or_sheet",
    ]
    for col in columns:
        if col not in frame.columns:
            frame[col] = ""
    return frame[columns].rename(
        columns={
            "source_id": "Source ID",
            "row_id": "Row",
            "source_coordinate": "Source Row",
            "source_file": "File",
            "page_or_sheet": "Sheet",
            "judul_rab": "Judul",
            "section": "Bagian",
            "item_per_rab": "Item per RAB",
            "unit": "Satuan",
            "volume": "Volume",
            "unit_price": "Harga Satuan",
            "total_price": "Total",
            "matched_category": "Kategori",
            "matched_keyword": "Keyword",
            "correction_percentage_label": "Prosentase NAC",
            "reference_percentage_label": "Prosentase Referensi",
            "percentage_status": "Status Prosentase",
            "selected_transaction_type": "Type of Transaction",
            "context_consistency_score": "Konsistensi Konteks",
            "title_match_keyword": "Match Judul",
            "title_match_score": "Skor Judul",
            "section_match_keyword": "Match Subjudul",
            "section_match_score": "Skor Subjudul",
            "item_match_keyword": "Match Item",
            "item_match_score": "Skor Item",
            "alternative_transaction": "Alternatif Transaksi",
            "alternative_percentage_label": "Alternatif Prosentase",
            "match_type": "Tipe Deteksi",
            "semantic_candidate_text": "Kandidat Semantic",
            "semantic_reason": "Alasan Semantic",
            "final_confidence": "Confidence",
            "confidence_label": "Confidence Level",
            "explanation": "Alasan Deteksi",
            "decision_reason": "Alasan Keputusan",
            "redaction_suggestion": "Sugesti Perubahan Redaksi",
            "engine": "Engine",
            "provider_model": "Provider Model",
            "deterministic_confidence": "Deterministic Confidence",
            "ai_confidence": "AI Confidence",
            "decision_source": "Sumber Keputusan",
            "rule_pack_version": "Rule Pack",
            "parser_confidence": "Parser Confidence",
        }
    )


def all_materials_dataframe(results: list[dict[str, Any]] | None) -> pd.DataFrame:
    frame = pd.DataFrame(results or [])
    columns = [
        "source_id", "row_id", "source_coordinate", "item_per_rab", "unit", "volume", "unit_price", "total_price",
        "correction_percentage_label", "percentage_status", "final_confidence",
        "confidence_label", "selected_transaction_type", "matched_category", "judul_rab", "section",
        "context_consistency_score", "item_match_keyword", "item_match_score", "section_match_keyword",
        "section_match_score", "title_match_keyword", "title_match_score", "reference_percentage_label",
        "alternative_transaction", "alternative_percentage_label", "match_type", "semantic_candidate_text",
        "semantic_reason", "decision_reason", "engine", "provider_model", "deterministic_confidence",
        "ai_confidence", "decision_source", "rule_pack_version", "parser_confidence",
    ]
    labels = {
        "source_id": "Source ID",
        "row_id": "Row",
        "source_coordinate": "Source Row",
        "judul_rab": "Judul RAB",
        "section": "Subjudul / Section",
        "item_per_rab": "Item RAB",
        "unit": "Satuan",
        "volume": "Volume",
        "unit_price": "Harga Satuan",
        "total_price": "Total",
        "matched_category": "Kategori NAC",
        "correction_percentage_label": "Prosentase NAC",
        "reference_percentage_label": "Prosentase Referensi",
        "percentage_status": "Status Prosentase",
        "selected_transaction_type": "Type of Transaction",
        "context_consistency_score": "Konsistensi Konteks",
        "title_match_keyword": "Match Judul",
        "title_match_score": "Skor Judul",
        "section_match_keyword": "Match Subjudul",
        "section_match_score": "Skor Subjudul",
        "item_match_keyword": "Match Item",
        "item_match_score": "Skor Item",
        "alternative_transaction": "Alternatif Transaksi",
        "alternative_percentage_label": "Alternatif Prosentase",
        "match_type": "Tipe Deteksi",
        "semantic_candidate_text": "Kandidat Semantic",
        "semantic_reason": "Alasan Semantic",
        "final_confidence": "Confidence %",
        "confidence_label": "Confidence Level",
        "decision_reason": "Alasan Keputusan",
        "engine": "Engine",
        "provider_model": "Provider Model",
        "deterministic_confidence": "Deterministic Confidence",
        "ai_confidence": "AI Confidence",
        "decision_source": "Sumber Keputusan",
        "rule_pack_version": "Rule Pack",
        "parser_confidence": "Parser Confidence",
    }
    if frame.empty:
        return pd.DataFrame(columns=list(labels.values()))
    for col in columns:
        if col not in frame.columns:
            frame[col] = ""
    frame = frame[columns].copy()
    frame["matched_category"] = frame["matched_category"].replace("", "-").fillna("-")
    frame["item_per_rab"] = frame["item_per_rab"].replace("", "-").fillna("-")
    frame["final_confidence"] = pd.to_numeric(frame["final_confidence"], errors="coerce").fillna(0).round(2)
    frame["_row_sort"] = pd.to_numeric(frame["row_id"], errors="coerce")
    frame = frame.sort_values("_row_sort", na_position="last").drop(columns=["_row_sort"])
    return frame.rename(columns=labels)


def filtered_results(
    results: list[dict[str, Any]] | None,
    levels: list[str] | None = None,
    category: str = "Semua",
    manual_only: bool = False,
    query: str = "",
) -> pd.DataFrame:
    frame = pd.DataFrame(results or [])
    if frame.empty:
        return frame
    if levels:
        frame = frame[frame["confidence_label"].isin(levels)]
    if category and category != "Semua":
        frame = frame[frame["matched_category"].fillna("-") == category]
    if manual_only and "recommended_action" in frame:
        frame = frame[frame["recommended_action"].astype(str).str.contains("Review Manual", case=False, na=False)]
    query_l = str(query or "").strip().lower()
    if query_l:
        search_columns = ["item_per_rab", "original_text", "matched_keyword", "matched_category", "transaction_type"]
        for col in search_columns:
            if col not in frame.columns:
                frame[col] = ""
        haystack = frame[search_columns].fillna("").astype(str).agg(" ".join, axis=1)
        frame = frame[haystack.str.lower().str.contains(re.escape(query_l), na=False)]
    return frame


def summary_metrics(results: list[dict[str, Any]] | None) -> dict[str, Any]:
    frame = pd.DataFrame(results or [])
    if frame.empty:
        return {"total": 0, "potential": 0, "high": 0, "top_confidence": 0.0, "manual": 0}
    confidence = pd.to_numeric(frame.get("final_confidence"), errors="coerce").fillna(0)
    potential = frame["confidence_label"].isin(["Sedang", "Tinggi", "Sangat tinggi"]).sum()
    high = frame["confidence_label"].isin(["Tinggi", "Sangat tinggi"]).sum()
    manual = frame.get("recommended_action", pd.Series(dtype=str)).astype(str).str.contains("Review Manual", case=False, na=False).sum()
    return {
        "total": int(len(frame)),
        "potential": int(potential),
        "high": int(high),
        "top_confidence": float(confidence.max() if not confidence.empty else 0),
        "manual": int(manual),
    }


def settings_for_mode(review_mode: str, semantic_mode: str, ocr_mode: str) -> dict[str, str]:
    sensitivity = {
        "Ketat": {"fuzzy_threshold": "86", "semantic_threshold": "78"},
        "Seimbang": {"fuzzy_threshold": "78", "semantic_threshold": "70"},
        "Lebih sensitif": {"fuzzy_threshold": "68", "semantic_threshold": "62"},
    }.get(review_mode, {"fuzzy_threshold": "78", "semantic_threshold": "70"})
    return {
        "enable_semantic": "true" if semantic_mode == "Aktif" else "false",
        "enable_stemming": "false",
        "fuzzy_threshold": sensitivity["fuzzy_threshold"],
        "semantic_threshold": sensitivity["semantic_threshold"],
        "ocr_mode": ocr_mode,
        "semantic_user_configured": "true",
    }


def save_simple_settings(review_mode: str, semantic_mode: str, ocr_mode: str, embedding_model: str | None = None) -> str:
    values = settings_for_mode(review_mode, semantic_mode, ocr_mode)
    if embedding_model:
        values["embedding_model"] = embedding_model
        values["semantic_model_user_configured"] = "true"
    for key, value in values.items():
        db.save_setting(key, value)
    return f"Settings tersimpan: mode review {review_mode}, semantic {semantic_mode}, OCR {ocr_mode}."


def semantic_package_available() -> bool:
    return bool(vector_indexer.runtime_status().get("package_available"))


def ocr_runtime_overview() -> dict[str, Any]:
    return ocr_runtime_status()


def semantic_runtime_overview(model_name: str | None = None) -> dict[str, Any]:
    settings = db.get_settings()
    model_id = model_name or settings.get("embedding_model") or vector_indexer.DEFAULT_MODEL
    status = vector_indexer.runtime_status(model_id)
    keywords = db.get_keywords(True)
    synonyms = db.get_synonyms(True)
    feedback_rows = [row for row in db.get_feedback() if row.get("feedback_type") == "Correct NAC"]
    candidates = vector_indexer.build_semantic_candidates(keywords, synonyms, feedback_rows)
    status.update(
        {
            "active_keyword_count": len(keywords),
            "active_synonym_count": len(synonyms),
            "positive_feedback_count": len(feedback_rows),
            "candidate_count": len(candidates),
            "signature": vector_indexer.semantic_index_signature(candidates, model_id)[:12],
        }
    )
    return status


def clear_semantic_cache() -> None:
    vector_indexer.clear_semantic_cache()


def row_choices(results: list[dict[str, Any]] | None, only_with_synonym: bool = False) -> list[str]:
    frame = pd.DataFrame(results or [])
    if frame.empty:
        return []
    if only_with_synonym:
        frame = frame[frame.get("suggested_synonym_candidate", "").astype(str).str.strip() != ""]
    return [
        f"{row.get('source_id') or row.get('row_id')} | {str(row.get('item_per_rab') or row.get('original_text') or '')[:80]}"
        for _, row in frame.iterrows()
    ]
