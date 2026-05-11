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


def keyword_alias_map() -> dict[int, list[str]]:
    aliases: dict[int, list[str]] = {}
    for row in db.get_synonyms(False):
        keyword_id = row.get("nac_keyword_id")
        if keyword_id is None:
            continue
        aliases.setdefault(int(keyword_id), []).append(str(row.get("synonym") or ""))
    return aliases


def filter_keyword_rows(rows: list[dict], search: str = "", categories: list[str] | None = None, severities: list[str] | None = None, statuses: list[str] | None = None) -> list[dict]:
    search_l = str(search or "").strip().lower()
    categories = categories or []
    severities = severities or []
    statuses = statuses or []
    filtered = []
    for row in rows:
        if categories and row.get("category") not in categories:
            continue
        if severities and row.get("severity") not in severities:
            continue
        if statuses and row.get("status") not in statuses:
            continue
        haystack = " ".join(str(row.get(key) or "") for key in ["id", "category", "keyword", "severity", "description", "reference", "notes", "status"]).lower()
        if search_l and search_l not in haystack:
            continue
        filtered.append(row)
    return filtered


def keyword_editor_frame(rows: list[dict], aliases: dict[int, list[str]]) -> pd.DataFrame:
    records = []
    for row in rows:
        keyword_id = int(row.get("id"))
        synonym_text = ", ".join(alias for alias in aliases.get(keyword_id, []) if alias)
        records.append(
            {
                "Pilih": False,
                "ID": keyword_id,
                "Kategori": row.get("category", ""),
                "Keyword": row.get("keyword", ""),
                "Severity": row.get("severity", ""),
                "Sinonim": synonym_text,
                "Catatan": row.get("notes") or row.get("description", ""),
            }
        )
    return pd.DataFrame(records, columns=["Pilih", "ID", "Kategori", "Keyword", "Severity", "Sinonim", "Catatan"])


def selected_keyword_ids(frame: pd.DataFrame | None) -> list[int]:
    if frame is None or frame.empty or "Pilih" not in frame.columns:
        return []
    selected = frame[frame["Pilih"].fillna(False).astype(bool)]
    return [int(value) for value in selected["ID"].tolist()]


def keyword_editor(
    frame: pd.DataFrame,
    key: str,
    empty_message: str,
) -> pd.DataFrame:
    if frame.empty:
        ui.empty_state(empty_message)
        return frame
    return st.data_editor(
        frame,
        key=key,
        width="stretch",
        hide_index=True,
        height=ui.dataframe_height(frame, 260, 620),
        disabled=["ID", "Kategori", "Keyword", "Severity", "Sinonim", "Catatan"],
        column_config={
            "Pilih": st.column_config.CheckboxColumn("Pilih", help="Centang keyword untuk bulk action.", default=False),
            "ID": st.column_config.NumberColumn("ID", width="small"),
            "Kategori": st.column_config.TextColumn("Kategori", width="medium"),
            "Keyword": st.column_config.TextColumn("Keyword", width="medium"),
            "Severity": st.column_config.TextColumn("Severity", width="small"),
            "Sinonim": st.column_config.TextColumn("Sinonim", width="large"),
            "Catatan": st.column_config.TextColumn("Catatan", width="large"),
        },
    )


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

    ui.section_label("Kelola keyword NAC")
    all_keywords = db.get_keywords(False)
    aliases = keyword_alias_map()
    category_options = sorted({row.get("category") for row in all_keywords if row.get("category")})
    severity_options = sorted({row.get("severity") for row in all_keywords if row.get("severity")})
    status_options = sorted({row.get("status") for row in all_keywords if row.get("status")})

    f1, f2, f3, f4 = st.columns([1.4, 1, 1, 1])
    with f1:
        keyword_search = st.text_input("Cari keyword", placeholder="Contoh: konsumsi, transport, hadiah")
    with f2:
        category_filter = st.multiselect("Kategori", category_options)
    with f3:
        severity_filter = st.multiselect("Severity", severity_options)
    with f4:
        default_status = ["active"] if "active" in status_options else status_options
        status_filter = st.multiselect("Status", status_options, default=default_status)

    filtered_keywords = filter_keyword_rows(all_keywords, keyword_search, category_filter, severity_filter, status_filter)
    keyword_frame = keyword_editor_frame(filtered_keywords, aliases)
    edited_keywords = keyword_editor(keyword_frame, "keyword_bulk_editor", "Database keyword masih kosong atau filter tidak menemukan data.")
    selected_ids = selected_keyword_ids(edited_keywords)
    ui.status_note(f"{len(selected_ids)} keyword dipilih dari {len(keyword_frame)} baris yang sedang tampil.")

    a1, a2 = st.columns([1, 2])
    with a1:
        if st.button("Nonaktifkan Selected", type="primary", disabled=not selected_ids):
            st.warning(actions.bulk_deactivate_keywords(selected_ids))
            st.rerun()
    with a2:
        with st.expander("Hapus permanen selected", expanded=False):
            st.warning("Aksi ini menghapus keyword, sinonim, dan exception terkait dari SQLite. Feedback historis tetap disimpan.")
            st.caption(f"Keyword yang akan dihapus permanen: {len(selected_ids)}")
            confirmation = st.text_input("Ketik HAPUS PERMANEN untuk mengaktifkan tombol", key="hard_delete_confirmation")
            if st.button("Hapus Permanen Selected", disabled=not selected_ids or confirmation != "HAPUS PERMANEN"):
                st.error(actions.bulk_delete_keywords(selected_ids))
                st.rerun()

    with st.expander("Keyword nonaktif", expanded=False):
        inactive_search = st.text_input("Cari keyword nonaktif", placeholder="Cari keyword yang ingin direstore")
        inactive_rows = filter_keyword_rows(all_keywords, inactive_search, statuses=["inactive"])
        inactive_frame = keyword_editor_frame(inactive_rows, aliases)
        edited_inactive = keyword_editor(inactive_frame, "keyword_inactive_editor", "Belum ada keyword nonaktif.")
        restore_ids = selected_keyword_ids(edited_inactive)
        st.caption(f"{len(restore_ids)} keyword nonaktif dipilih untuk restore.")
        if st.button("Restore Selected", disabled=not restore_ids):
            st.success(actions.bulk_restore_keywords(restore_ids))
            st.rerun()

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
Rilis ini memakai tag git `v1.0.1`. Untuk rollback lokal, gunakan tag tersebut dari GitHub atau jalankan `git checkout v1.0.1` pada salinan repo. Untuk Streamlit Cloud, deploy ulang branch atau tag yang ingin dipakai.
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
