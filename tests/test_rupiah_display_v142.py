from __future__ import annotations

import numpy as np
import pandas as pd

from modules.ui_system import format_rupiah, rupiah_display_styler


def test_format_rupiah_uses_indonesian_finance_notation():
    assert format_rupiah(2136100) == "Rp 2.136.100"
    assert format_rupiah(27900) == "Rp 27.900"
    assert format_rupiah(474300) == "Rp 474.300"
    assert format_rupiah(4495248) == "Rp 4.495.248"
    assert format_rupiah(13056800) == "Rp 13.056.800"
    assert format_rupiah(0) == "Rp 0"
    assert format_rupiah(-1250000) == "Rp -1.250.000"
    assert format_rupiah(1234.5) == "Rp 1.234,50"


def test_format_rupiah_supports_numeric_strings_and_numpy_scalars():
    assert format_rupiah("2136100") == "Rp 2.136.100"
    assert format_rupiah("1234,50") == "Rp 1.234,50"
    assert format_rupiah(np.int64(5914368)) == "Rp 5.914.368"
    assert format_rupiah(np.float64(8820000.0)) == "Rp 8.820.000"


def test_format_rupiah_returns_dash_for_missing_or_invalid_values():
    assert format_rupiah(None) == "-"
    assert format_rupiah(float("nan")) == "-"
    assert format_rupiah(pd.NA) == "-"
    assert format_rupiah("") == "-"
    assert format_rupiah("bukan angka") == "-"
    assert format_rupiah(True) == "-"


def test_rupiah_styler_uses_a_numeric_copy_and_preserves_source_frame():
    source = pd.DataFrame(
        {
            "Item / Uraian": ["Mobilisasi"],
            "Volume": [1.0],
            "Harga Satuan": [2136100],
            "Total": [2136100],
        }
    )
    original = source.copy(deep=True)

    display = rupiah_display_styler(source)

    pd.testing.assert_frame_equal(source, original)
    assert display.data is not source
    assert display.data.loc[0, "Harga Satuan"] == 2136100
    assert display.data.loc[0, "Total"] == 2136100
    assert pd.api.types.is_numeric_dtype(display.data["Harga Satuan"])
    assert pd.api.types.is_numeric_dtype(display.data["Total"])
    assert format_rupiah(display.data.loc[0, "Harga Satuan"]) == "Rp 2.136.100"
    assert format_rupiah(display.data.loc[0, "Total"]) == "Rp 2.136.100"


def test_rupiah_styler_ignores_absent_columns_without_mutating_data():
    source = pd.DataFrame({"Volume": [6.25], "Nilai non-rupiah": [80]})

    display = rupiah_display_styler(source, ("Harga Satuan", "Total"))

    pd.testing.assert_frame_equal(display.data, source)


def test_review_page_still_renders_without_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("RAB_NAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAB_NAC_DB_PATH", str(tmp_path / "data" / "app.db"))
    monkeypatch.setenv("RAB_NAC_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("RAB_NAC_UPLOAD_DIR", str(tmp_path / "uploads"))

    from streamlit.testing.v1 import AppTest

    script = """
from modules import db
from modules import ui_system as ui
from streamlit_app import init_session, review_page
ui.apply_page_config()
db.init_db()
init_session()
ui.inject_css()
review_page()
"""
    app = AppTest.from_string(script, default_timeout=20).run()

    assert not app.exception
