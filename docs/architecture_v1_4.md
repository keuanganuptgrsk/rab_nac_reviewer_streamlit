# Arsitektur v1.4.0

## Alur Review

1. Upload divalidasi berdasarkan ukuran, ekstensi, dan signature, lalu disimpan di direktori UUID milik sesi.
2. `adaptive_parser` memprofilkan tiap sheet atau region dan memetakan data ke `RABItem` kanonis.
3. Mapping dengan confidence rendah atau ambigu diblokir sampai reviewer mengonfirmasi kolom untuk sesi aktif.
4. Deterministic engine membentuk maksimal lima kandidat dari keyword pack NAC 2026 beserta allowable dan exception.
5. `Python Lokal` menetapkan hasil tanpa jaringan. OpenAI atau Gemini hanya merangking ID kandidat setelah consent eksplisit.
6. Orchestrator menolak kandidat asing, payload/schema invalid, dan field prosentase dari provider.
7. Prosentase final selalu diambil dari rule kandidat tepercaya. Konflik atau disagreement ditahan untuk review manual.
8. UI, PDF, dan Excel menerima model audit yang sama agar hasil dapat ditelusuri kembali ke file, baris, rule, dan engine.

## Boundary Modul

- `modules/rab_models.py`: kontrak dokumen, region, mapping, diagnostics, dan item kanonis.
- `modules/adaptive_parser.py`: profiler spreadsheet dan normalisasi angka/provenance.
- `modules/pdf_loader.py`: ekstraksi PDF berbasis koordinat dan fallback OCR confidence rendah.
- `modules/nac_detector.py`: matching deterministic, guard allowable/exception, dan kandidat rule tepercaya.
- `modules/providers/`: kontrak provider, OpenAI, Gemini, validasi, retry, cache, dan kebijakan alternate.
- `modules/review_flow.py`: keamanan upload, orchestration review, serta frame UI/export.
- `modules/export_engine.py`: workbook finance dan PDF dua tingkat.
- `modules/db.py`: schema, keyword pack, backup, dan restore transaksional.

## Kebijakan Data

- Mode lokal tidak mengirim data ke API eksternal.
- Mode cloud mengirim judul, section, uraian item, dan kandidat transaksi yang ditampilkan di UI sebelum consent.
- API key dibaca dari `st.secrets` atau environment dan tidak masuk cache, log, export, prompt audit, atau database.
- Prompt mentah dan response mentah tidak disimpan. Cache hanya menyimpan hasil audit tervalidasi selama maksimal 24 jam.
- Dokumen upload lebih tua dari 24 jam dibersihkan saat pipeline upload berjalan.

## Roadmap Enterprise

Streamlit Community Cloud dan SQLite tetap cocok untuk pilot atau review ringan. Tahap berikut untuk pemakaian enterprise:

1. Pindahkan database ke PostgreSQL dengan row-level audit, migration tooling, dan backup terjadwal.
2. Tambahkan SSO perusahaan, role reviewer/admin, serta pemisahan workspace per unit.
3. Simpan dokumen pada object storage terenkripsi dengan retention policy dan malware scanning.
4. Jalankan worker OCR/model terpisah agar UI tidak bergantung pada resource proses Streamlit.
5. Tambahkan immutable audit event, approval workflow, dan observability tanpa menyimpan isi dokumen sensitif.
6. Bangun benchmark parser dan detector dari dataset RAB berlabel sebelum fine-tuning model Indonesia.
7. Tambahkan deployment private network untuk dokumen yang tidak boleh diproses pada cloud publik.
