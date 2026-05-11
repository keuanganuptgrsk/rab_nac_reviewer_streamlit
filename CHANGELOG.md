# Changelog

Semua penambahan fitur harus dicatat dengan format: versi, judul, tanggal, dan keterangan.

## v1.0.1 - Bulk Keyword Management - 2026-05-11

- Mengganti hapus keyword berbasis dropdown menjadi tabel checkbox bulk action.
- Menambahkan aksi `Nonaktifkan Selected` untuk soft-delete audit-friendly.
- Menambahkan `Hapus Permanen Selected` dengan konfirmasi `HAPUS PERMANEN`.
- Menambahkan restore massal untuk keyword nonaktif.
- Mengganti copy rilis menjadi `Review potensi NAC dengan mudah~`.

## v1.0.0 - Streamlit Migration and Finance Review Workspace - 2026-05-11

- Memigrasikan aplikasi dari Gradio ke Streamlit dengan entry point `streamlit_app.py`.
- Membuat navigasi top-level untuk Review RAB, Analisa Redaksi, Database NAC, Feedback & Learning, dan Settings.
- Mempertahankan business logic deteksi NAC, parser Excel/CSV/PDF/OCR, SQLite keyword database, feedback learning, dan export PDF/Excel.
- Menambahkan helper `modules/review_flow.py` dan `modules/feedback_actions.py` agar alur Streamlit bisa diuji tanpa bergantung pada UI.
- Menambahkan env var `RAB_NAC_DB_PATH`, `RAB_NAC_DATA_DIR`, `RAB_NAC_EXPORT_DIR`, dan `RAB_NAC_UPLOAD_DIR` untuk testing/deploy.
- Menambahkan konfigurasi Streamlit Cloud, requirements produksi, requirements dev, smoke tests, dan tutorial pemula di README.
