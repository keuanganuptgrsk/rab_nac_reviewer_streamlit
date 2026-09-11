from __future__ import annotations

import html
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import db


EXPORT_DIR = Path(os.environ.get("RAB_NAC_EXPORT_DIR", Path(__file__).resolve().parents[1] / "exports"))
AUDIT_COLUMNS = [
    "source_id",
    "row_id",
    "source_file",
    "page_or_sheet",
    "source_coordinate",
    "judul_rab",
    "section",
    "item_per_rab",
    "unit",
    "volume",
    "material_unit_price",
    "service_unit_price",
    "unit_price",
    "material_total",
    "service_total",
    "total_price",
    "matched_keyword_id",
    "matched_keyword",
    "matched_category",
    "nac_group",
    "selected_transaction_type",
    "reference_percentage",
    "applied_nac_percentage",
    "percentage_status",
    "percentage_source",
    "final_confidence",
    "deterministic_confidence",
    "confidence_label",
    "recommended_action",
    "is_ambiguous",
    "decision_reason",
    "explanation",
    "title_match_keyword",
    "title_match_score",
    "section_match_keyword",
    "section_match_score",
    "item_match_keyword",
    "item_match_score",
    "context_consistency_score",
    "allowable_score",
    "allowable_keyword",
    "exception_pattern",
    "semantic_candidate_text",
    "semantic_reason",
    "semantic_model",
    "engine",
    "provider_model",
    "prompt_version",
    "analysis_timestamp",
    "ai_confidence",
    "ai_ranked_candidate_ids",
    "ai_selected_candidate_id",
    "ai_ambiguity",
    "ai_manual_review",
    "ai_evidence_terms",
    "ai_reason",
    "provider_latency_ms",
    "provider_error",
    "provider_cache_hit",
    "decision_source",
    "rule_pack_version",
    "parser_strategy",
    "parser_confidence",
    "parser_warnings",
    "provenance",
]


def export_review_excel(results):
    path = _xlsx_path("rab_nac_review")
    findings = _audit_frame(results)
    summary = _summary(findings)
    suggestions = _select_columns(
        findings,
        [
            "source_id",
            "row_id",
            "item_per_rab",
            "redaction_suggestion",
            "recommended_action",
            "applied_nac_percentage",
            "percentage_status",
            "selected_transaction_type",
            "decision_reason",
            "ai_reason",
        ],
    )
    matches = _select_columns(
        findings,
        [
            "source_id",
            "matched_keyword",
            "matched_category",
            "nac_group",
            "selected_transaction_type",
            "reference_percentage",
            "applied_nac_percentage",
            "percentage_source",
            "title_match_keyword",
            "title_match_score",
            "section_match_keyword",
            "section_match_score",
            "item_match_keyword",
            "item_match_score",
            "context_consistency_score",
            "decision_reason",
            "engine",
            "provider_model",
            "ai_confidence",
            "decision_source",
        ],
    )
    sheets = {
        "Summary": summary,
        "Findings": findings,
        "Suggestions": suggestions,
        "Keyword Matches": matches,
        "Feedback Log": pd.DataFrame(db.get_feedback()),
        "NAC Keyword Snapshot": pd.DataFrame(db.get_keywords(False)),
    }
    write_professional_workbook(path, sheets)
    return str(path)


def export_feedback_logs():
    path = _xlsx_path("feedback_log")
    write_professional_workbook(path, {"Feedback Log": pd.DataFrame(db.get_feedback())})
    return str(path)


def export_potential_nac_pdf(results):
    rows = _potential_rows(results)
    path = _pdf_path("ringkasan_potensi_nac")
    _write_review_pdf(path, "Ringkasan Potensi NAC Perlu Review", rows)
    return str(path)


def export_all_materials_pdf(results):
    rows = _all_material_rows(results)
    path = _pdf_path("seluruh_material_rab")
    _write_review_pdf(path, "Tabel Seluruh Material RAB", rows)
    return str(path)


def export_all_materials_excel(results):
    path = _xlsx_path("seluruh_material_rab")
    frame = _audit_frame(results)
    visible = _select_columns(
        frame,
        [
            "source_id",
            "row_id",
            "judul_rab",
            "section",
            "item_per_rab",
            "unit",
            "volume",
            "unit_price",
            "total_price",
            "matched_category",
            "selected_transaction_type",
            "reference_percentage",
            "applied_nac_percentage",
            "percentage_status",
            "final_confidence",
            "context_consistency_score",
            "confidence_label",
            "recommended_action",
            "decision_reason",
            "engine",
            "provider_model",
            "ai_confidence",
            "decision_source",
            "parser_confidence",
            "source_file",
            "page_or_sheet",
            "source_coordinate",
        ],
    ).rename(
        columns={
            "source_id": "Source ID",
            "row_id": "Row",
            "judul_rab": "Judul RAB",
            "section": "Subjudul/Section",
            "item_per_rab": "Nama Material",
            "unit": "Satuan",
            "volume": "Volume",
            "unit_price": "Harga Satuan",
            "total_price": "Total",
            "matched_category": "Kategori NAC",
            "selected_transaction_type": "Type of Transaction",
            "reference_percentage": "Prosentase Referensi",
            "applied_nac_percentage": "Prosentase NAC",
            "percentage_status": "Status Prosentase",
            "final_confidence": "Confidence %",
            "context_consistency_score": "Konsistensi Konteks %",
            "confidence_label": "Confidence Level",
            "recommended_action": "Rekomendasi",
            "decision_reason": "Alasan Keputusan",
            "engine": "Engine",
            "provider_model": "Provider Model",
            "ai_confidence": "AI Confidence %",
            "decision_source": "Sumber Keputusan",
            "parser_confidence": "Parser Confidence %",
            "source_file": "File",
            "page_or_sheet": "Sheet/Page",
            "source_coordinate": "Source Row",
        }
    )
    write_professional_workbook(path, {"Seluruh Material": visible})
    return str(path)


def _summary(findings: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "metric": "Disclaimer",
            "value": "Hasil deteksi adalah bantuan awal untuk review internal. Prosentase NAC hanya berasal dari rule pack tepercaya.",
        },
        {"metric": "Generated UTC", "value": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        {"metric": "Total item reviewed", "value": len(findings)},
    ]
    if "confidence_label" in findings:
        for label, count in findings["confidence_label"].value_counts().items():
            rows.append({"metric": f"Confidence {label}", "value": int(count)})
    if "recommended_action" in findings:
        manual = findings["recommended_action"].astype(str).str.contains("Review Manual", case=False, na=False).sum()
        rows.append({"metric": "Manual review", "value": int(manual)})
    if "total_price" in findings:
        total = pd.to_numeric(findings["total_price"], errors="coerce").sum(skipna=True)
        rows.append({"metric": "Total nilai baris", "value": float(total or 0)})
    return pd.DataFrame(rows)


def _audit_frame(results: list[dict[str, Any]] | None) -> pd.DataFrame:
    frame = pd.DataFrame(results or [])
    for column in AUDIT_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    if frame.empty:
        return frame[AUDIT_COLUMNS]
    for column in ("parser_warnings", "provenance"):
        frame[column] = frame[column].map(_serializable_text)
    numeric_columns = [
        "volume",
        "material_unit_price",
        "service_unit_price",
        "unit_price",
        "material_total",
        "service_total",
        "total_price",
        "reference_percentage",
        "applied_nac_percentage",
        "final_confidence",
        "deterministic_confidence",
        "ai_confidence",
        "parser_confidence",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[AUDIT_COLUMNS + [column for column in frame.columns if column not in AUDIT_COLUMNS]]


def _potential_rows(results):
    frame = _audit_frame(results)
    if frame.empty:
        return []
    mask = frame["confidence_label"].isin(["Sedang", "Tinggi", "Sangat tinggi"])
    mask |= frame["recommended_action"].astype(str).str.contains("Review Manual", case=False, na=False)
    return frame[mask].to_dict("records")


def _all_material_rows(results):
    return _audit_frame(results).to_dict("records")


def write_professional_workbook(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        workbook = writer.book
        header_format = workbook.add_format(
            {"bold": True, "font_color": "#FFFFFF", "bg_color": "#246B61", "border": 0, "valign": "vcenter"}
        )
        text_format = workbook.add_format({"text_wrap": True, "valign": "top"})
        currency_format = workbook.add_format({"num_format": '#,##0;[Red]-#,##0;"-"', "valign": "top"})
        number_format = workbook.add_format({"num_format": '#,##0.00;[Red]-#,##0.00;"-"', "valign": "top"})
        percent_format = workbook.add_format({"num_format": '0.00"%"', "valign": "top"})
        for sheet_name, source_frame in sheets.items():
            frame = source_frame.copy()
            frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            worksheet = writer.sheets[sheet_name[:31]]
            rows, cols = frame.shape
            worksheet.freeze_panes(1, 0)
            worksheet.set_row(0, 28, header_format)
            for index, column in enumerate(frame.columns):
                worksheet.write(0, index, str(column), header_format)
            if cols:
                worksheet.autofilter(0, 0, max(rows, 1), cols - 1)
            for index, column in enumerate(frame.columns):
                label = str(column)
                lower = label.lower()
                sample = frame[column].dropna().astype(str).head(100)
                content_width = max([len(label)] + [min(len(value), 60) for value in sample]) + 2
                width = min(54, max(11, content_width))
                fmt = text_format
                if any(token in lower for token in ("harga", "total", "nilai")):
                    fmt = currency_format
                    width = max(width, 16)
                elif "prosentase" in lower or "confidence" in lower or lower.endswith("score"):
                    fmt = percent_format
                    width = max(width, 14)
                elif lower in {"volume", "qty", "kuantitas"}:
                    fmt = number_format
                worksheet.set_column(index, index, width, fmt)
                if "confidence" in lower and rows:
                    worksheet.conditional_format(
                        1,
                        index,
                        rows,
                        index,
                        {"type": "3_color_scale", "min_color": "#E7ECEA", "mid_color": "#F3D8A8", "max_color": "#D99A9A"},
                    )
                if any(token in lower for token in ("manual", "ambigu")) and rows:
                    worksheet.conditional_format(
                        1,
                        index,
                        rows,
                        index,
                        {"type": "text", "criteria": "containing", "value": "True", "format": workbook.add_format({"bg_color": "#FCE8E6", "font_color": "#9B2C2C"})},
                    )
            if rows:
                worksheet.set_default_row(34)


def _write_review_pdf(path: Path, title: str, rows: list[dict[str, Any]]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        KeepTogether,
        ListFlowable,
        ListItem,
        NextPageTemplate,
        PageBreak,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rab_titles = _unique_rab_titles(rows)
    metadata_title = _pdf_metadata_title(title, rab_titles)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("RabTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=colors.HexColor("#1F2A2E"), alignment=TA_LEFT, spaceAfter=3)
    subtitle_style = ParagraphStyle("RabSubtitle", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=colors.HexColor("#246B61"), alignment=TA_LEFT, spaceAfter=5)
    title_list_label_style = ParagraphStyle("RabTitleListLabel", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#246B61"), alignment=TA_LEFT, spaceAfter=2)
    title_list_style = ParagraphStyle("RabTitleListItem", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#39474C"))
    body_style = ParagraphStyle("RabBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#39474C"))
    small_style = ParagraphStyle("RabSmall", parent=body_style, fontSize=7.5, leading=9.5)
    section_style = ParagraphStyle("RabSection", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#246B61"), spaceBefore=4, spaceAfter=6)
    label_style = ParagraphStyle("RabLabel", parent=small_style, fontName="Helvetica-Bold", textColor=colors.HexColor("#59676B"))
    table_header_style = ParagraphStyle("RabTableHeader", parent=small_style, fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=colors.white)

    document = BaseDocTemplate(
        str(path),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=metadata_title,
        author="RAB NAC Reviewer",
    )
    landscape_frame = Frame(12 * mm, 16 * mm, landscape(A4)[0] - 24 * mm, landscape(A4)[1] - 30 * mm, id="landscape")
    portrait_frame = Frame(14 * mm, 17 * mm, A4[0] - 28 * mm, A4[1] - 33 * mm, id="portrait")
    document.addPageTemplates(
        [
            PageTemplate(id="summary", pagesize=landscape(A4), frames=[landscape_frame]),
            PageTemplate(id="detail", pagesize=A4, frames=[portrait_frame]),
        ]
    )

    story = [Paragraph(_pdf_text(title), title_style)]
    if len(rab_titles) == 1:
        story.append(Paragraph(_pdf_text(rab_titles[0]), subtitle_style))
    elif rab_titles:
        story.extend(
            [
                Paragraph("RAB:", title_list_label_style),
                ListFlowable(
                    [ListItem(Paragraph(_pdf_text(rab_title), title_list_style)) for rab_title in rab_titles],
                    bulletType="bullet",
                    leftIndent=16,
                    bulletFontName="Helvetica",
                    bulletFontSize=7,
                    spaceAfter=5,
                ),
            ]
        )
    story.extend(
        [
            Paragraph(
                "Prosentase NAC berasal dari aturan transaksi tepercaya. Confidence menunjukkan keyakinan klasifikasi dan tidak membuat prosentase baru.",
                body_style,
            ),
            Spacer(1, 5 * mm),
        ]
    )
    headers = ["Source", "Item / Uraian", "Type of Transaction", "NAC", "Confidence", "Status / Keputusan"]
    data = [[Paragraph(_pdf_text(header), table_header_style) for header in headers]]
    display_rows = rows or [{}]
    for row in display_rows:
        data.append(
            [
                Paragraph(_pdf_text(row.get("source_coordinate") or row.get("row_id") or "-"), small_style),
                Paragraph(_pdf_text(row.get("item_per_rab") or "Tidak ada data"), small_style),
                Paragraph(_pdf_text(row.get("selected_transaction_type") or "-"), small_style),
                Paragraph(_pdf_text(_percentage_label(row.get("applied_nac_percentage")) or "-"), small_style),
                Paragraph(_pdf_text(f"{_number(row.get('final_confidence')):.1f}% {row.get('confidence_label') or ''}"), small_style),
                Paragraph(_pdf_text(row.get("percentage_status") or row.get("decision_reason") or "-"), small_style),
            ]
        )
    summary_table = Table(
        data,
        colWidths=[20 * mm, 72 * mm, 48 * mm, 16 * mm, 26 * mm, 83 * mm],
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#246B61")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7DEDC")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7F6")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(summary_table)
    story.extend([NextPageTemplate("detail"), PageBreak(), Paragraph("Appendix Audit Per Item", title_style)])
    for index, row in enumerate(rows, start=1):
        source = row.get("source_id") or row.get("row_id") or index
        story.append(Paragraph(_pdf_text(f"{index}. {row.get('item_per_rab') or '-'}"), section_style))
        detail_data = [
            [Paragraph("Source ID", label_style), Paragraph(_pdf_text(source), body_style)],
            [Paragraph("Lokasi", label_style), Paragraph(_pdf_text(f"{row.get('source_file') or '-'} | {row.get('page_or_sheet') or '-'} | {row.get('source_coordinate') or '-'}"), body_style)],
            [Paragraph("Konteks", label_style), Paragraph(_pdf_text(f"Judul: {row.get('judul_rab') or '-'}\nSection: {row.get('section') or '-'}"), body_style)],
            [Paragraph("Transaksi", label_style), Paragraph(_pdf_text(f"{row.get('selected_transaction_type') or '-'} | NAC: {_percentage_label(row.get('applied_nac_percentage')) or '-'} | {row.get('percentage_status') or '-'}"), body_style)],
            [Paragraph("Confidence", label_style), Paragraph(_pdf_text(f"Deterministic {_number(row.get('deterministic_confidence') or row.get('final_confidence')):.1f}% | AI {_number(row.get('ai_confidence')):.1f}% | {row.get('confidence_label') or '-'}"), body_style)],
            [Paragraph("Bukti", label_style), Paragraph(_pdf_text(_context_audit(row)), body_style)],
            [Paragraph("Keputusan", label_style), Paragraph(_pdf_text(row.get("decision_reason") or "-"), body_style)],
            [Paragraph("Alasan lengkap", label_style), Paragraph(_pdf_text(row.get("explanation") or "-"), body_style)],
            [Paragraph("AI audit", label_style), Paragraph(_pdf_text(_provider_audit(row)), body_style)],
            [Paragraph("Parser", label_style), Paragraph(_pdf_text(_parser_audit(row)), body_style)],
        ]
        detail_table = Table(detail_data, colWidths=[31 * mm, 149 * mm], splitByRow=1, splitInRow=1)
        detail_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#D7DEDC")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F0F4F3")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.extend([detail_table, Spacer(1, 5 * mm)])
    document.build(story, canvasmaker=lambda *args, **kwargs: _NumberedCanvas(*args, generated=generated, **kwargs))


class _NumberedCanvas:
    def __new__(cls, *args, **kwargs):
        from reportlab.pdfgen.canvas import Canvas

        generated = kwargs.pop("generated", "")

        class NumberedCanvas(Canvas):
            def __init__(self, *canvas_args, **canvas_kwargs):
                Canvas.__init__(self, *canvas_args, **canvas_kwargs)
                self._saved_page_states = []

            def showPage(self):
                self._saved_page_states.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                page_count = len(self._saved_page_states)
                for state in self._saved_page_states:
                    self.__dict__.update(state)
                    self.setFont("Helvetica", 7)
                    self.setFillColorRGB(0.35, 0.40, 0.41)
                    self.drawString(34, 18, f"Internal Review Draft | {generated}")
                    self.drawRightString(self._pagesize[0] - 34, 18, f"Page {self._pageNumber} of {page_count}")
                    Canvas.showPage(self)
                Canvas.save(self)

        return NumberedCanvas(*args, **kwargs)


def _select_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = ""
    return result[columns]


def _serializable_text(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{key}={item}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(item) for item in value)
    return str(value or "")


def _unique_rab_titles(rows: list[dict[str, Any]]) -> list[str]:
    titles = []
    seen = set()
    for row in rows:
        value = row.get("judul_rab")
        try:
            if value is None or pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        title = " ".join(str(value).split())
        key = title.casefold()
        if title and key not in seen:
            seen.add(key)
            titles.append(title)
    return titles


def _pdf_metadata_title(report_title: str, rab_titles: list[str]) -> str:
    if len(rab_titles) == 1:
        combined = f"{report_title} - {rab_titles[0]}"
        return combined if len(combined) <= 240 else combined[:237].rstrip() + "..."
    if rab_titles:
        return f"{report_title} - {len(rab_titles)} judul RAB"
    return report_title


def _context_audit(row: dict[str, Any]) -> str:
    evidence = []
    for label, keyword_key, score_key in [
        ("Judul", "title_match_keyword", "title_match_score"),
        ("Subjudul", "section_match_keyword", "section_match_score"),
        ("Item", "item_match_keyword", "item_match_score"),
    ]:
        keyword = str(row.get(keyword_key) or "").strip()
        if keyword:
            evidence.append(f"{label}: {keyword} ({_number(row.get(score_key)):.1f})")
    consistency = _number(row.get("context_consistency_score"))
    if consistency:
        evidence.append(f"Konsistensi: {consistency:.1f}%")
    return "; ".join(evidence) or "-"


def _provider_audit(row: dict[str, Any]) -> str:
    return (
        f"Engine: {row.get('engine') or 'Python Lokal'}; model: {row.get('provider_model') or '-'}; "
        f"decision source: {row.get('decision_source') or '-'}; selected: {row.get('ai_selected_candidate_id') or '-'}; "
        f"reason: {row.get('ai_reason') or row.get('provider_error') or '-'}"
    )


def _parser_audit(row: dict[str, Any]) -> str:
    return (
        f"Strategy: {row.get('parser_strategy') or '-'}; confidence: {_number(row.get('parser_confidence')):.1f}%; "
        f"provenance: {_serializable_text(row.get('provenance'))}; warning: {_serializable_text(row.get('parser_warnings')) or '-'}"
    )


def _pdf_text(value: Any) -> str:
    return html.escape(str(value if value not in (None, "") else "-")).replace("\n", "<br/>")


def _percentage_label(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    return f"{int(number)}%" if number.is_integer() else f"{number:.2f}%"


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _xlsx_path(prefix: str) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORT_DIR / f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.xlsx"


def _pdf_path(prefix: str) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORT_DIR / f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.pdf"
