from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
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
    assert results[0]["matched_keyword"] in {"Bahan Makanan dan Konsumsi", "Rapat Koordinasi Penyediaan Tenaga Listrik Proporsi Konsumsi"}
    assert results[0]["transaction_type"]
    assert results[0]["correction_percentage_label"]
    assert results[0]["confidence_label"] in {"Sedang", "Tinggi", "Sangat tinggi"}


def test_nac_2026_seed_pack_replaces_demo_keywords(monkeypatch, tmp_path):
    db, _, _, _ = load_modules(monkeypatch, tmp_path)
    keywords = db.get_keywords(False)

    assert keywords
    assert not [row for row in keywords if str(row.get("reference") or "").startswith("DEMO")]
    assert "Kategori A - PMK Non BPP" in {row["category"] for row in keywords}
    assert "Kategori B - Koreksi BPP" in {row["category"] for row in keywords}
    assert all(row.get("transaction_type") for row in keywords)
    assert all(row.get("correction_percentage") not in (None, "") for row in keywords)


def test_nac_2026_detection_metadata(monkeypatch, tmp_path):
    _, review_flow, _, _ = load_modules(monkeypatch, tmp_path)

    samples = {
        "beban pajak penghasilan pasal 21 pegawai": 100,
        "bahan makanan dan konsumsi": 100,
        "penyusutan aset tetap dari hibah": 100,
        "sewa kendaraan operasional": 29,
        "management building CS satpam taman": 10,
        "SPPD non diklat": 21,
        "renovasi ruang kerja": 20,
    }

    for text, expected_percentage in samples.items():
        result = review_flow.analyze_redaction(text)
        assert result is not None
        assert result["matched_keyword"]
        assert int(float(result["correction_percentage"])) == expected_percentage
        assert result["transaction_type"]


def test_allowable_exceptions_reduce_false_positive(monkeypatch, tmp_path):
    _, review_flow, _, _ = load_modules(monkeypatch, tmp_path)

    result = review_flow.analyze_redaction("konsumsi bahan bakar genset")

    assert result is not None
    assert result["allowable_score"] >= 60
    assert result["confidence_label"] in {"Sangat rendah", "Rendah"}
    assert "Exception cocok" in result["explanation"]


def test_settings_mapping():
    from modules.review_flow import settings_for_mode

    assert settings_for_mode("Ketat", "Nonaktif", "auto")["fuzzy_threshold"] == "86"
    assert settings_for_mode("Seimbang", "Aktif", "auto")["enable_semantic"] == "true"
    assert settings_for_mode("Lebih sensitif", "Nonaktif", "disabled")["semantic_threshold"] == "62"


def test_ocr_runtime_detects_local_tesseract(monkeypatch):
    import modules.ocr_engine as ocr_engine

    monkeypatch.setattr(ocr_engine, "_module_available", lambda name: name in {"pytesseract", "PIL"})
    monkeypatch.setattr(
        ocr_engine.shutil,
        "which",
        lambda executable: "C:/Program Files/Tesseract-OCR/tesseract.exe" if executable == "tesseract" else None,
    )

    status = ocr_engine.ocr_runtime_status()

    assert status["available"] is True
    assert status["available_engines"] == ["tesseract"]
    assert "OCR tersedia" in status["message"]


def test_ocr_runtime_unavailable_returns_cloud_safe_message(monkeypatch, tmp_path):
    import modules.ocr_engine as ocr_engine

    monkeypatch.setattr(ocr_engine, "_module_available", lambda name: False)
    monkeypatch.setattr(ocr_engine.shutil, "which", lambda executable: None)

    status = ocr_engine.ocr_runtime_status()
    text, message = ocr_engine.extract_text_from_image(tmp_path / "scan.png", "auto")

    assert status["available"] is False
    assert status["available_engines"] == []
    assert text == ""
    assert "tidak tersedia pada hosting ini" in message
    assert "Excel, CSV, atau PDF berbasis teks" in message


def test_ocr_auto_uses_available_engine(monkeypatch, tmp_path):
    import modules.ocr_engine as ocr_engine

    monkeypatch.setattr(
        ocr_engine,
        "ocr_runtime_status",
        lambda: {
            "available": True,
            "available_engines": ["tesseract"],
            "tesseract_binary": "tesseract",
            "message": "OCR tersedia pada runtime ini: tesseract.",
        },
    )
    monkeypatch.setattr(ocr_engine, "_tesseract_text", lambda path: "Biaya konsumsi rapat koordinasi")

    text, message = ocr_engine.extract_text_from_image(tmp_path / "scan.png", "auto")

    assert text == "Biaya konsumsi rapat koordinasi"
    assert message == "OCR berhasil menggunakan tesseract."


def test_digital_pdf_does_not_require_ocr(monkeypatch, tmp_path):
    _, review_flow, _, _ = load_modules(monkeypatch, tmp_path)
    import fitz
    import modules.ocr_engine as ocr_engine

    monkeypatch.setattr(
        ocr_engine,
        "ocr_runtime_status",
        lambda: {"available": False, "available_engines": [], "tesseract_binary": "", "message": "OCR tidak tersedia."},
    )
    pdf_path = tmp_path / "digital.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Biaya konsumsi rapat koordinasi untuk pelaksanaan pekerjaan kantor")
        document.save(pdf_path)

    loaded = review_flow.load_uploaded_path(pdf_path)

    assert loaded["state"]["source_quality"] == "digital_pdf"
    assert loaded["state"]["data"]
    assert "Berhasil ekstrak teks" in loaded["message"]


def fake_semantic_embeddings(texts, model_name="fake-e5", *, kind="passage"):
    vectors = []
    for text in texts:
        value = str(text or "").lower()
        vector = np.zeros(5, dtype=float)
        if any(token in value for token in ["hidangan", "makanan", "makan", "catering", "katering"]):
            vector[0] = 1.0
        if "konsumsi" in value:
            vector[4] = 0.7
        if any(token in value for token in ["publikasi", "running text", "iklan", "banner", "spanduk", "brosur"]):
            vector[1] = 1.0
        if any(token in value for token in ["alihdaya", "satpam", "taman", "management building", "gedung"]):
            vector[2] = 1.0
        if any(token in value for token in ["transmisi", "jaringan", "gardu"]):
            vector[3] = 1.0
        if vector.sum() == 0:
            vector[4] = 1.0
        vectors.append(vector)
    return np.asarray(vectors)


def test_semantic_indonesia_with_mock_embeddings(monkeypatch, tmp_path):
    db, review_flow, _, _ = load_modules(monkeypatch, tmp_path)

    import modules.vector_indexer as vector_indexer

    monkeypatch.setattr(vector_indexer, "embed_texts", fake_semantic_embeddings)
    db.save_setting("enable_semantic", "true")
    db.save_setting("embedding_model", "fake-e5")
    db.save_setting("semantic_threshold", "70")

    samples = {
        "hidangan peserta rapat": "Bahan Makanan dan Konsumsi",
        "publikasi running text kantor": "Iklan Brosur Spanduk Publikasi Banner",
        "alihdaya gedung satpam taman": "Management Building Gedung CS Satpam Taman",
    }
    for text, expected_keyword in samples.items():
        result = review_flow.analyze_redaction(text)
        assert result["matched_keyword"] == expected_keyword
        assert result["match_type"] in {"semantic", "synonym"}
        assert result["semantic_score"] >= 70
        assert result["semantic_candidate_text"] == expected_keyword
        assert result["semantic_model"] == "fake-e5"
        assert result["confidence_label"] in {"Sedang", "Tinggi", "Sangat tinggi"}


def test_semantic_does_not_override_allowable_or_low_signal(monkeypatch, tmp_path):
    db, review_flow, _, _ = load_modules(monkeypatch, tmp_path)

    import modules.vector_indexer as vector_indexer

    monkeypatch.setattr(vector_indexer, "embed_texts", fake_semantic_embeddings)
    db.save_setting("enable_semantic", "true")
    db.save_setting("embedding_model", "fake-e5")
    db.save_setting("semantic_threshold", "70")

    technical = review_flow.analyze_redaction("perbaikan jaringan transmisi")
    assert technical["match_type"] != "semantic"
    assert technical["confidence_label"] in {"Sangat rendah", "Rendah"}

    fuel = review_flow.analyze_redaction("konsumsi bahan bakar genset")
    assert fuel["allowable_score"] >= 60
    assert fuel["confidence_label"] in {"Sangat rendah", "Rendah"}


def test_semantic_index_signature_and_clear_cache(monkeypatch, tmp_path):
    db, _, _, _ = load_modules(monkeypatch, tmp_path)

    import modules.vector_indexer as vector_indexer

    monkeypatch.setattr(vector_indexer, "embed_texts", fake_semantic_embeddings)
    before = vector_indexer.semantic_index_signature(db.get_keywords(True), "fake-e5", db.get_synonyms(True), db.get_feedback())
    new_id = db.add_keyword("Audit", "keyword semantic signature", "", "", "medium", "active", "")
    db.add_synonym(new_id, "alias signature")
    after_add = vector_indexer.semantic_index_signature(db.get_keywords(True), "fake-e5", db.get_synonyms(True), db.get_feedback())
    assert before != after_add

    db.update_keyword_status(new_id, "inactive")
    after_inactive = vector_indexer.semantic_index_signature(db.get_keywords(True), "fake-e5", db.get_synonyms(True), db.get_feedback())
    assert after_add != after_inactive

    vector_indexer.clear_semantic_cache()
    assert vector_indexer.runtime_status("fake-e5")["cached_index_count"] == 0


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


def test_bulk_keyword_lifecycle_keeps_feedback(monkeypatch, tmp_path):
    db, _, actions, _ = load_modules(monkeypatch, tmp_path)
    first_id = db.add_keyword("Audit", "keyword bulk satu", "", "", "medium", "active", "")
    second_id = db.add_keyword("Audit", "keyword bulk dua", "", "", "medium", "active", "")
    db.add_synonym(first_id, "bulk alias")
    db.add_exception(first_id, "bulk pattern", "test", "lower_confidence", 25)
    db.save_feedback("1", "keyword bulk satu", "keyword bulk satu", "Correct NAC", "", "history")

    deactivated = actions.bulk_deactivate_keywords([first_id, second_id])
    assert "2 keyword dinonaktifkan" in deactivated
    statuses = {row["keyword"]: row["status"] for row in db.get_keywords(False) if row["keyword"].startswith("keyword bulk")}
    assert statuses == {"keyword bulk satu": "inactive", "keyword bulk dua": "inactive"}

    restored = actions.bulk_restore_keywords([first_id])
    assert "1 keyword direstore" in restored
    assert db.get_keyword_by_text("keyword bulk satu")["status"] == "active"

    deleted = actions.bulk_delete_keywords([first_id])
    assert "1 keyword dihapus permanen" in deleted
    assert db.get_keyword_by_text("keyword bulk satu") is None
    assert not [row for row in db.get_synonyms(False) if row.get("nac_keyword_id") == first_id]
    assert not [row for row in db.get_exceptions(False) if row.get("nac_keyword_id") == first_id]
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
    exported = pd.read_excel(excel_path)
    assert "Prosentase NAC" in exported.columns
    assert "Type of Transaction" in exported.columns


def test_streamlit_app_smoke_shows_release_copy(monkeypatch, tmp_path):
    monkeypatch.setenv("RAB_NAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAB_NAC_DB_PATH", str(tmp_path / "data" / "app.db"))
    monkeypatch.setenv("RAB_NAC_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("RAB_NAC_UPLOAD_DIR", str(tmp_path / "uploads"))

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("streamlit_app.py", default_timeout=20).run()
    assert not at.exception
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "Review potensi NAC dengan mudah~" in markdown_text


def test_streamlit_settings_shows_ocr_runtime_status(monkeypatch, tmp_path):
    monkeypatch.setenv("RAB_NAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAB_NAC_DB_PATH", str(tmp_path / "data" / "app.db"))
    monkeypatch.setenv("RAB_NAC_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("RAB_NAC_UPLOAD_DIR", str(tmp_path / "uploads"))

    from streamlit.testing.v1 import AppTest

    script = """
from modules import db
from modules import ui_system as ui
from streamlit_app import init_session, settings_page

ui.apply_page_config()
db.init_db()
init_session()
ui.inject_css()
settings_page()
"""
    at = AppTest.from_string(script, default_timeout=20).run()

    assert not at.exception
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "Status OCR Runtime" in markdown_text
    assert "OCR" in markdown_text


def test_hierarchical_context_uses_item_as_primary_evidence(monkeypatch, tmp_path):
    _, review_flow, _, _ = load_modules(monkeypatch, tmp_path)

    result = review_flow.analyze_redaction(
        "Kabel penghantar 150 mm",
        "Bahan Makanan dan Konsumsi",
        "Pemeliharaan jaringan transmisi",
    )

    assert result["title_match_keyword"] == "Bahan Makanan dan Konsumsi"
    assert result["item_match_score"] < 45
    assert result["final_confidence"] <= 44
    assert result["applied_nac_percentage"] == ""
    assert result["percentage_status"].startswith("Perlu penentuan reviewer")
    assert result["allowable_score"] >= 40


def test_consistent_hierarchy_increases_confidence_and_applies_rule(monkeypatch, tmp_path):
    _, review_flow, _, _ = load_modules(monkeypatch, tmp_path)

    item_only = review_flow.analyze_redaction("Sewa kendaraan operasional bulanan")
    contextual = review_flow.analyze_redaction(
        "Sewa kendaraan operasional bulanan",
        "Sewa kendaraan operasional unit",
        "Sewa kendaraan untuk kegiatan operasional",
    )

    assert contextual["selected_transaction_type"].startswith("Sewa Kendaraan")
    assert contextual["applied_nac_percentage"] == 29
    assert contextual["context_consistency_score"] == 100
    assert contextual["final_confidence"] > item_only["final_confidence"]
    assert contextual["percentage_status"] == "Diterapkan dari transaksi terpilih"


def test_production_percentages_are_rules_not_confidence(monkeypatch, tmp_path):
    _, review_flow, _, _ = load_modules(monkeypatch, tmp_path)
    samples = {
        "sewa kendaraan operasional": 29,
        "SPPD non diklat": 21,
        "management building CS satpam taman": 10,
        "renovasi ruang kerja": 20,
        "publikasi media running text": 80,
    }

    confidences = set()
    for text, percentage in samples.items():
        result = review_flow.analyze_redaction(text)
        assert result["applied_nac_percentage"] == percentage
        assert result["reference_percentage"] == percentage
        assert result["correction_percentage"] == percentage
        confidences.add(result["final_confidence"])

    assert len(confidences) > 1


def test_ambiguous_transactions_hold_percentage_for_reviewer(monkeypatch, tmp_path):
    db, review_flow, _, _ = load_modules(monkeypatch, tmp_path)
    first = db.add_keyword(
        "Audit",
        "Transaksi Campuran Alfa",
        severity="high",
        correction_percentage=20,
        transaction_type="Transaksi Alfa",
    )
    second = db.add_keyword(
        "Audit",
        "Transaksi Campuran Beta",
        severity="high",
        correction_percentage=80,
        transaction_type="Transaksi Beta",
    )
    db.add_synonym(first, "komponen campuran khusus", weight=0.95)
    db.add_synonym(second, "komponen campuran khusus", weight=0.95)

    result = review_flow.analyze_redaction("komponen campuran khusus")

    assert result["is_ambiguous"] is True
    assert result["applied_nac_percentage"] == ""
    assert result["correction_percentage_label"] == "Perlu penentuan reviewer"
    assert "Ambigu" in result["percentage_status"]
    assert result["alternative_transaction"]


def test_build_items_preserves_hierarchical_fields(monkeypatch, tmp_path):
    _, review_flow, _, _ = load_modules(monkeypatch, tmp_path)
    state = {
        "kind": "table",
        "path": str(tmp_path / "rab.xlsx"),
        "sheet": "RAB",
        "detected": {},
        "data": [
            {
                "row_id": "7",
                "judul_rab": "Pemeliharaan Gardu Induk",
                "section": "Material pekerjaan teknis",
                "item_per_rab": "Kabel kontrol 4 x 2.5 mm",
                "review_text": (
                    "Pemeliharaan Gardu Induk | Material pekerjaan teknis | Kabel kontrol 4 x 2.5 mm"
                ),
            }
        ],
    }

    items, _ = review_flow.build_items(state, ["review_text"])

    assert items[0]["judul_rab"] == "Pemeliharaan Gardu Induk"
    assert items[0]["section"] == "Material pekerjaan teknis"
    assert items[0]["item_per_rab"] == "Kabel kontrol 4 x 2.5 mm"
    assert "Pemeliharaan Gardu Induk" in items[0]["original_text"]


def test_context_audit_fields_reach_dataframes_and_exports(monkeypatch, tmp_path):
    _, review_flow, _, export_engine = load_modules(monkeypatch, tmp_path)
    result = review_flow.analyze_redaction(
        "Sewa kendaraan operasional bulanan",
        "Operasional Unit",
        "Transportasi pendukung",
    )
    required = {
        "title_match_keyword",
        "title_match_score",
        "section_match_keyword",
        "section_match_score",
        "item_match_keyword",
        "item_match_score",
        "context_consistency_score",
        "selected_transaction_type",
        "reference_percentage",
        "applied_nac_percentage",
        "percentage_source",
        "percentage_status",
        "alternative_transaction",
        "alternative_percentage",
        "decision_reason",
    }
    assert required.issubset(result)

    summary = review_flow.review_summary_dataframe([result])
    all_items = review_flow.all_materials_dataframe([result])
    for column in [
        "Prosentase Referensi",
        "Status Prosentase",
        "Konsistensi Konteks",
        "Match Judul",
        "Match Subjudul",
        "Match Item",
        "Alasan Keputusan",
    ]:
        assert column in summary.columns
        assert column in all_items.columns

    all_excel = Path(export_engine.export_all_materials_excel([result]))
    full_excel = Path(export_engine.export_review_excel([result]))
    exported = pd.read_excel(all_excel)
    findings = pd.read_excel(full_excel, sheet_name="Findings")
    assert "Status Prosentase" in exported.columns
    assert "Konsistensi Konteks %" in exported.columns
    assert "percentage_status" in findings.columns
    assert "decision_reason" in findings.columns
