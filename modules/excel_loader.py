from __future__ import annotations

from pathlib import Path

import pandas as pd

from .adaptive_parser import parse_document, preview_dataframe


COLUMN_HINTS = {
    "item_number": ["no", "nomor", "item", "kode"],
    "work_title": ["pekerjaan", "judul", "uraian pekerjaan", "judul_rab"],
    "description": ["uraian", "deskripsi", "keterangan", "item_per_rab"],
    "material_service_name": ["material", "barang", "jasa", "nama", "item_per_rab"],
    "volume": ["volume", "vol", "qty", "kuantitas"],
    "unit": ["satuan", "unit", "uom"],
    "unit_price": ["harga satuan", "harga", "price", "harsat", "unit_price"],
    "total_price": ["jumlah", "total", "subtotal", "nilai", "total_price"],
    "notes": ["catatan", "notes", "remark"],
}


def load_excel_or_csv(file_path):
    document = parse_document(file_path)
    frame = pd.DataFrame([item.to_dict() for item in document.items])
    sheets = sorted({item.page_or_sheet for item in document.items})
    return {
        "dataframe": frame,
        "sheet": ", ".join(sheets),
        "warning": _document_message(document),
        "document": document,
    }


def load_rab_excel_items(file_path):
    """Backward-compatible wrapper around the adaptive RAB profiler."""
    path = Path(file_path)
    if path.suffix.lower() not in {".xlsx", ".xls"}:
        return None
    document = parse_document(path)
    if not document.items:
        return None
    return pd.DataFrame([item.to_dict() for item in document.items])


def detect_columns(df):
    detected = {}
    normalized = {str(column).lower().strip(): column for column in df.columns}
    for target, hints in COLUMN_HINTS.items():
        for label, original in normalized.items():
            if any(hint == label or hint in label for hint in hints):
                detected[target] = original
                break
    return detected


def combine_selected_text_columns(df, text_columns):
    if not text_columns:
        raise ValueError("Pilih minimal satu kolom teks untuk review.")
    existing = [column for column in text_columns if column in df.columns]
    if not existing:
        raise ValueError("Kolom teks yang dipilih tidak ditemukan.")
    return df[existing].fillna("").astype(str).agg(" | ".join, axis=1)


def normalize_dataframe(df):
    frame = df.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def finance_preview(document):
    return preview_dataframe(document)


def _document_message(document) -> str:
    labels = [region.diagnostic.confidence_label for region in document.regions]
    confidence = ", ".join(labels) if labels else "tidak tersedia"
    warning_count = len(document.warnings) + sum(len(region.diagnostic.warnings) for region in document.regions)
    blocked = " Mapping perlu konfirmasi manual sebelum review." if document.review_blocked else ""
    return (
        f"Parser adaptif menemukan {len(document.items)} item pada {len(document.regions)} region. "
        f"Confidence struktur: {confidence}. Warning: {warning_count}.{blocked}"
    )
