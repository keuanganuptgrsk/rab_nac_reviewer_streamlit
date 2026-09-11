from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from modules.pdf_loader import parse_pdf_document


def _multipage_rab_pdf(path):
    styles = getSampleStyleSheet()
    story = [Paragraph("RAB RENOVASI RUANG FINANCE", styles["Title"]), Spacer(1, 12)]
    rows = [["No", "Uraian Pekerjaan", "Satuan", "Volume", "Harga Satuan", "Total"]]
    rows.extend(
        [str(index), f"Item pekerjaan nomor {index}", "ls", "2", "1.250.000", "2.500.000"]
        for index in range(1, 46)
    )
    table = Table(rows, colWidths=[30, 230, 50, 50, 80, 80], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([table, Spacer(1, 16), Paragraph("Disusun dan disetujui", styles["BodyText"])])
    SimpleDocTemplate(str(path), pagesize=A4).build(story)
    return path


def test_pdf_coordinate_table_parser_handles_continuation_pages(tmp_path):
    document = parse_pdf_document(_multipage_rab_pdf(tmp_path / "rab-multipage.pdf"))

    assert document.parser_strategy == "pdf_coordinate_tables"
    assert document.review_blocked is False
    assert len(document.items) == 45
    assert len({item.source_id for item in document.items}) == 45
    assert {item.page_or_sheet for item in document.items} == {"Page 1", "Page 2"}
    first = document.items[0]
    assert first.judul_rab == "RAB RENOVASI RUANG FINANCE"
    assert (first.unit, first.volume, first.unit_price, first.total_price) == ("ls", 2, 1250000, 2500000)
    assert first.source_id.endswith("PDF!page1:table1:row2")
    assert "table_bbox" in first.raw_values
