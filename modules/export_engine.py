from datetime import datetime
import os
from pathlib import Path

import pandas as pd

from . import db


EXPORT_DIR = Path(os.environ.get("RAB_NAC_EXPORT_DIR", Path(__file__).resolve().parents[1] / "exports"))


def export_review_excel(results):
    EXPORT_DIR.mkdir(exist_ok=True)
    path = EXPORT_DIR / f"rab_nac_review_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    findings = pd.DataFrame(results)
    if findings.empty:
        findings = pd.DataFrame(columns=[
            "row_id", "source_file", "page_or_sheet", "original_text", "normalized_text", "item_description",
            "volume", "unit", "unit_price", "total_price", "matched_keyword", "matched_category", "match_type",
            "fuzzy_score", "semantic_score", "allowable_score", "final_confidence", "confidence_label",
            "explanation", "recommended_action", "redaction_suggestion", "suggested_synonym_candidate",
            "suggested_synonym_for_keyword", "synonym_suggestion_confidence", "synonym_suggestion_reason",
            "user_feedback", "reviewer_notes",
        ])
    summary = _summary(findings)
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        findings.to_excel(writer, sheet_name="Findings", index=False)
        findings[["row_id", "redaction_suggestion", "recommended_action"]].to_excel(writer, sheet_name="Suggestions", index=False)
        pd.DataFrame(db.get_feedback()).to_excel(writer, sheet_name="Feedback Log", index=False)
        findings[["row_id", "matched_keyword", "matched_category", "match_type", "fuzzy_score", "semantic_score"]].to_excel(writer, sheet_name="Keyword Matches", index=False)
        pd.DataFrame(db.get_keywords(False)).to_excel(writer, sheet_name="NAC Keyword Database Snapshot", index=False)
    return str(path)


def _summary(findings):
    rows = [
        {"metric": "Disclaimer", "value": "Hasil deteksi adalah bantuan awal untuk review internal. Keputusan final tetap harus divalidasi oleh reviewer yang memahami PMK, kebijakan internal, dan konteks pekerjaan."},
        {"metric": "total_items_reviewed", "value": len(findings)},
    ]
    if "confidence_label" in findings:
        for label, count in findings["confidence_label"].value_counts().items():
            rows.append({"metric": f"count_{label}", "value": int(count)})
    high = findings[findings.get("confidence_label", pd.Series(dtype=str)).isin(["Tinggi", "Sangat tinggi"])]
    rows.append({"metric": "count_potential_nac_high_very_high", "value": len(high)})
    if "total_price" in findings:
        values = pd.to_numeric(findings["total_price"], errors="coerce")
        rows.append({"metric": "total_value_detected_rows", "value": float(values.sum(skipna=True) or 0)})
        for label, group in findings.assign(_value=values).groupby("confidence_label", dropna=False):
            rows.append({"metric": f"total_value_{label}", "value": float(group["_value"].sum(skipna=True) or 0)})
    return pd.DataFrame(rows)


def export_feedback_logs():
    EXPORT_DIR.mkdir(exist_ok=True)
    path = EXPORT_DIR / f"feedback_log_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    pd.DataFrame(db.get_feedback()).to_excel(path, index=False)
    return str(path)


def export_potential_nac_pdf(results):
    rows = _potential_rows(results)
    path = _pdf_path("ringkasan_potensi_nac")
    title = "Ringkasan Potensi NAC Perlu Review"
    columns = ["row_id", "item_per_rab", "matched_category", "final_confidence", "confidence_label"]
    headers = ["Row", "Nama Material", "Kategori NAC", "Confidence %", "Confidence Level"]
    _write_pdf(path, title, rows, columns, headers)
    return str(path)


def export_all_materials_pdf(results):
    rows = _all_material_rows(results)
    path = _pdf_path("seluruh_material_rab")
    title = "Tabel Seluruh Material RAB"
    columns = ["row_id", "item_per_rab", "matched_category", "final_confidence", "confidence_label"]
    headers = ["Row", "Nama Material", "Kategori NAC", "Confidence %", "Confidence Level"]
    _write_pdf(path, title, rows, columns, headers)
    return str(path)


def export_all_materials_excel(results):
    EXPORT_DIR.mkdir(exist_ok=True)
    path = EXPORT_DIR / f"seluruh_material_rab_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    frame = pd.DataFrame(_all_material_rows(results))
    columns = {
        "row_id": "Row",
        "item_per_rab": "Nama Material",
        "matched_category": "Kategori NAC",
        "final_confidence": "Confidence %",
        "confidence_label": "Confidence Level",
    }
    frame = frame[list(columns)].rename(columns=columns) if not frame.empty else pd.DataFrame(columns=list(columns.values()))
    frame.to_excel(path, index=False)
    return str(path)


def _potential_rows(results):
    frame = pd.DataFrame(results or [])
    if frame.empty:
        return []
    frame = frame[frame["confidence_label"].isin(["Sedang", "Tinggi", "Sangat tinggi"])].copy()
    return _normalize_export_rows(frame)


def _all_material_rows(results):
    frame = pd.DataFrame(results or [])
    if frame.empty:
        return []
    return _normalize_export_rows(frame)


def _normalize_export_rows(frame):
    frame = frame.copy()
    for col in ["row_id", "item_per_rab", "matched_category", "final_confidence", "confidence_label"]:
        if col not in frame.columns:
            frame[col] = ""
    frame["item_per_rab"] = frame["item_per_rab"].fillna(frame.get("item_description", ""))
    frame["matched_category"] = frame["matched_category"].replace("", "-").fillna("-")
    frame["final_confidence"] = pd.to_numeric(frame["final_confidence"], errors="coerce").fillna(0).round(2)
    frame["_row_sort"] = pd.to_numeric(frame["row_id"], errors="coerce")
    frame = frame.sort_values("_row_sort", na_position="last")
    return frame.to_dict("records")


def _pdf_path(prefix):
    EXPORT_DIR.mkdir(exist_ok=True)
    return EXPORT_DIR / f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"


def _write_pdf(path, title, rows, columns, headers):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    data = [headers]
    for row in rows:
        data.append([_pdf_cell(row.get(col, "")) for col in columns])
    if len(data) == 1:
        data.append(["-", "Tidak ada data", "-", "-", "-"])
    table = Table(data, colWidths=[45, 330, 130, 80, 120], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1665D6")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DBE7F7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FBFF")]),
            ]
        )
    )
    story.append(table)
    doc.build(story)


def _pdf_cell(value):
    text = str(value if value is not None else "")
    return text[:180]
