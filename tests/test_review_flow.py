from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd


def load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("RAB_NAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAB_NAC_DB_PATH", str(tmp_path / "data" / "app.db"))
    monkeypatch.setenv("RAB_NAC_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("RAB_NAC_UPLOAD_DIR", str(tmp_path / "uploads"))

    import modules.db as db
    import modules.export_engine as export_engine
    import modules.feedback_actions as feedback_actions
    import modules.nac_detector as nac_detector
    import modules.review_flow as review_flow

    importlib.reload(db)
    importlib.reload(export_engine)
    importlib.reload(nac_detector)
    importlib.reload(review_flow)
    importlib.reload(feedback_actions)
    db.init_db()
    return db, review_flow, feedback_actions, export_engine


def test_excel_upload_and_detects_konsumsi(monkeypatch, tmp_path):
    _, review_flow, _, _ = load_modules(monkeypatch, tmp_path)
    workbook = tmp_path / "sample.xlsx"
    pd.DataFrame(
        {
            "uraian": ["Biaya konsumsi rapat koordinasi", "Material konstruksi panel"],
            "volume": [1, 2],
            "satuan": ["paket", "unit"],
            "total": [250000, 1200000],
        }
    ).to_excel(workbook, index=False)

    loaded = review_flow.load_uploaded_path(workbook)
    mapping = review_flow.default_mapping(loaded["state"])
    results, message = review_flow.run_review(
        loaded["state"],
        mapping["text_columns"],
        mapping["volume_col"],
        mapping["unit_col"],
        mapping["unit_price_col"],
        mapping["total_price_col"],
    )

    assert "Review selesai" in message
    assert len(results) == 2
    assert results[0]["matched_keyword"] in {"konsumsi", "konsumsi rapat"}
    assert results[0]["confidence_label"] in {"Sedang", "Tinggi", "Sangat tinggi"}


def test_settings_mapping():
    from modules.review_flow import settings_for_mode

    assert settings_for_mode("Ketat", "Nonaktif", "auto")["fuzzy_threshold"] == "86"
    assert settings_for_mode("Seimbang", "Aktif", "auto")["enable_semantic"] == "true"
    assert settings_for_mode("Lebih sensitif", "Nonaktif", "disabled")["semantic_threshold"] == "52"


def test_keyword_and_feedback_actions(monkeypatch, tmp_path):
    db, _, actions, _ = load_modules(monkeypatch, tmp_path)
    msg = actions.add_keyword_simple("biaya representasi khusus")
    assert "ditambahkan" in msg
    assert db.get_keyword_by_text("biaya representasi khusus")

    results = [
        {
            "row_id": "1",
            "original_text": "Biaya konsumsi rapat koordinasi",
            "matched_keyword": "konsumsi",
            "item_per_rab": "Biaya konsumsi rapat koordinasi",
        }
    ]
    saved = actions.save_row_feedback(results, "1 | Biaya konsumsi rapat koordinasi", "Correct NAC", "", "valid")
    assert "tersimpan" in saved
    assert len(db.get_feedback()) == 1


def test_exports_create_files(monkeypatch, tmp_path):
    _, _, _, export_engine = load_modules(monkeypatch, tmp_path)
    results = [
        {
            "row_id": "1",
            "item_per_rab": "Biaya konsumsi rapat koordinasi",
            "matched_category": "Rapat/Jamuan",
            "final_confidence": 62.5,
            "confidence_label": "Sedang",
            "redaction_suggestion": "Perjelas dasar kegiatan.",
            "recommended_action": "Perlu Review Manual",
        }
    ]

    excel_path = Path(export_engine.export_all_materials_excel(results))
    pdf_path = Path(export_engine.export_potential_nac_pdf(results))

    assert excel_path.exists()
    assert excel_path.suffix == ".xlsx"
    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
