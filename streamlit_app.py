from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from modules import db
from modules import feedback_actions as actions
from modules import review_flow
from modules import ui_system as ui
from modules.export_engine import export_all_materials_excel, export_all_materials_pdf, export_potential_nac_pdf
from modules.feedback_engine import learning_summary
from modules.version import APP_RELEASE_NOTES, APP_RELEASE_TITLE, APP_VERSION, version_banner


EXPORT_DIR = Path(__file__).resolve().parent / "exports"


def init_session() -> None:
    defaults = {
        "upload_signature": None,
        "upload_state": {},
        "upload_preview": pd.DataFrame(),
        "upload_message": "",
        "review_results": [],
        "review_message": "",
        "export_potential_pdf": "",
        "export_all_pdf": "",
        "export_all_excel": "",
        "keyword_export": "",
        "db_backup": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def current_metrics() -> dict:
    return review_flow.summary_metrics(st.session_state.get("review_results", []))


def select_or_blank(label: str, columns: list[str], value: str | None, key: str) -> str | None:
    options = [""] + list(columns)
    index = options.index(value) if value in options else 0
    selected = st.selectbox(label, options, index=index, key=key)
    return selected or None


def load_uploaded_file(uploaded_file) -> None:
    signature = (getattr(uploaded_file, "name", ""), getattr(uploaded_file, "size", None))
    if signature == st.session_state.get("upload_signature"):
        return
    path = review_flow.save_uploaded_file(uploaded_file)
    loaded = review_flow.load_uploaded_path(path)
    st.session_state.upload_signature = signature
    st.session_state.upload_state = loaded["state"]
    st.session_state.upload_preview = loaded["preview"]
    st.session_state.upload_message = loaded["message"]
    st.session_state.review_results = []
    st.session_state.review_message = ""
    for key in ["export_potential_pdf", "export_all_pdf", "export_all_excel"]:
        st.session_state[key] = ""


def review_page() -> None:
    ui.hero(APP_VERSION, APP_RELEASE_TITLE, APP_RELEASE_NOTES, current_metrics())
    st.markdown(
        "Upload Excel/CSV untuk hasil paling presisi. PDF digital dan gambar/PDF scan tetap didukung melalui ekstraksi teks atau OCR best-effort."
    )

    uploaded = st.file_uploader(
        "Upload RAB",
        type=[ext.lstrip(".") for ext in review_flow.SUPPORTED_EXTENSIONS],
        help="Format: xlsx, xls, csv, pdf, png, jpg, jpeg.",
        key="rab_file_uploader",
    )
    if uploaded is not None:
        with st.spinner("Membaca struktur file dan menyiapkan preview..."):
            load_uploaded_file(uploaded)

    upload_state = st.session_state.get("upload_state", {})
    if not upload_state:
        ui.empty_state("Belum ada file. Upload RAB untuk mulai review.")
        return

    ui.status_note(st.session_state.get("upload_message", "File siap direview."))

    preview = st.session_state.get("upload_preview", pd.DataFrame())
    if preview is not None and not preview.empty:
        with st.expander("Preview data terdeteksi", expanded=False):
            st.dataframe(preview, width="stretch", hide_index=True, height=ui.dataframe_height(preview, 180, 360))

    mapping = review_flow.default_mapping(upload_state)
    columns = list(upload_state.get("columns", []))
    if upload_state.get("kind") == "table":
        with st.expander("Mapping kolom", expanded=False):
            text_columns = st.multiselect(
                "Kolom teks untuk direview",
                columns,
                default=[col for col in mapping["text_columns"] if col in columns],
                help="Pilih kolom yang berisi uraian pekerjaan, item, material, atau catatan.",
            )
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                volume_col = select_or_blank("Volume", columns, mapping["volume_col"], "volume_col")
            with c2:
                unit_col = select_or_blank("Satuan", columns, mapping["unit_col"], "unit_col")
            with c3:
                unit_price_col = select_or_blank("Harga satuan", columns, mapping["unit_price_col"], "unit_price_col")
            with c4:
                total_price_col = select_or_blank("Total", columns, mapping["total_price_col"], "total_price_col")
    else:
        text_columns = mapping["text_columns"]
        volume_col = unit_col = unit_price_col = total_price_col = None

    run_clicked = st.button("Run NAC Review", type="primary", width="stretch")
    if run_clicked:
        try:
            with st.spinner("Memproses deteksi NAC..."):
                results, message = review_flow.run_review(
                    upload_state,
                    text_columns,
                    volume_col,
                    unit_col,
                    unit_price_col,
                    total_price_col,
                )
            st.session_state.review_results = results
            st.session_state.review_message = message
        except Exception as exc:
            st.session_state.review_results = []
            st.session_state.review_message = f"Review gagal diproses: {exc}"

    if st.session_state.get("review_message"):
        ui.status_note(st.session_state.review_message)

    results = st.session_state.get("review_results", [])
    if not results:
        ui.empty_state("Hasil review akan muncul setelah tombol Run NAC Review ditekan.")
        return

    metrics = review_flow.summary_metrics(results)
    ui.metric_grid(
        [
            ("Total item", metrics["total"]),
            ("Potensi NAC", metrics["potential"]),
            ("Prioritas tinggi", metrics["high"]),
            ("Manual review", metrics["manual"]),
        ]
    )

    ui.section_label("Temuan prioritas")
    category_options = ["Semua"] + sorted(
        {
            str(row.get("matched_category") or "-")
            for row in results
            if str(row.get("matched_category") or "").strip()
        }
    )
    f1, f2, f3 = st.columns([1.4, 1, 1])
    with f1:
        levels = st.multiselect(
            "Confidence level",
            ["Sedang", "Tinggi", "Sangat tinggi", "Rendah", "Sangat rendah"],
            default=["Sedang", "Tinggi", "Sangat tinggi"],
        )
    with f2:
        category = st.selectbox("Kategori", category_options)
    with f3:
        manual_only = st.toggle("Perlu review manual saja", value=False)
    query = st.text_input("Cari hasil", placeholder="Cari item, keyword, atau kategori")

    filtered = review_flow.filtered_results(results, levels, category, manual_only, query)
    findings = review_flow.review_summary_dataframe(filtered.to_dict("records") if not filtered.empty else [])
    st.dataframe(
        findings,
        width="stretch",
        hide_index=True,
        height=ui.dataframe_height(findings),
        column_config={
            "Confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100, format="%.1f%%"),
        },
    )

    with st.expander("Tabel seluruh item RAB", expanded=False):
        all_items = review_flow.all_materials_dataframe(results)
        st.dataframe(
            all_items,
            width="stretch",
            hide_index=True,
            height=ui.dataframe_height(all_items, 240, 620),
            column_config={
                "Confidence %": st.column_config.ProgressColumn("Confidence %", min_value=0, max_value=100, format="%.1f%%"),
            },
        )

    feedback_panel(results)
    export_panel(results)


def feedback_panel(results: list[dict]) -> None:
    ui.section_label("Feedback reviewer")
    row_options = review_flow.row_choices(results)
    with st.form("feedback_form"):
        c1, c2 = st.columns([1.4, 1])
        with c1:
            row_selection = st.selectbox("Row hasil review", row_options)
        with c2:
            feedback_type = st.selectbox(
                "Jenis feedback",
                ["Correct NAC", "Not NAC", "Confidence Too High", "Confidence Too Low", "Add as New NAC Keyword", "Add as Synonym"],
            )
        redaction = st.text_input("Redaksi atau sinonim yang disarankan", placeholder="Opsional")
        notes = st.text_area("Catatan reviewer", placeholder="Catatan audit internal", height=90)
        submitted = st.form_submit_button("Simpan Feedback", type="primary")
    if submitted:
        st.success(actions.save_row_feedback(results, row_selection, feedback_type, redaction, notes))

    synonym_rows = review_flow.row_choices(results, only_with_synonym=True)
    if synonym_rows:
        with st.expander("Approve suggested synonym dari hasil review", expanded=False):
            selected = st.selectbox("Kandidat sinonim", synonym_rows, key="synonym_candidate_row")
            weight = st.slider("Bobot sinonim", min_value=0.50, max_value=1.00, value=0.85, step=0.05)
            if st.button("Approve Suggested Synonym", type="primary"):
                st.success(actions.approve_suggested_synonym(results, selected, weight))


def export_panel(results: list[dict]) -> None:
    ui.section_label("Export hasil")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Buat PDF Potensi NAC", width="stretch"):
            st.session_state.export_potential_pdf = export_potential_nac_pdf(results)
        if st.session_state.get("export_potential_pdf"):
            data, name = ui.file_download(st.session_state.export_potential_pdf)
            st.download_button("Download PDF Potensi NAC", data, file_name=name, mime="application/pdf", width="stretch")
    with c2:
        if st.button("Buat PDF Seluruh Material", width="stretch"):
            st.session_state.export_all_pdf = export_all_materials_pdf(results)
        if st.session_state.get("export_all_pdf"):
            data, name = ui.file_download(st.session_state.export_all_pdf)
            st.download_button("Download PDF Seluruh Material", data, file_name=name, mime="application/pdf", width="stretch")
    with c3:
        if st.button("Buat Excel Seluruh Material", width="stretch"):
            st.session_state.export_all_excel = export_all_materials_excel(results)
        if st.session_state.get("export_all_excel"):
            data, name = ui.file_download(st.session_state.export_all_excel)
            st.download_button(
                "Download Excel Seluruh Material",
                data,
                file_name=name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )


def redaction_page() -> None:
    ui.hero(APP_VERSION, APP_RELEASE_TITLE, "Analisa satu kalimat redaksi RAB sebelum dimasukkan ke dokumen.", current_metrics())
    text = st.text_area(
        "Redaksi RAB",
        placeholder="Contoh: biaya konsumsi rapat koordinasi",
        height=130,
    )
    if not text.strip():
        ui.empty_state("Ketik satu kalimat redaksi untuk melihat potensi NAC, keyword, dan saran klarifikasi.")
        return

    result = review_flow.analyze_redaction(text)
    if not result:
        ui.empty_state("Belum ada hasil analisa.")
        return

    score = float(result.get("final_confidence", 0) or 0)
    label = result.get("confidence_label", "-")
    category = result.get("matched_category") or "Tidak ada kategori kuat"
    keyword = result.get("matched_keyword") or "-"
    st.markdown(
        f"""
<div class="hero-panel">
  <div class="hero-panel-title">Potensi NAC</div>
  <div class="hero-panel-number">{score:.1f}%</div>
  <div>{ui.confidence_pill(label)}</div>
  <div class="hero-panel-line"></div>
  <div class="hero-panel-copy"><strong>Kategori:</strong> {html.escape(category)}</div>
  <div class="hero-panel-copy"><strong>Keyword:</strong> {html.escape(keyword)}</div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.progress(min(max(score / 100, 0), 1))
    ui.status_note(result.get("explanation", ""))
    st.markdown("Saran klarifikasi")
    st.info(result.get("redaction_suggestion") or "Tidak ada saran khusus.")


def database_page() -> None:
    ui.hero(APP_VERSION, APP_RELEASE_TITLE, "Kelola keyword NAC, sinonim, allowable keyword, exception, backup, dan import data.", current_metrics())

    c1, c2 = st.columns([1.1, 1])
    with c1:
        with st.form("add_keyword_form"):
            keyword = st.text_input("Tambah keyword NAC", placeholder="Contoh: uang saku, honorarium, biaya representasi")
            submitted = st.form_submit_button("Tambah Keyword", type="primary")
        if submitted:
            st.success(actions.add_keyword_simple(keyword))

    with c2:
        import_file = st.file_uploader("Import Excel keyword", type=["xlsx"], key="keyword_import_file")
        if st.button("Import Keyword dari Excel", disabled=import_file is None):
            path = review_flow.save_uploaded_file(import_file)
            st.success(actions.import_keywords_file(path))
        if st.button("Buat Export Database Keyword"):
            EXPORT_DIR.mkdir(exist_ok=True)
            st.session_state.keyword_export = actions.export_keywords_file(
                EXPORT_DIR / f"keyword_database_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
            )
        if st.session_state.get("keyword_export"):
            data, name = ui.file_download(st.session_state.keyword_export)
            st.download_button(
                "Download Database Keyword",
                data,
                file_name=name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    ui.section_label("Daftar keyword aktif")
    search = st.text_input("Cari keyword atau kategori", placeholder="Contoh: konsumsi, transport, hadiah")
    keywords = pd.DataFrame(db.get_keywords(False))
    if not keywords.empty:
        keywords = keywords[keywords["status"].eq("active")]
        if search:
            mask = keywords.fillna("").astype(str).agg(" ".join, axis=1).str.lower().str.contains(search.lower(), na=False)
            keywords = keywords[mask]
        show_cols = ["id", "category", "keyword", "severity", "description", "reference", "notes"]
        st.dataframe(keywords[[col for col in show_cols if col in keywords.columns]], width="stretch", hide_index=True, height=ui.dataframe_height(keywords))
    else:
        ui.empty_state("Database keyword masih kosong.")

    with st.expander("Nonaktifkan keyword", expanded=False):
        selection = st.selectbox("Keyword", actions.keyword_choices(active_only=True))
        if st.button("Nonaktifkan Keyword"):
            st.warning(actions.delete_keyword(selection))

    with st.expander("Sinonim, allowable keyword, dan exception", expanded=False):
        tabs = st.tabs(["Sinonim", "Allowable", "Exception"])
        with tabs[0]:
            st.dataframe(pd.DataFrame(db.get_synonyms(False)), width="stretch", hide_index=True)
        with tabs[1]:
            st.dataframe(pd.DataFrame(db.get_allowable(False)), width="stretch", hide_index=True)
        with tabs[2]:
            st.dataframe(pd.DataFrame(db.get_exceptions(False)), width="stretch", hide_index=True)

    backup_restore_panel()


def backup_restore_panel() -> None:
    ui.section_label("Backup dan restore SQLite")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Buat Backup Database"):
            st.session_state.db_backup = db.backup_db()
        if st.session_state.get("db_backup"):
            data, name = ui.file_download(st.session_state.db_backup)
            st.download_button("Download Backup SQLite", data, file_name=name, mime="application/octet-stream")
    with b2:
        restore_file = st.file_uploader("Restore dari backup SQLite", type=["db", "sqlite", "sqlite3"], key="restore_db_file")
        if st.button("Restore Database", disabled=restore_file is None):
            path = review_flow.save_uploaded_file(restore_file)
            db.restore_db(path)
            st.success("Backup berhasil direstore. Refresh halaman bila data belum berubah.")


def learning_page() -> None:
    ui.hero(APP_VERSION, APP_RELEASE_TITLE, "Dashboard feedback untuk membaca pola false positive, false negative, sinonim, dan exception.", current_metrics())
    fp, fn, new_kw, syn, model_syn, exc, fb_hist = learning_summary()
    feedback_count = 0 if fb_hist is None or fb_hist.empty else len(fb_hist)
    ui.metric_grid(
        [
            ("Total feedback", feedback_count),
            ("False positive", int(fp["count"].sum()) if fp is not None and not fp.empty else 0),
            ("False negative", int(fn["count"].sum()) if fn is not None and not fn.empty else 0),
            ("Sinonim disarankan", int(syn["count"].sum()) if syn is not None and not syn.empty else 0),
        ]
    )
    tabs = st.tabs(["False Positive", "False Negative", "Keyword Baru", "Sinonim", "Model Synonym", "Exception", "Feedback Log"])
    frames = [fp, fn, new_kw, syn, model_syn, exc, fb_hist]
    for tab, frame in zip(tabs, frames):
        with tab:
            if frame is None or frame.empty:
                ui.empty_state("Belum ada data pada kategori ini.")
            else:
                st.dataframe(frame, width="stretch", hide_index=True, height=ui.dataframe_height(frame))


def settings_page() -> None:
    ui.hero(APP_VERSION, APP_RELEASE_TITLE, "Atur sensitivitas review, semantic matching, OCR, dan versioning aplikasi.", current_metrics())
    settings = db.get_settings()
    fuzzy = settings.get("fuzzy_threshold", "78")
    review_mode_default = {"86": "Ketat", "78": "Seimbang", "68": "Lebih sensitif"}.get(fuzzy, "Seimbang")
    semantic_available = review_flow.semantic_package_available()
    semantic_default = "Aktif" if settings.get("enable_semantic", "false") == "true" else "Nonaktif"
    ocr_default = "auto" if settings.get("ocr_mode", "auto") != "disabled" else "disabled"

    with st.form("settings_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            review_mode = st.radio("Mode Review", ["Ketat", "Seimbang", "Lebih sensitif"], index=["Ketat", "Seimbang", "Lebih sensitif"].index(review_mode_default))
        with c2:
            semantic_mode = st.radio("Deteksi Sinonim/Parafrasa Otomatis", ["Nonaktif", "Aktif"], index=["Nonaktif", "Aktif"].index(semantic_default))
        with c3:
            ocr_mode = st.radio("OCR PDF Scan/Gambar", ["auto", "disabled"], index=["auto", "disabled"].index(ocr_default))
        submitted = st.form_submit_button("Simpan Settings", type="primary")
    if submitted:
        st.success(review_flow.save_simple_settings(review_mode, semantic_mode, ocr_mode))
    if semantic_mode == "Aktif" and not semantic_available:
        st.warning("Paket sentence-transformers belum terpasang. Semantic matching akan fallback tanpa menghentikan review.")

    with st.expander("Versioning dan rollback", expanded=True):
        st.markdown(version_banner())
        st.markdown(
            """
Rilis ini memakai tag git `v1.0.0`. Untuk rollback lokal, gunakan tag tersebut dari GitHub atau jalankan `git checkout v1.0.0` pada salinan repo. Untuk Streamlit Cloud, deploy ulang branch atau tag yang ingin dipakai.
"""
        )

    with st.expander("Reset demo database", expanded=False):
        st.warning("Reset akan membuat ulang database demo dan menghapus perubahan SQLite lokal pada environment aktif.")
        if st.button("Reset demo database"):
            db.reset_demo_database()
            st.success("Demo database dibuat ulang.")


def main() -> None:
    ui.apply_page_config()
    db.init_db()
    init_session()
    ui.inject_css()
    pages = [
        st.Page(review_page, title="Review RAB"),
        st.Page(redaction_page, title="Analisa Redaksi"),
        st.Page(database_page, title="Database NAC"),
        st.Page(learning_page, title="Feedback & Learning"),
        st.Page(settings_page, title="Settings"),
    ]
    page = st.navigation(pages, position="top")
    page.run()


if __name__ == "__main__":
    main()
