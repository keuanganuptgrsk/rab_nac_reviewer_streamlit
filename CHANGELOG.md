# Changelog

Semua penambahan fitur harus dicatat dengan format: versi, judul, tanggal, dan keterangan.

## v1.4.0 - Adaptive RAB Parser and AI Review Providers - 2026-09-11

- Mengganti parser posisi tetap dengan profiler adaptif untuk XLSX, XLS, CSV, PDF digital, dan PDF OCR.
- Menambahkan model RAB kanonis, stable source ID, provenance nilai, diagnostics mapping, dan konfirmasi mapping manual per sesi.
- Mengabaikan hidden row serta memvalidasi relasi volume, harga satuan, material, jasa, dan total tanpa koreksi diam-diam.
- Menambahkan engine `Python Lokal`, `OpenAI API`, dan `Gemini Flash API` dengan consent eksplisit, structured output, retry, cache, serta deterministic fallback.
- Membatasi AI hanya untuk merangking kandidat rule pack tepercaya; AI tidak dapat membuat atau mengubah Prosentase NAC.
- Memperluas metadata audit provider, parser, rule pack, sumber keputusan, timestamp, serta confidence deterministic dan AI yang terpisah.
- Mengganti PDF menjadi summary landscape dan appendix audit portrait, serta memperkuat format angka dan audit di seluruh Excel export.
- Menambahkan validasi upload 100 MB, direktori sesi terisolasi, validasi restore SQLite, logging tersanitasi, dan dokumentasi arsitektur.

## v1.3.0 - Context-Aware Hierarchical NAC Review - 2026-09-10

- Memisahkan deteksi `judul_rab`, `section/subjudul`, dan `item_per_rab` dengan bobot 15%, 25%, dan 60%.
- Menambahkan agregasi kandidat transaksi dari exact keyword, sinonim, fuzzy, dan semantic per field.
- Memisahkan Prosentase NAC sebagai aturan koreksi transaksi dari Confidence sebagai keyakinan klasifikasi.
- Menahan penerapan prosentase saat kandidat berbeda sama-sama kuat dan menandainya sebagai `Perlu penentuan reviewer - Ambigu`.
- Menambahkan audit match per field, konsistensi konteks, kandidat transaksi kedua, sumber prosentase, dan alasan keputusan.
- Memperluas Review RAB, Analisa Redaksi, PDF, serta Excel dengan output context-aware dan export audit lengkap.
- Memperkuat allowable/exception untuk konteks teknis pembangkit, gardu, transmisi, distribusi, operasi, dan pemeliharaan.

## v1.2.1 - Streamlit Cloud Build Reliability - 2026-09-08

- Menghapus `packages.txt` agar build Streamlit Community Cloud tidak bergantung pada repository APT Debian.
- Menambahkan pemeriksaan ketersediaan Tesseract, PaddleOCR, dan EasyOCR sebelum engine dipanggil.
- Menambahkan status OCR runtime pada halaman Settings dan pesan fallback untuk gambar/PDF scan.
- Mempertahankan OCR Tesseract untuk instalasi lokal tanpa menghambat Excel, CSV, PDF teks, semantic matching, dan review di Cloud.

## v1.2.0 - Indonesian Semantic Matching Lite - 2026-05-18

- Menambahkan semantic similarity Bahasa Indonesia berbasis Hugging Face untuk mendeteksi sinonim dan parafrasa NAC.
- Menggunakan model default `LazarusNLP/all-indo-e5-small-v4` dengan fallback lexical bila paket/model gagal dimuat.
- Menambahkan konteks embedding dari keyword, sinonim, metadata transaksi, G/L description, notes, dan feedback `Correct NAC`.
- Menambahkan output audit semantic: kandidat semantic, sumber kandidat, alasan semantic, dan model yang dipakai.
- Menambahkan panel `Semantic Bahasa Indonesia` di Settings untuk memilih model, melihat status package/cache, dan rebuild index.
- Menambahkan `sentence-transformers` ke dependency Cloud agar semantic bisa diaktifkan di Streamlit Community Cloud.

## v1.1.0 - NAC 2026 Keyword Pack - 2026-05-18

- Mengganti seed keyword demo dengan keyword NAC 2026 Kategori A dan Kategori B.
- Menambahkan metadata `Prosentase NAC`, `Type of Transaction`, G/L account, rujukan sumber, dan slide sumber pada keyword pack.
- Menampilkan `Prosentase NAC` dan `Type of Transaction` di UI review, Analisa Redaksi, PDF, Excel, dan export database keyword.
- Menambahkan allowable/exception untuk konteks teknis seperti rumah dinas operator, pakaian dinas petugas operasi, dan konsumsi bahan bakar.

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
