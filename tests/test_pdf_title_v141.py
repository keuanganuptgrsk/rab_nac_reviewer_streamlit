from __future__ import annotations

import importlib
from copy import deepcopy
from pathlib import Path

import fitz


REPORT_TITLE = "Ringkasan Potensi NAC Perlu Review"
DISCLAIMER_START = "Prosentase NAC berasal dari aturan transaksi tepercaya."
RAB_TITLE = 'Implementasi Budaya Perusahaan "IBU CERMAT" UPT Gresik'
SUMMARY_HEADERS = [
    "Source",
    "Item / Uraian",
    "Type of Transaction",
    "NAC",
    "Confidence",
    "Status / Keputusan",
]


def _load_export_engine(monkeypatch, tmp_path):
    monkeypatch.setenv("RAB_NAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAB_NAC_DB_PATH", str(tmp_path / "data" / "app.db"))
    monkeypatch.setenv("RAB_NAC_EXPORT_DIR", str(tmp_path / "exports"))
    import modules.db as db
    import modules.export_engine as export_engine

    importlib.reload(db)
    importlib.reload(export_engine)
    db.init_db()
    return export_engine


def _result(title=RAB_TITLE, index=1):
    return {
        "source_id": f"hash:RAB!B{index + 12}",
        "row_id": str(index),
        "source_file": "Workbook3.xlsx",
        "page_or_sheet": "Sheet1",
        "source_coordinate": f"B{index + 12}",
        "judul_rab": title,
        "section": "Penguatan Budaya Perusahaan",
        "item_per_rab": f"Material kegiatan {index}",
        "selected_transaction_type": "Kegiatan Event",
        "applied_nac_percentage": 100,
        "percentage_status": "Diterapkan dari transaksi terpilih",
        "final_confidence": 72,
        "deterministic_confidence": 72,
        "confidence_label": "Tinggi",
        "recommended_action": "Perlu Review Manual",
        "decision_reason": "Kandidat didukung redaksi item.",
        "explanation": "Kandidat didukung redaksi item dan konteks RAB.",
        "engine": "Python Lokal",
        "provider_model": "deterministic-nac-engine",
        "parser_strategy": "adaptive_xlsx",
        "parser_confidence": 93,
        "provenance": {"total_price": "source"},
    }


def _page_span_colors(page):
    colors = {}
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if text:
                    colors.setdefault(text, []).append(span.get("color"))
    return colors


def test_pdf_subtitle_order_metadata_and_white_summary_headers(monkeypatch, tmp_path):
    export_engine = _load_export_engine(monkeypatch, tmp_path)
    path = Path(export_engine.export_potential_nac_pdf([_result()]))

    with fitz.open(path) as document:
        page = document[0]
        text = page.get_text()
        assert REPORT_TITLE in text
        assert RAB_TITLE in text
        assert text.index(REPORT_TITLE) < text.index(RAB_TITLE) < text.index(DISCLAIMER_START)
        assert document.metadata["title"] == f"{REPORT_TITLE} - {RAB_TITLE}"

        colors = _page_span_colors(page)
        for header in SUMMARY_HEADERS:
            assert header in colors
            assert set(colors[header]) == {0xFFFFFF}


def test_duplicate_title_is_printed_once_and_all_materials_uses_subtitle(monkeypatch, tmp_path):
    export_engine = _load_export_engine(monkeypatch, tmp_path)
    first = _result(index=1)
    duplicate = deepcopy(first)
    duplicate.update(
        {
            "source_id": "hash:RAB!B14",
            "row_id": "2",
            "source_coordinate": "B14",
            "judul_rab": "  implementasi   budaya perusahaan \"ibu cermat\" upt gresik  ",
        }
    )
    path = Path(export_engine.export_all_materials_pdf([first, duplicate]))

    with fitz.open(path) as document:
        first_page_text = document[0].get_text()
        assert first_page_text.count(RAB_TITLE) == 1
        assert document.metadata["title"] == f"Tabel Seluruh Material RAB - {RAB_TITLE}"


def test_all_unique_titles_flow_before_appendix(monkeypatch, tmp_path):
    export_engine = _load_export_engine(monkeypatch, tmp_path)
    titles = [f"RAB Pekerjaan Area {index:02d}" for index in range(1, 41)]
    rows = [_result(title=title, index=index) for index, title in enumerate(titles, start=1)]
    path = Path(export_engine.export_potential_nac_pdf(rows))

    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
        appendix_page = next(index for index, text in enumerate(pages) if "Appendix Audit Per Item" in text)
        summary_text = "\n".join(pages[:appendix_page])
        assert "RAB:" in summary_text
        assert all(title in summary_text for title in titles)
        assert document.metadata["title"] == f"{REPORT_TITLE} - 40 judul RAB"


def test_missing_title_is_omitted_without_crashing(monkeypatch, tmp_path):
    export_engine = _load_export_engine(monkeypatch, tmp_path)
    rows = [_result(title="", index=1), _result(title=None, index=2), _result(title=float("nan"), index=3)]
    path = Path(export_engine.export_potential_nac_pdf(rows))

    with fitz.open(path) as document:
        first_page_text = document[0].get_text()
        assert "RAB:" not in first_page_text
        assert first_page_text.index(REPORT_TITLE) < first_page_text.index(DISCLAIMER_START)
        assert document.metadata["title"] == REPORT_TITLE
