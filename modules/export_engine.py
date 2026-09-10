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
            "nac_group", "correction_percentage", "correction_percentage_label", "transaction_type",
            "reference_percentage", "reference_percentage_label", "applied_nac_percentage", "percentage_source",
            "percentage_status", "selected_transaction_type", "alternative_transaction", "alternative_percentage",
            "alternative_percentage_label", "is_ambiguous", "gl_account", "gl_account_description",
            "title_match_keyword", "title_match_score", "section_match_keyword", "section_match_score",
            "item_match_keyword", "item_match_score", "context_consistency_score", "context_conflict_penalty",
            "fuzzy_score", "semantic_score", "allowable_score", "final_confidence", "confidence_label",
            "semantic_candidate_text", "semantic_candidate_source", "semantic_reason", "semantic_model",
            "decision_reason", "explanation", "recommended_action", "redaction_suggestion", "suggested_synonym_candidate",
            "suggested_synonym_for_keyword", "synonym_suggestion_confidence", "synonym_suggestion_reason",
            "user_feedback", "reviewer_notes",
        ])
    required_columns = [
        "row_id", "redaction_suggestion", "recommended_action", "matched_keyword", "matched_category",
        "nac_group", "correction_percentage_label", "reference_percentage_label", "percentage_status",
        "transaction_type", "selected_transaction_type", "percentage_source", "alternative_transaction",
        "alternative_percentage_label", "title_match_keyword", "title_match_score", "section_match_keyword",
        "section_match_score", "item_match_keyword", "item_match_score", "context_consistency_score",
        "decision_reason", "gl_account",
        "gl_account_description", "match_type", "fuzzy_score", "semantic_score",
        "semantic_candidate_text", "semantic_candidate_source", "semantic_reason", "semantic_model",
    ]
    for column in required_columns:
        if column not in findings.columns:
            findings[column] = ""
    summary = _summary(findings)
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        findings.to_excel(writer, sheet_name="Findings", index=False)
        findings[[
            "row_id", "redaction_suggestion", "recommended_action", "correction_percentage_label",
            "reference_percentage_label", "percentage_status", "selected_transaction_type",
            "alternative_transaction", "alternative_percentage_label", "decision_reason", "semantic_reason",
        ]].to_excel(writer, sheet_name="Suggestions", index=False)
        pd.DataFrame(db.get_feedback()).to_excel(writer, sheet_name="Feedback Log", index=False)
        findings[[
            "row_id", "matched_keyword", "matched_category", "nac_group", "correction_percentage_label",
            "reference_percentage_label", "percentage_status", "selected_transaction_type", "percentage_source",
            "alternative_transaction", "alternative_percentage_label", "title_match_keyword", "title_match_score",
            "section_match_keyword", "section_match_score", "item_match_keyword", "item_match_score",
            "context_consistency_score", "decision_reason", "gl_account", "gl_account_description", "match_type",
            "fuzzy_score", "semantic_score",
            "semantic_candidate_text", "semantic_candidate_source", "semantic_reason", "semantic_model",
        ]].to_excel(writer, sheet_name="Keyword Matches", index=False)
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
    columns = [
        "row_id", "item_per_rab", "selected_transaction_type", "correction_percentage_label",
        "percentage_status", "context_audit", "final_confidence", "confidence_label", "decision_reason",
    ]
    headers = [
        "Row", "Nama Material", "Type of Transaction", "Prosentase NAC", "Status Prosentase",
        "Audit Konteks", "Confidence %", "Level", "Alasan Keputusan",
    ]
    _write_pdf(path, title, rows, columns, headers)
    return str(path)


def export_all_materials_pdf(results):
    rows = _all_material_rows(results)
    path = _pdf_path("seluruh_material_rab")
    title = "Tabel Seluruh Material RAB"
    columns = [
        "row_id", "item_per_rab", "selected_transaction_type", "correction_percentage_label",
        "percentage_status", "context_audit", "final_confidence", "confidence_label", "decision_reason",
    ]
    headers = [
        "Row", "Nama Material", "Type of Transaction", "Prosentase NAC", "Status Prosentase",
        "Audit Konteks", "Confidence %", "Level", "Alasan Keputusan",
    ]
    _write_pdf(path, title, rows, columns, headers)
    return str(path)


def export_all_materials_excel(results):
    EXPORT_DIR.mkdir(exist_ok=True)
    path = EXPORT_DIR / f"seluruh_material_rab_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    frame = pd.DataFrame(_all_material_rows(results))
    columns = {
        "row_id": "Row",
        "judul_rab": "Judul RAB",
        "section": "Subjudul/Section",
        "item_per_rab": "Nama Material",
        "matched_category": "Kategori NAC",
        "selected_transaction_type": "Type of Transaction",
        "reference_percentage_label": "Prosentase Referensi",
        "correction_percentage_label": "Prosentase NAC",
        "percentage_status": "Status Prosentase",
        "percentage_source": "Sumber Prosentase",
        "alternative_transaction": "Alternatif Transaksi",
        "alternative_percentage_label": "Alternatif Prosentase",
        "title_match_keyword": "Match Judul",
        "title_match_score": "Skor Judul",
        "section_match_keyword": "Match Subjudul",
        "section_match_score": "Skor Subjudul",
        "item_match_keyword": "Match Item",
        "item_match_score": "Skor Item",
        "context_consistency_score": "Konsistensi Konteks %",
        "semantic_audit": "Semantic Audit",
        "final_confidence": "Confidence %",
        "confidence_label": "Confidence Level",
        "decision_reason": "Alasan Keputusan",
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
    for col in [
        "row_id", "judul_rab", "section", "item_per_rab", "matched_category", "correction_percentage_label",
        "reference_percentage_label", "percentage_status", "percentage_source", "selected_transaction_type",
        "alternative_transaction", "alternative_percentage_label", "title_match_keyword", "title_match_score",
        "section_match_keyword", "section_match_score", "item_match_keyword", "item_match_score",
        "context_consistency_score", "decision_reason",
        "semantic_candidate_text", "semantic_reason", "semantic_model", "final_confidence", "confidence_label",
    ]:
        if col not in frame.columns:
            frame[col] = ""
    frame["item_per_rab"] = frame["item_per_rab"].fillna(frame.get("item_description", ""))
    frame["matched_category"] = frame["matched_category"].replace("", "-").fillna("-")
    frame["semantic_audit"] = frame.apply(_semantic_audit, axis=1)
    frame["context_audit"] = frame.apply(_context_audit, axis=1)
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
    story = [
        Paragraph(title, styles["Title"]),
        Paragraph(
            "Prosentase NAC adalah aturan koreksi transaksi. Confidence adalah keyakinan klasifikasi dan tidak digunakan untuk menciptakan prosentase baru.",
            styles["BodyText"],
        ),
        Spacer(1, 12),
    ]
    data = [headers]
    for row in rows:
        data.append([_pdf_cell(row.get(col, "")) for col in columns])
    if len(data) == 1:
        data.append(["-"] + ["Tidak ada data"] + ["-"] * (len(headers) - 2))
    default_widths = [28, 130, 100, 55, 82, 105, 52, 55, 105]
    table = Table(data, colWidths=default_widths[: len(headers)], repeatRows=1)
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


def _semantic_audit(row):
    candidate = str(row.get("semantic_candidate_text") or "").strip()
    reason = str(row.get("semantic_reason") or "").strip()
    if not candidate and not reason:
        return "-"
    if candidate and reason:
        return f"{candidate}: {reason}"
    return candidate or reason


def _context_audit(row):
    evidence = []
    for label, keyword_key, score_key in [
        ("Judul", "title_match_keyword", "title_match_score"),
        ("Subjudul", "section_match_keyword", "section_match_score"),
        ("Item", "item_match_keyword", "item_match_score"),
    ]:
        keyword = str(row.get(keyword_key) or "").strip()
        if keyword:
            evidence.append(f"{label}: {keyword} ({float(row.get(score_key) or 0):.1f})")
    consistency = float(row.get("context_consistency_score") or 0)
    if consistency:
        evidence.append(f"Konsistensi: {consistency:.1f}%")
    return "; ".join(evidence) or "-"
