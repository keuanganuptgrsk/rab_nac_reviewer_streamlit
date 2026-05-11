from __future__ import annotations

import os
import re
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
from .nac_detector import detect_item, detect_items
from .ocr_engine import extract_text_from_image, extract_text_from_pdf_scan
from .pdf_loader import extract_text_from_pdf


BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_DIR = Path(os.environ.get("RAB_NAC_UPLOAD_DIR", BASE_DIR / "runtime" / "uploads"))
SUPPORTED_EXTENSIONS = [".xlsx", ".xls", ".csv", ".pdf", ".png", ".jpg", ".jpeg"]

DISCLAIMER = (
    "Hasil deteksi adalah bantuan awal untuk review internal. Keputusan final tetap harus divalidasi oleh reviewer "
    "yang memahami PMK, kebijakan internal, dan konteks pekerjaan."
)


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "upload"))
    return cleaned.strip("._") or "upload"


def save_uploaded_file(uploaded_file: Any, upload_dir: Path | None = None) -> Path:
    upload_dir = upload_dir or UPLOAD_DIR
    upload_dir.mkdir(parents=True, exist_ok=True)
    name = safe_filename(getattr(uploaded_file, "name", "upload"))
    path = upload_dir / name
    data = uploaded_file.getbuffer() if hasattr(uploaded_file, "getbuffer") else uploaded_file.read()
    path.write_bytes(bytes(data))
    return path


def load_uploaded_path(file_path: str | Path) -> dict[str, Any]:
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
        loaded = load_excel_or_csv(path)
        frame = normalize_dataframe(loaded["dataframe"])
        detected = detect_columns(frame)
        generic_text_hit = any(key in detected for key in ("work_title", "description", "material_service_name", "notes"))
        if suffix in [".xlsx", ".xls"] and not generic_text_hit:
            rab_items = load_rab_excel_items(path)
            if rab_items is not None and not rab_items.empty:
                frame = normalize_dataframe(rab_items)
                loaded = {
                    "sheet": "RAB/REALISASI",
                    "warning": "Format RAB terdeteksi. Review memakai Judul dan Item per RAB.",
                }
        detected = detect_columns(frame)
        columns = list(frame.columns)
        text_defaults = ["review_text"] if "review_text" in columns else [
            col
            for key, col in detected.items()
            if key in ("work_title", "description", "material_service_name", "notes")
        ]
        text_defaults = text_defaults or columns[:1]
        state = {
            "kind": "table",
            "path": str(path),
            "sheet": loaded["sheet"],
            "data": frame.to_dict("records"),
            "columns": columns,
            "detected": detected,
        }
        msg = f"{loaded.get('warning', '')} Kolom terdeteksi: {detected}"
        return {
            "preview": frame.head(30),
            "columns": columns,
            "text_defaults": text_defaults,
            "detected": detected,
            "mapping": {
                "volume": {"choices": columns, "value": detected.get("volume")},
                "unit": {"choices": columns, "value": detected.get("unit")},
                "unit_price": {"choices": columns, "value": detected.get("unit_price")},
                "total_price": {"choices": columns, "value": detected.get("total_price")},
            },
            "message": msg.strip(),
            "state": state,
        }

    if suffix == ".pdf":
        chunks, warning, scanned = extract_text_from_pdf(path)
        settings = db.get_settings()
        if scanned:
            ocr_text, ocr_note = extract_text_from_pdf_scan(path, settings.get("ocr_mode", "auto"))
            if ocr_text.strip():
                chunks = [{"page_or_sheet": "OCR PDF", "text": ocr_text}]
                warning = ocr_note
            else:
                warning = f"{warning} {ocr_note}".strip()
        frame = pd.DataFrame(chunks)
        state = {
            "kind": "chunks",
            "path": str(path),
            "data": chunks,
            "source_quality": "ocr" if scanned else "digital_pdf",
        }
        return {
            "preview": frame,
            "columns": ["text"],
            "text_defaults": ["text"],
            "detected": {},
            "mapping": {key: empty_mapping for key in ["volume", "unit", "unit_price", "total_price"]},
            "message": warning,
            "state": state,
        }

    text, note = extract_text_from_image(path, db.get_settings().get("ocr_mode", "auto"))
    chunks = [{"page_or_sheet": "Image OCR", "text": text}] if text else []
    frame = pd.DataFrame(chunks)
    return {
        "preview": frame,
        "columns": ["text"],
        "text_defaults": ["text"],
        "detected": {},
        "mapping": {key: empty_mapping for key in ["volume", "unit", "unit_price", "total_price"]},
        "message": note,
        "state": {"kind": "chunks", "path": str(path), "data": chunks, "source_quality": "ocr"},
    }


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
    if upload_state.get("kind") == "table":
        frame = pd.DataFrame(upload_state["data"])
        combined = combine_selected_text_columns(frame, text_columns or [])
        items = []
        for idx, text in combined.items():
            row = frame.loc[idx]
            items.append(
                {
                    "row_id": str(row.get("row_id", idx + 1)),
                    "source_file": path.name,
                    "page_or_sheet": row.get("sheet", upload_state.get("sheet", "")),
                    "original_text": text,
                    "item_description": text,
                    "judul_rab": row.get("judul_rab", ""),
                    "item_per_rab": row.get("item_per_rab", text),
                    "section": row.get("section", ""),
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
) -> tuple[list[dict[str, Any]], str]:
    items, msg = build_items(upload_state, text_columns, volume_col, unit_col, unit_price_col, total_price_col)
    if not items:
        return [], f"Review belum dapat dijalankan. {msg}"
    results = detect_items(items, db.get_settings())
    return results, f"Review selesai. {msg} {DISCLAIMER}"


def analyze_redaction(text: str) -> dict[str, Any] | None:
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
        },
        db.get_settings(),
    )


def review_summary_dataframe(results: list[dict[str, Any]] | None) -> pd.DataFrame:
    frame = pd.DataFrame(results or [])
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "Row",
                "File",
                "Sheet",
                "Judul",
                "Bagian",
                "Item per RAB",
                "Kategori",
                "Keyword",
                "Tipe Deteksi",
                "Confidence",
                "Confidence Level",
                "Alasan Deteksi",
                "Sugesti Perubahan Redaksi",
            ]
        )
    frame = frame[frame["confidence_label"].isin(["Sedang", "Tinggi", "Sangat tinggi"])].copy()
    columns = [
        "row_id",
        "source_file",
        "page_or_sheet",
        "judul_rab",
        "section",
        "item_per_rab",
        "matched_category",
        "matched_keyword",
        "match_type",
        "final_confidence",
        "confidence_label",
        "explanation",
        "redaction_suggestion",
    ]
    for col in columns:
        if col not in frame.columns:
            frame[col] = ""
    return frame[columns].rename(
        columns={
            "row_id": "Row",
            "source_file": "File",
            "page_or_sheet": "Sheet",
            "judul_rab": "Judul",
            "section": "Bagian",
            "item_per_rab": "Item per RAB",
            "matched_category": "Kategori",
            "matched_keyword": "Keyword",
            "match_type": "Tipe Deteksi",
            "final_confidence": "Confidence",
            "confidence_label": "Confidence Level",
            "explanation": "Alasan Deteksi",
            "redaction_suggestion": "Sugesti Perubahan Redaksi",
        }
    )


def all_materials_dataframe(results: list[dict[str, Any]] | None) -> pd.DataFrame:
    frame = pd.DataFrame(results or [])
    columns = ["row_id", "item_per_rab", "matched_category", "final_confidence", "confidence_label"]
    labels = {
        "row_id": "Row",
        "item_per_rab": "Item RAB",
        "matched_category": "Kategori NAC",
        "final_confidence": "Confidence %",
        "confidence_label": "Confidence Level",
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
        haystack = frame[["item_per_rab", "original_text", "matched_keyword", "matched_category"]].fillna("").astype(str).agg(" ".join, axis=1)
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
        "Ketat": {"fuzzy_threshold": "86", "semantic_threshold": "72"},
        "Seimbang": {"fuzzy_threshold": "78", "semantic_threshold": "60"},
        "Lebih sensitif": {"fuzzy_threshold": "68", "semantic_threshold": "52"},
    }.get(review_mode, {"fuzzy_threshold": "78", "semantic_threshold": "60"})
    return {
        "enable_semantic": "true" if semantic_mode == "Aktif" else "false",
        "enable_stemming": "false",
        "fuzzy_threshold": sensitivity["fuzzy_threshold"],
        "semantic_threshold": sensitivity["semantic_threshold"],
        "ocr_mode": ocr_mode,
        "semantic_user_configured": "true",
    }


def save_simple_settings(review_mode: str, semantic_mode: str, ocr_mode: str) -> str:
    values = settings_for_mode(review_mode, semantic_mode, ocr_mode)
    for key, value in values.items():
        db.save_setting(key, value)
    return f"Settings tersimpan: mode review {review_mode}, semantic {semantic_mode}, OCR {ocr_mode}."


def semantic_package_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except Exception:
        return False
    return True


def row_choices(results: list[dict[str, Any]] | None, only_with_synonym: bool = False) -> list[str]:
    frame = pd.DataFrame(results or [])
    if frame.empty:
        return []
    if only_with_synonym:
        frame = frame[frame.get("suggested_synonym_candidate", "").astype(str).str.strip() != ""]
    return [f"{row.get('row_id')} | {str(row.get('item_per_rab') or row.get('original_text') or '')[:80]}" for _, row in frame.iterrows()]
