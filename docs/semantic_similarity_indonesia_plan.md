# Rencana Upgrade Deteksi Sinonim dan Parafrasa Bahasa Indonesia

Dokumen ini merencanakan upgrade semantic matching untuk RAB NAC Reviewer agar lebih kuat membaca sinonim/parafrasa Bahasa Indonesia, tetapi tetap realistis untuk Streamlit Community Cloud gratis.

## Tujuan

- Menangkap redaksi yang tidak persis sama dengan keyword NAC, misalnya `hidangan peserta rapat`, `biaya makan minum koordinasi`, `publikasi running text`, atau `alihdaya gedung satpam`.
- Tetap audit-friendly: semantic matching hanya membantu prioritisasi, keputusan akhir tetap pada reviewer.
- Tetap bisa berjalan di Streamlit Community Cloud gratis dengan fallback yang aman bila model tidak berhasil dimuat.

## Referensi Model Hugging Face

| Prioritas | Model | Alasan | Catatan Hosting |
| --- | --- | --- | --- |
| Default rekomendasi | [LazarusNLP/all-indo-e5-small-v4](https://hf.co/LazarusNLP/all-indo-e5-small-v4) | Sentence similarity, berbasis Bahasa Indonesia, 117.7M parameter, dataset Indonesia seperti IndoNLI dan paraphrase detection. | Kandidat terbaik untuk akurasi Indonesia, tapi cold start dan dependency `sentence-transformers` perlu dipantau. |
| Fallback stabil | [intfloat/multilingual-e5-small](https://hf.co/intfloat/multilingual-e5-small) | Multilingual, mendukung `id`, 117.7M parameter, ekosistem luas. | Cocok bila model Indonesia sulit diunduh/cache. |
| Baseline lama | [sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://hf.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | Sudah menjadi default lama, sangat populer untuk paraphrase multilingual. | Lebih generic; simpan sebagai fallback kompatibilitas. |
| Evaluasi lokal | [firqaaa/indo-sentence-bert-base](https://hf.co/firqaaa/indo-sentence-bert-base) | Model sentence similarity Bahasa Indonesia. | Perlu benchmark lokal dengan redaksi NAC karena kualitas domain belum pasti. |
| Tidak untuk free cloud | [BAAI/bge-m3](https://hf.co/BAAI/bge-m3) | Kuat untuk multilingual retrieval. | Terlalu berat untuk default Streamlit gratis; hanya lokal/server kuat. |

Referensi hosting: Streamlit Community Cloud menyatakan resource app sekitar CPU 0.078-2 core, memori 690MB-2.7GB, dan storage sampai 50GB, serta dependency dikelola dari `requirements.txt` dan `packages.txt`. Sumber: [Manage your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app), [Managing dependencies](https://docs.streamlit.io/deploy/concepts/dependencies), dan [Status and limitations](https://docs.streamlit.io/deploy/streamlit-community-cloud/status).

## Arsitektur Deteksi

1. **Candidate generation ringan**
   - Ambil kandidat dari exact keyword, sinonim manual, RapidFuzz, kategori, `transaction_type`, `description`, `notes`, dan feedback positif reviewer.
   - Batasi maksimal 20 kandidat per item sebelum semantic rerank agar embedding tidak membandingkan seluruh database secara boros.

2. **Semantic rerank**
   - Gunakan model default `LazarusNLP/all-indo-e5-small-v4`.
   - Index embedding dibuat dari gabungan:
     `keyword + sinonim + transaction_type + description + notes + contoh feedback Correct NAC`.
   - Untuk model E5, gunakan prefix:
     - Query: `query: {teks_rab}`
     - Candidate: `passage: {keyword_context}`
   - Cache model memakai `st.cache_resource`.
   - Cache embedding index memakai hash dari keyword aktif + sinonim + feedback positif.

3. **Scoring hybrid**
   - Semantic tidak boleh override exception/allowable.
   - Semantic hanya menaikkan confidence bila skor melewati threshold:
     - Ketat: 78
     - Seimbang: 70
     - Lebih sensitif: 62
   - Bila semantic cocok tetapi allowable/exception kuat, hasil turun confidence dan tetap diberi alasan audit.

4. **Fallback**
   - Jika `sentence-transformers` gagal import, model gagal download, atau memori cloud habis, app otomatis kembali ke lexical mode: exact + sinonim + fuzzy + allowable + exception.
   - UI Settings harus menampilkan status: `Semantic aktif`, `Fallback lexical`, atau `Model gagal dimuat`.

## Rencana Implementasi

- Rilis target: `v1.2.0 - Indonesian Semantic Matching Lite`.
- Tambahkan dependency opsional terkontrol:
  - `sentence-transformers`
  - hindari `scikit-learn` bila tidak wajib, karena cosine similarity sudah bisa dihitung dengan NumPy.
- Ubah default model setting ke `LazarusNLP/all-indo-e5-small-v4`, tetapi semantic tetap `Nonaktif` secara default untuk menjaga cold start Streamlit gratis.
- Perbaiki `modules/vector_indexer.py` agar membuat index dari konteks keyword lengkap, bukan hanya nama keyword.
- Tambah kolom audit hasil:
  - `semantic_candidate_text`
  - `semantic_candidate_source`
  - `semantic_reason`
  - `semantic_model`
- Tambah panel Settings:
  - model aktif,
  - status model,
  - jumlah kandidat dalam index,
  - tombol `Rebuild Semantic Index`.
- Tambah evaluasi internal kecil di test:
  - pasangan positif sinonim/parafrasa NAC,
  - pasangan negatif allowable/teknis,
  - benchmark waktu untuk 90 keyword seed NAC 2026.

## Test Plan

- `hidangan peserta rapat` cocok ke `Bahan Makanan dan Konsumsi`.
- `publikasi running text kantor` cocok ke `Iklan / Brosur / Spanduk / Publikasi / Banner`.
- `alihdaya gedung satpam taman` cocok ke `Management Building`.
- `perbaikan jaringan transmisi` tidak naik menjadi NAC karena konteks teknis.
- `konsumsi bahan bakar genset` tetap rendah karena allowable/exception.
- Bila model semantic dimatikan atau gagal load, hasil review tetap berjalan tanpa exception.
- Export Excel/PDF tetap memuat confidence, keyword, `Prosentase NAC`, `Type of Transaction`, dan alasan semantic bila ada.

## Keputusan Default

- Untuk Streamlit gratis, mode terbaik adalah **semantic lite opt-in**: dependency dan code siap, tetapi semantic default tetap `Nonaktif`.
- Model pertama yang direkomendasikan adalah `LazarusNLP/all-indo-e5-small-v4`.
- `BAAI/bge-m3` tidak dijadikan opsi cloud default.
- Tidak memakai API eksternal agar dokumen finance tidak dikirim keluar aplikasi.
