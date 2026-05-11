from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from . import db
from .keyword_manager import export_keyword_database, import_keywords_from_excel


def save_row_feedback(
    results: list[dict[str, Any]] | None,
    row_selection: str,
    feedback_type: str,
    redaction: str = "",
    notes: str = "",
) -> str:
    row_id = parse_row_id(row_selection)
    frame = pd.DataFrame(results or [])
    if frame.empty or not row_id:
        return "Pilih row hasil review."
    row = frame[frame["row_id"].astype(str) == str(row_id)]
    if row.empty:
        return "Row tidak ditemukan."
    rec = row.iloc[0].to_dict()
    db.save_feedback(row_id, rec.get("original_text", ""), rec.get("matched_keyword", ""), feedback_type, redaction, notes)
    return "Feedback tersimpan ke SQLite."


def approve_suggested_synonym(results: list[dict[str, Any]] | None, row_selection: str, weight: float = 0.85) -> str:
    row_id = parse_row_id(row_selection)
    frame = pd.DataFrame(results or [])
    if frame.empty or not row_id:
        return "Pilih row yang memiliki kandidat sinonim."
    row = frame[frame["row_id"].astype(str) == str(row_id)]
    if row.empty:
        return "Row tidak ditemukan."
    rec = row.iloc[0].to_dict()
    candidate = str(rec.get("suggested_synonym_candidate", "") or "").strip()
    keyword = str(rec.get("suggested_synonym_for_keyword", "") or rec.get("matched_keyword", "") or "").strip()
    if not candidate or not keyword:
        return "Baris ini belum memiliki kandidat sinonim."
    keyword_row = db.get_keyword_by_text(keyword)
    if not keyword_row:
        return f"Keyword induk tidak ditemukan: {keyword}"
    if db.synonym_exists(keyword_row["id"], candidate):
        return "Sinonim sudah ada di database."
    db.add_synonym(keyword_row["id"], candidate, float(weight or 0.85), "active")
    db.save_feedback(
        row_id,
        rec.get("original_text", ""),
        keyword,
        "Add as Synonym",
        candidate,
        "Approved model-suggested synonym",
    )
    return f"Sinonim '{candidate}' ditambahkan untuk keyword '{keyword}'."


def add_keyword_simple(keyword: str) -> str:
    keyword = str(keyword or "").strip()
    if not keyword:
        return "Isi nama keyword NAC terlebih dahulu."
    existing = db.get_keyword_by_text(keyword)
    if existing and existing.get("status") == "active":
        return f"Keyword '{keyword}' sudah ada."
    category, severity, notes = infer_keyword_metadata(keyword)
    keyword_id = db.add_keyword(
        category,
        keyword,
        notes,
        "USER",
        severity,
        "active",
        "Metadata kategori/confidence dasar dipilih otomatis oleh sistem.",
    )
    aliases = auto_aliases(keyword)
    for alias in aliases:
        if not db.synonym_exists(keyword_id, alias):
            db.add_synonym(keyword_id, alias, 0.85, "active")
    msg = f"Keyword '{keyword}' ditambahkan."
    if aliases:
        msg += " Kandidat sinonim/parafrasa otomatis: " + ", ".join(aliases) + "."
    return msg


def delete_keyword(keyword_selection: str) -> str:
    keyword_id = parse_row_id(keyword_selection)
    if not keyword_id:
        return "Pilih keyword yang ingin dinonaktifkan."
    try:
        db.update_keyword_status(int(keyword_id), "inactive")
    except Exception as exc:
        return f"Gagal menghapus keyword: {exc}"
    return "Keyword dinonaktifkan. Data tidak dihapus permanen agar tetap audit-friendly."


def bulk_deactivate_keywords(keyword_ids: Iterable[Any]) -> str:
    ids = normalize_keyword_ids(keyword_ids)
    if not ids:
        return "Pilih minimal satu keyword untuk dinonaktifkan."
    with db.connect() as conn:
        for keyword_id in ids:
            conn.execute("UPDATE nac_keywords SET status='inactive', updated_at=? WHERE id=?", (db.now(), keyword_id))
    return f"{len(ids)} keyword dinonaktifkan. Data tetap tersimpan untuk audit dan bisa direstore."


def bulk_restore_keywords(keyword_ids: Iterable[Any]) -> str:
    ids = normalize_keyword_ids(keyword_ids)
    if not ids:
        return "Pilih minimal satu keyword untuk direstore."
    with db.connect() as conn:
        for keyword_id in ids:
            conn.execute("UPDATE nac_keywords SET status='active', updated_at=? WHERE id=?", (db.now(), keyword_id))
    return f"{len(ids)} keyword direstore ke status active."


def bulk_delete_keywords(keyword_ids: Iterable[Any]) -> str:
    ids = normalize_keyword_ids(keyword_ids)
    if not ids:
        return "Pilih minimal satu keyword untuk dihapus permanen."
    placeholders = ",".join("?" for _ in ids)
    with db.connect() as conn:
        conn.execute(f"DELETE FROM nac_synonyms WHERE nac_keyword_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM exceptions WHERE nac_keyword_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM nac_keywords WHERE id IN ({placeholders})", ids)
    return f"{len(ids)} keyword dihapus permanen beserta sinonim dan exception terkait. Feedback historis tetap disimpan."


def import_keywords_file(file_path: str | Path) -> str:
    count = import_keywords_from_excel(file_path)
    return f"{count} keyword berhasil diimpor dari Excel."


def export_keywords_file(path: str | Path) -> str:
    return str(export_keyword_database(path))


def parse_row_id(selection: str) -> str:
    return str(selection or "").split("|", 1)[0].strip()


def normalize_keyword_ids(keyword_ids: Iterable[Any]) -> list[int]:
    normalized = []
    for value in keyword_ids or []:
        try:
            keyword_id = int(value)
        except (TypeError, ValueError):
            continue
        if keyword_id not in normalized:
            normalized.append(keyword_id)
    return normalized


def keyword_choices(active_only: bool = True) -> list[str]:
    rows = db.get_keywords(False)
    if active_only:
        rows = [row for row in rows if row.get("status") == "active"]
    return [f"{row['id']} | {row['keyword']}" for row in rows]


def auto_aliases(keyword: str) -> list[str]:
    base = str(keyword or "").strip().lower()
    if not base:
        return []
    variants = []
    if not base.startswith("biaya "):
        variants.append(f"biaya {base}")
    if " " in base:
        variants.append(base.replace("biaya ", ""))
    if "honorarium" in base:
        variants.extend(["honor", "fee"])
    if "konsumsi" in base:
        variants.extend(["makan minum", "jamuan", "snack"])
    if "transport" in base:
        variants.extend(["transportasi", "bantuan transport"])
    cleaned = []
    for item in variants:
        item = item.strip()
        if item and item != base and item not in cleaned:
            cleaned.append(item)
    return cleaned[:5]


def infer_keyword_metadata(keyword: str) -> tuple[str, str, str]:
    text = str(keyword or "").lower()
    rules = [
        (
            ["konsumsi", "makan", "minum", "snack", "jamuan", "catering"],
            "Rapat/Jamuan",
            "high",
            "Kandidat biaya konsumsi/jamuan; validasi konteks kegiatan dan aturan internal.",
        ),
        (
            ["hadiah", "souvenir", "doorprize", "oleh-oleh", "cinderamata"],
            "Pribadi/Hadiah",
            "high",
            "Kandidat biaya hadiah/cinderamata; perlu validasi allowability.",
        ),
        (
            ["pegawai", "tunjangan", "cuti", "fasilitas", "seragam"],
            "Pegawai",
            "high",
            "Kandidat biaya terkait pegawai; cek pemisahan komponen allowable/non-allowable.",
        ),
        (["denda", "sanksi", "penalti"], "Denda/Sanksi", "high", "Kandidat denda/sanksi; biasanya perlu review khusus."),
        (
            ["honor", "narasumber", "fee", "uang saku", "pulsa"],
            "Personel/Operasional",
            "medium",
            "Kandidat biaya personel/operasional; validasi dasar pembayaran dan output kegiatan.",
        ),
        (
            ["transport", "perjalanan", "akomodasi"],
            "Transportasi/Personel",
            "medium",
            "Kandidat biaya perjalanan/transport; pastikan terkait langsung dengan pekerjaan teknis.",
        ),
    ]
    for tokens, category, severity, notes in rules:
        if any(token in text for token in tokens):
            return category, severity, notes
    return "Umum", "medium", "Keyword ditambahkan dari UI sederhana; wajib validasi PMK/kebijakan internal."
