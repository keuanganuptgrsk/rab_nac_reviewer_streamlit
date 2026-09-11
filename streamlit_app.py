from __future__ import annotations

import html
import json
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from modules import db
from modules import feedback_actions as actions
from modules import review_flow
from modules import ui_system as ui
from modules.export_engine import (
    export_all_materials_excel,
    export_all_materials_pdf,
    export_potential_nac_pdf,
    export_review_excel,
)
from modules.feedback_engine import learning_summary
from modules.safe_logging import configure_logging
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
        "export_review_excel": "",
        "keyword_export": "",
        "db_backup": "",
        "upload_session_id": uuid.uuid4().hex,
        "review_engine": "Python Lokal",
        "cloud_consent": False,
        "manual_mappings": {},
        "parser_confirmed": False,
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
    path = review_flow.save_uploaded_file(
        uploaded_file,
        session_id=st.session_state.get("upload_session_id"),
    )
    loaded = review_flow.load_uploaded_path(path)
    st.session_state.upload_signature = signature
    st.session_state.upload_state = loaded["state"]
    st.session_state.upload_preview = loaded["preview"]
    st.session_state.upload_message = loaded["message"]
    st.session_state.review_results = []
    st.session_state.review_message = ""
    st.session_state.manual_mappings = {}
    st.session_state.parser_confirmed = False
    for key in ["export_potential_pdf", "export_all_pdf", "export_all_excel", "export_review_excel"]:
        st.session_state[key] = ""


def parser_diagnostics_panel(upload_state: dict) -> None:
    diagnostics = upload_state.get("diagnostics") or [
        region.get("diagnostic", {}) for region in upload_state.get("regions", [])
    ]
    if not diagnostics:
        return
    ui.section_label("Parser diagnostics")
    diagnostic_rows = []
    for diagnostic in diagnostics:
        mapped = []
        for role, mapping in diagnostic.get("mappings", {}).items():
            if mapping.get("column_label"):
                mapped.append(f"{role}={mapping['column_label']}")
        diagnostic_rows.append(
            {
                "Region": diagnostic.get("region_id", "-"),
                "Confidence": float(diagnostic.get("confidence") or 0),
                "Level": diagnostic.get("confidence_label", "-"),
                "Header Rows": ", ".join(map(str, diagnostic.get("header_rows", []))) or "-",
                "Mapping": "; ".join(mapped) or "Text blocks",
                "Arithmetic Failures": int(diagnostic.get("arithmetic_failures") or 0),
                "Hidden Rows Skipped": int(diagnostic.get("hidden_rows_skipped") or 0),
                "Status": "Perlu konfirmasi" if diagnostic.get("review_blocked") else "Siap",
            }
        )
    st.dataframe(
        pd.DataFrame(diagnostic_rows),
        width="stretch",
        hide_index=True,
        column_config={
            "Confidence": st.column_config.ProgressColumn(
                "Confidence", min_value=0, max_value=100, format="%.1f%%"
            ),
            "Mapping": st.column_config.TextColumn("Mapping", width="large"),
        },
    )
    warning_lines = [
        warning
        for diagnostic in diagnostics
        for warning in diagnostic.get("warnings", [])
    ]
    if warning_lines:
        with st.expander("Warning dan detail mapping", expanded=False):
            for warning in warning_lines:
                st.markdown(f"- {warning}")

    if not upload_state.get("review_blocked"):
        return
    if upload_state.get("source_quality") == "ocr":
        st.warning("OCR tidak memiliki struktur tabel tepercaya. Angka tidak direkonstruksi otomatis.")
        if st.button("Konfirmasi review text-only", type="primary"):
            loaded = review_flow.reload_with_manual_mapping(upload_state, {}, confirm_low_confidence=True)
            _set_loaded_upload(loaded)
            st.rerun()
        return

    with st.expander("Konfirmasi mapping manual", expanded=True):
        st.caption("Pilih kolom untuk region yang ambigu. Mapping ini hanya berlaku pada upload dan sesi aktif.")
        manual_mappings = dict(st.session_state.get("manual_mappings", {}))
        with st.form("manual_mapping_form"):
            for diagnostic in diagnostics:
                if not diagnostic.get("review_blocked"):
                    continue
                region_id = diagnostic.get("region_id", "region")
                st.markdown(f"**{region_id}**")
                mappings = diagnostic.get("mappings", {})
                used_labels = [mapping.get("column_label", "") for mapping in mappings.values()]
                max_index = max([_excel_col_number(label) for label in used_labels if label] + [16])
                options = [""] + [_excel_col_label(index) for index in range(1, min(max_index + 4, 52) + 1)]
                cols = st.columns(4)
                for position, (role, label) in enumerate(
                    [
                        ("description", "Item / Uraian"),
                        ("item_number", "No."),
                        ("unit", "Satuan"),
                        ("volume", "Volume"),
                        ("material_unit_price", "Harga Material"),
                        ("service_unit_price", "Harga Jasa"),
                        ("total_price", "Total"),
                        ("notes", "Catatan"),
                    ]
                ):
                    current = mappings.get(role, {}).get("column_label", "")
                    with cols[position % 4]:
                        selected = st.selectbox(
                            label,
                            options,
                            index=options.index(current) if current in options else 0,
                            key=f"manual_{region_id}_{role}",
                        )
                    manual_mappings.setdefault(region_id, {})[role] = selected
            submitted = st.form_submit_button("Terapkan dan konfirmasi mapping", type="primary")
        if submitted:
            loaded = review_flow.reload_with_manual_mapping(upload_state, manual_mappings)
            st.session_state.manual_mappings = manual_mappings
            _set_loaded_upload(loaded)
            st.rerun()


def _set_loaded_upload(loaded: dict) -> None:
    st.session_state.upload_state = loaded["state"]
    st.session_state.upload_preview = loaded["preview"]
    st.session_state.upload_message = loaded["message"]
    st.session_state.review_results = []
    st.session_state.review_message = ""


def _excel_col_number(label: str) -> int:
    number = 0
    for char in str(label or "").upper():
        if "A" <= char <= "Z":
            number = number * 26 + ord(char) - 64
    return number


def _excel_col_label(number: int) -> str:
    label = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        label = chr(65 + remainder) + label
    return label


def review_page() -> None:
    ui.hero(APP_VERSION, APP_RELEASE_TITLE, APP_RELEASE_NOTES, current_metrics())
    st.markdown(
        "Upload Excel/CSV untuk hasil paling presisi. PDF digital didukung; gambar/PDF scan memerlukan engine OCR pada runtime dan diproses secara best-effort."
    )

    uploaded = st.file_uploader(
        "Upload RAB",
        type=[ext.lstrip(".") for ext in review_flow.SUPPORTED_EXTENSIONS],
        help="Format: xlsx, xls, csv, pdf, png, jpg, jpeg.",
        key="rab_file_uploader",
    )
    if uploaded is not None:
        try:
            with st.spinner("Membaca struktur file dan menyiapkan preview..."):
                load_uploaded_file(uploaded)
        except Exception as exc:
            st.error(f"File tidak dapat diproses: {exc}")
            return

    upload_state = st.session_state.get("upload_state", {})
    if not upload_state:
        ui.empty_state("Belum ada file. Upload RAB untuk mulai review.")
        return

    ui.status_note(st.session_state.get("upload_message", "File siap direview."))

    parser_diagnostics_panel(upload_state)

    preview = st.session_state.get("upload_preview", pd.DataFrame())
    if preview is not None and not preview.empty:
        ui.section_label("Preview finance")
        st.dataframe(
            preview,
            width="stretch",
            hide_index=True,
            height=ui.dataframe_height(preview, 220, 430),
            column_config={
                "Item / Uraian": st.column_config.TextColumn("Item / Uraian", width="large"),
                "Volume": st.column_config.NumberColumn("Volume", format="%.2f"),
                "Harga Satuan": st.column_config.NumberColumn("Harga Satuan", format="Rp %.0f"),
                "Total": st.column_config.NumberColumn("Total", format="Rp %.0f"),
                "Source Row": st.column_config.TextColumn("Source Row", width="small"),
            },
        )
        with st.expander("Debug / Raw Parser Data", expanded=False):
            raw = pd.DataFrame(upload_state.get("items", []))
            for column in ("raw_values", "provenance", "parser_warnings"):
                if column in raw.columns:
                    raw[column] = raw[column].map(lambda value: json.dumps(value, ensure_ascii=False, default=str))
            st.dataframe(raw, width="stretch", hide_index=True, height=360)

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

    ui.section_label("Review engine")
    engine = st.segmented_control(
        "Review engine",
        ["Python Lokal", "OpenAI API", "Gemini Flash API"],
        key="review_engine",
        label_visibility="collapsed",
    ) or "Python Lokal"
    provider_status = review_flow.provider_runtime_status(engine, st.secrets)
    if engine == "Python Lokal":
        st.caption("Offline. Seluruh data dan keputusan diproses oleh deterministic rule engine lokal.")
    else:
        credential_text = "siap" if provider_status["credential"] else "belum tersedia"
        package_text = "terpasang" if provider_status["package"] else "belum terpasang"
        st.caption(
            f"Mode cloud | model {provider_status['model']} | SDK {package_text} | credential {credential_text}."
        )
        st.session_state.cloud_consent = st.checkbox(
            "Saya menyetujui pengiriman data review pada sesi ini ke provider cloud yang dipilih.",
            value=bool(st.session_state.get("cloud_consent")),
        )
        with st.expander("Data yang dikirim ke provider", expanded=False):
            st.markdown(
                "Setiap baris mengirim **judul RAB, section/subjudul, item/uraian, dan maksimal lima kandidat transaksi tepercaya**. "
                "File asli, API key, harga, total, serta Prosentase NAC tidak dikirim oleh prompt provider."
            )
            payload_preview = review_flow.cloud_payload_preview(upload_state)
            st.dataframe(payload_preview, width="stretch", hide_index=True, height=300)
            if len(upload_state.get("items", [])) > len(payload_preview):
                st.caption(
                    f"Preview menampilkan {len(payload_preview)} dari {len(upload_state.get('items', []))} baris; "
                    "seluruh baris diproses saat review."
                )

    parser_blocked = bool(upload_state.get("review_blocked"))
    cloud_blocked = engine != "Python Lokal" and (
        not provider_status["available"] or not st.session_state.get("cloud_consent")
    )
    run_clicked = st.button(
        "Run NAC Review",
        type="primary",
        width="stretch",
        disabled=parser_blocked or cloud_blocked,
    )
    if parser_blocked:
        st.warning("Review belum dapat dijalankan sampai mapping parser dikonfirmasi.")
    elif cloud_blocked:
        st.warning("Lengkapi credential provider dan persetujuan sesi untuk menjalankan review cloud.")
    if run_clicked:
        try:
            with st.spinner("Memproses deteksi NAC..."):
                progress = st.progress(0, text="Menyiapkan deterministic review...") if engine != "Python Lokal" else None

                def update_progress(done, total, cache_hits, failed):
                    if progress is not None:
                        ratio = done / max(total, 1)
                        progress.progress(
                            ratio,
                            text=f"Provider cloud: {done}/{total} cache miss diproses | cache hit {cache_hits} | gagal {failed}",
                        )

                results, message = review_flow.run_review(
                    upload_state,
                    text_columns,
                    volume_col,
                    unit_col,
                    unit_price_col,
                    total_price_col,
                    engine=engine,
                    secrets=st.secrets,
                    progress_callback=update_progress,
                )
                if progress is not None:
                    progress.progress(1.0, text="Review selesai.")
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
    ui.status_note(
        "Prosentase NAC adalah proporsi koreksi dari aturan transaksi. Confidence adalah tingkat keyakinan "
        "klasifikasi berdasarkan item, subjudul, judul, allowable, dan exception; keduanya tidak memakai rumus yang sama."
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
            "Prosentase NAC": st.column_config.TextColumn(
                "Prosentase NAC",
                help="Proporsi koreksi yang diterapkan dari aturan transaksi, bukan skor confidence.",
            ),
            "Prosentase Referensi": st.column_config.TextColumn(
                "Prosentase Referensi",
                help="Angka aturan pada keyword pack sebelum keputusan penerapan.",
            ),
            "Confidence": st.column_config.ProgressColumn(
                "Confidence",
                min_value=0,
                max_value=100,
                format="%.1f%%",
                help="Keyakinan klasifikasi dari bukti hierarkis dan guard allowable/exception.",
            ),
            "Konsistensi Konteks": st.column_config.ProgressColumn(
                "Konsistensi Konteks",
                min_value=0,
                max_value=100,
                format="%.1f%%",
                help="Keselarasan transaksi terpilih pada item, subjudul, dan judul.",
            ),
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
                "Prosentase NAC": st.column_config.TextColumn(
                    "Prosentase NAC",
                    help="Proporsi koreksi yang diterapkan dari aturan transaksi, bukan skor confidence.",
                ),
                "Confidence %": st.column_config.ProgressColumn(
                    "Confidence %",
                    min_value=0,
                    max_value=100,
                    format="%.1f%%",
                    help="Keyakinan klasifikasi dari bukti hierarkis dan guard allowable/exception.",
                ),
                "Konsistensi Konteks": st.column_config.ProgressColumn(
                    "Konsistensi Konteks",
                    min_value=0,
                    max_value=100,
                    format="%.1f%%",
                ),
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
    c1, c2, c3, c4 = st.columns(4)
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
    with c4:
        if st.button("Buat Excel Audit Lengkap", width="stretch"):
            st.session_state.export_review_excel = export_review_excel(results)
        if st.session_state.get("export_review_excel"):
            data, name = ui.file_download(st.session_state.export_review_excel)
            st.download_button(
                "Download Excel Audit Lengkap",
                data,
                file_name=name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )


def redaction_page() -> None:
    ui.hero(
        APP_VERSION,
        APP_RELEASE_TITLE,
        "Uji redaksi RAB dengan konteks judul, subjudul, dan item sebelum dokumen direview.",
        current_metrics(),
    )
    title_text = st.text_input(
        "Judul RAB",
        placeholder="Contoh: Pemeliharaan jaringan distribusi",
    )
    section_text = st.text_input(
        "Subjudul / section pekerjaan",
        placeholder="Contoh: Material pekerjaan teknis",
    )
    text = st.text_area(
        "Redaksi item / material",
        placeholder="Contoh: Kabel penghantar 150 mm",
        height=130,
    )
    if not text.strip():
        ui.empty_state("Ketik satu kalimat redaksi untuk melihat potensi NAC, keyword, dan saran klarifikasi.")
        return

    result = review_flow.analyze_redaction(text, title_text, section_text)
    if not result:
        ui.empty_state("Belum ada hasil analisa.")
        return

    score = float(result.get("final_confidence", 0) or 0)
    label = result.get("confidence_label", "-")
    category = result.get("matched_category") or "Tidak ada kategori kuat"
    keyword = result.get("matched_keyword") or "-"
    percentage = result.get("correction_percentage_label") or "-"
    transaction_type = result.get("selected_transaction_type") or "-"
    reference_percentage = result.get("reference_percentage_label") or "-"
    percentage_status = result.get("percentage_status") or "Tidak teridentifikasi"
    semantic_candidate = result.get("semantic_candidate_text") or "-"
    semantic_reason = result.get("semantic_reason") or ""
    st.markdown(
        f"""
<div class="hero-panel">
  <div class="hero-panel-title">Confidence klasifikasi</div>
  <div class="hero-panel-number">{score:.1f}%</div>
  <div>{ui.confidence_pill(label)}</div>
  <div class="hero-panel-line"></div>
  <div class="hero-panel-copy"><strong>Kategori:</strong> {html.escape(category)}</div>
  <div class="hero-panel-copy"><strong>Keyword:</strong> {html.escape(keyword)}</div>
  <div class="hero-panel-copy"><strong>Prosentase NAC:</strong> {html.escape(percentage)}</div>
  <div class="hero-panel-copy"><strong>Prosentase Referensi:</strong> {html.escape(reference_percentage)}</div>
  <div class="hero-panel-copy"><strong>Status Prosentase:</strong> {html.escape(percentage_status)}</div>
  <div class="hero-panel-copy"><strong>Type of Transaction:</strong> {html.escape(transaction_type)}</div>
  <div class="hero-panel-copy"><strong>Kandidat Semantic:</strong> {html.escape(semantic_candidate)}</div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.progress(min(max(score / 100, 0), 1))
    ui.status_note(result.get("explanation", ""))
    if semantic_reason:
        st.caption(f"Semantic audit: {semantic_reason}")
    ui.section_label("Bukti hierarkis")
    context_audit = pd.DataFrame(
        [
            {
                "Field": "Judul RAB (15%)",
                "Redaksi": title_text or "-",
                "Kandidat": result.get("title_match_keyword") or "-",
                "Skor": float(result.get("title_match_score") or 0),
            },
            {
                "Field": "Subjudul / section (25%)",
                "Redaksi": section_text or "-",
                "Kandidat": result.get("section_match_keyword") or "-",
                "Skor": float(result.get("section_match_score") or 0),
            },
            {
                "Field": "Item / material (60%)",
                "Redaksi": text,
                "Kandidat": result.get("item_match_keyword") or "-",
                "Skor": float(result.get("item_match_score") or 0),
            },
        ]
    )
    st.dataframe(
        context_audit,
        width="stretch",
        hide_index=True,
        column_config={
            "Skor": st.column_config.ProgressColumn("Skor", min_value=0, max_value=100, format="%.1f%%"),
        },
    )
    ui.section_label("Keputusan transaksi")
    ui.status_note(result.get("decision_reason") or "Belum ada keputusan transaksi.")
    if result.get("alternative_transaction"):
        st.caption(
            f"Kandidat kedua: {result['alternative_transaction']} "
            f"({result.get('alternative_percentage_label') or 'prosentase belum tersedia'})."
        )
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
        haystack = " ".join(
            str(row.get(key) or "")
            for key in [
                "id", "category", "keyword", "severity", "description", "reference", "notes",
                "status", "nac_group", "transaction_type", "gl_account", "gl_account_description",
            ]
        ).lower()
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
                "Prosentase": f"{int(float(row.get('correction_percentage')))}%" if row.get("correction_percentage") not in (None, "") else "",
                "Type of Transaction": row.get("transaction_type", ""),
                "Sinonim": synonym_text,
                "Catatan": row.get("notes") or row.get("description", ""),
            }
        )
    return pd.DataFrame(records, columns=["Pilih", "ID", "Kategori", "Keyword", "Severity", "Prosentase", "Type of Transaction", "Sinonim", "Catatan"])


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
        disabled=["ID", "Kategori", "Keyword", "Severity", "Prosentase", "Type of Transaction", "Sinonim", "Catatan"],
        column_config={
            "Pilih": st.column_config.CheckboxColumn("Pilih", help="Centang keyword untuk bulk action.", default=False),
            "ID": st.column_config.NumberColumn("ID", width="small"),
            "Kategori": st.column_config.TextColumn("Kategori", width="medium"),
            "Keyword": st.column_config.TextColumn("Keyword", width="medium"),
            "Severity": st.column_config.TextColumn("Severity", width="small"),
            "Prosentase": st.column_config.TextColumn("Prosentase", width="small"),
            "Type of Transaction": st.column_config.TextColumn("Type of Transaction", width="large"),
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
            try:
                path = review_flow.save_database_upload(
                    restore_file,
                    session_id=st.session_state.get("upload_session_id"),
                )
                db.restore_db(path)
                st.success("Backup lolos integrity/schema check dan berhasil direstore.")
            except Exception as exc:
                st.error(f"Restore ditolak: {exc}")


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
    model_options = review_flow.SEMANTIC_MODEL_OPTIONS
    current_model = settings.get("embedding_model") or "LazarusNLP/all-indo-e5-small-v4"
    label_by_model = {value: label for label, value in model_options.items()}
    model_labels = list(model_options)
    current_model_label = label_by_model.get(current_model, model_labels[0])

    with st.form("settings_form"):
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1.5])
        with c1:
            review_mode = st.radio("Mode Review", ["Ketat", "Seimbang", "Lebih sensitif"], index=["Ketat", "Seimbang", "Lebih sensitif"].index(review_mode_default))
        with c2:
            semantic_mode = st.radio("Deteksi Sinonim/Parafrasa Otomatis", ["Nonaktif", "Aktif"], index=["Nonaktif", "Aktif"].index(semantic_default))
        with c3:
            ocr_mode = st.radio("OCR PDF Scan/Gambar", ["auto", "disabled"], index=["auto", "disabled"].index(ocr_default))
        with c4:
            model_label = st.selectbox("Model Semantic", model_labels, index=model_labels.index(current_model_label))
        submitted = st.form_submit_button("Simpan Settings", type="primary")
    if submitted:
        st.success(review_flow.save_simple_settings(review_mode, semantic_mode, ocr_mode, model_options[model_label]))
    if semantic_mode == "Aktif" and not semantic_available:
        st.warning("Paket sentence-transformers belum terpasang. Semantic matching akan fallback tanpa menghentikan review.")

    ui.section_label("Status OCR Runtime")
    ocr_overview = review_flow.ocr_runtime_overview()
    ui.status_note(ocr_overview["message"])
    if ocr_overview["available_engines"]:
        st.caption("Engine OCR aktif: " + ", ".join(ocr_overview["available_engines"]))

    ui.section_label("Semantic Bahasa Indonesia")
    overview = review_flow.semantic_runtime_overview(model_options.get(model_label, current_model))
    st.dataframe(
        pd.DataFrame(
            [
                {"Status": "Package", "Nilai": "Tersedia" if overview["package_available"] else "Belum terpasang"},
                {"Status": "Model aktif", "Nilai": overview["model"]},
                {"Status": "Status model", "Nilai": overview["model_status"]},
                {"Status": "Kandidat index", "Nilai": str(overview["candidate_count"])},
                {"Status": "Cache index", "Nilai": str(overview["cached_index_count"])},
            ]
        ),
        width="stretch",
        hide_index=True,
        height=215,
    )
    st.caption(
        "Semantic diproses lokal di runtime Streamlit tanpa API eksternal. First run di Cloud dapat lebih lama karena model Hugging Face perlu diunduh dan dimuat."
    )
    c_sem1, c_sem2 = st.columns([1, 2])
    with c_sem1:
        if st.button("Rebuild Semantic Index", width="stretch"):
            review_flow.clear_semantic_cache()
            st.success("Cache semantic dibersihkan. Index akan dibangun ulang pada review berikutnya.")
            st.rerun()
    with c_sem2:
        st.caption(
            f"Signature index aktif: {overview['signature']} | Keyword aktif: {overview['active_keyword_count']} | "
            f"Sinonim aktif: {overview['active_synonym_count']} | Feedback Correct NAC: {overview['positive_feedback_count']}"
        )

    ui.section_label("AI Review Providers")
    provider_rows = []
    for engine_name in ["Python Lokal", "OpenAI API", "Gemini Flash API"]:
        status = review_flow.provider_runtime_status(engine_name, st.secrets)
        provider_rows.append(
            {
                "Engine": engine_name,
                "Mode": status["mode"],
                "SDK": "Tersedia" if status["package"] else "Belum terpasang",
                "Credential": "Tersedia" if status["credential"] else "Belum tersedia",
                "Model": status["model"],
                "Siap": "Ya" if status["available"] else "Tidak",
            }
        )
    st.dataframe(pd.DataFrame(provider_rows), width="stretch", hide_index=True)
    st.caption(
        "API key hanya dibaca dari Streamlit secrets atau environment dan tidak ditulis ke database, log, cache, maupun hasil export."
    )
    test_cols = st.columns(2)
    for index, engine_name in enumerate(["OpenAI API", "Gemini Flash API"]):
        with test_cols[index]:
            if st.button(f"Test {engine_name}", width="stretch", key=f"test_{engine_name}"):
                ok, message = review_flow.test_provider_connection(engine_name, st.secrets)
                (st.success if ok else st.error)(message)

    with st.expander("Versioning dan rollback", expanded=True):
        st.markdown(version_banner())
        st.markdown(
            """
Rilis ini memakai tag git `v1.4.0`. Untuk rollback lokal, gunakan tag stabil dari GitHub atau jalankan `git checkout v1.3.0` pada salinan repo. Untuk Streamlit Cloud, deploy ulang branch atau tag yang ingin dipakai.
"""
        )

    with st.expander("Reset database NAC 2026", expanded=False):
        st.warning("Reset akan membuat ulang database dari seed NAC 2026 dan menghapus perubahan SQLite lokal pada environment aktif.")
        if st.button("Reset database NAC 2026"):
            db.reset_demo_database()
            st.success("Database NAC 2026 dibuat ulang.")


def main() -> None:
    configure_logging()
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
