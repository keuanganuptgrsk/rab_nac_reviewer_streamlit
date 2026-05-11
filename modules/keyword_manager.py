import pandas as pd

from . import db


def _infer_keyword_metadata(keyword):
    text = str(keyword or "").lower()
    rules = [
        (["konsumsi", "makan", "minum", "snack", "jamuan", "catering"], "Rapat/Jamuan", "high"),
        (["hadiah", "souvenir", "doorprize", "oleh-oleh", "cinderamata"], "Pribadi/Hadiah", "high"),
        (["pegawai", "tunjangan", "cuti", "fasilitas", "seragam"], "Pegawai", "high"),
        (["denda", "sanksi", "penalti"], "Denda/Sanksi", "high"),
        (["honor", "narasumber", "fee", "uang saku", "pulsa"], "Personel/Operasional", "medium"),
        (["transport", "perjalanan", "akomodasi"], "Transportasi/Personel", "medium"),
    ]
    for tokens, category, severity in rules:
        if any(token in text for token in tokens):
            return category, severity
    return "Umum", "medium"


def import_keywords_from_excel(file_path):
    frame = pd.read_excel(file_path).fillna("")
    if "keyword" not in frame.columns:
        if len(frame.columns) == 1:
            frame = frame.rename(columns={frame.columns[0]: "keyword"})
        else:
            raise ValueError("Kolom wajib hilang: keyword")
    added = 0
    for _, row in frame.iterrows():
        if not str(row.get("keyword", "")).strip():
            continue
        inferred_category, inferred_severity = _infer_keyword_metadata(row.get("keyword", ""))
        keyword_id = db.add_keyword(
            row.get("category", "") or inferred_category,
            row.get("keyword", ""),
            row.get("description", "") or "Keyword import Excel; kategori/confidence dasar dapat dipilih otomatis bila kosong.",
            row.get("reference", ""),
            row.get("severity", "") or inferred_severity,
            row.get("status", "active") or "active",
            row.get("notes", ""),
            "excel_import",
        )
        for syn in str(row.get("synonyms", "")).split(";"):
            syn = syn.strip()
            if syn:
                db.add_synonym(keyword_id, syn)
        added += 1
    return added


def export_keyword_database(path):
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        pd.DataFrame(db.get_keywords(False)).to_excel(writer, sheet_name="NAC Keywords", index=False)
        pd.DataFrame(db.get_synonyms(False)).to_excel(writer, sheet_name="Synonyms", index=False)
        pd.DataFrame(db.get_allowable(False)).to_excel(writer, sheet_name="Allowable", index=False)
        pd.DataFrame(db.get_exceptions(False)).to_excel(writer, sheet_name="Exceptions", index=False)
    return path
