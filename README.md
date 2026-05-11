# RAB NAC Reviewer Streamlit

RAB NAC Reviewer adalah aplikasi Streamlit untuk membantu reviewer finance melakukan review awal dokumen RAB dan mendeteksi potensi NAC. Aplikasi ini tidak menggantikan keputusan reviewer; hasil deteksi wajib divalidasi terhadap PMK, kebijakan internal, dan konteks pekerjaan.

Versi aktif: `v1.0.0 - Streamlit Migration and Finance Review Workspace`.

## Fitur

- Upload RAB Excel, CSV, PDF digital, PDF scan, dan gambar.
- Parser Excel RAB Indonesia dengan dukungan judul pekerjaan, section, item, volume, satuan, harga satuan, dan total.
- Deteksi NAC hybrid: exact keyword, sinonim, fuzzy matching, semantic matching opsional, allowable competitor, exception, dan feedback historis.
- Database SQLite lokal untuk keyword, sinonim, allowable keyword, exception, settings, dan feedback.
- Export PDF ringkasan potensi NAC, PDF seluruh material, Excel seluruh material, dan database keyword.
- Backup dan restore SQLite dari UI.
- Siap deploy ke Streamlit Community Cloud gratis.

## Cara Pakai Web

1. Buka aplikasi Streamlit.
2. Masuk ke halaman `Review RAB`.
3. Upload file RAB. Format paling disarankan adalah `.xlsx` atau `.csv`.
4. Cek pesan deteksi kolom dan preview data.
5. Tekan `Run NAC Review`.
6. Baca tabel `Temuan prioritas` untuk item confidence `Sedang`, `Tinggi`, dan `Sangat tinggi`.
7. Buka `Tabel seluruh item RAB` untuk melihat semua material, termasuk confidence rendah.
8. Isi `Feedback reviewer` bila ada false positive, false negative, atau sinonim baru.
9. Gunakan bagian `Export hasil` untuk membuat PDF atau Excel dokumentasi review.

## Deploy Gratis ke Streamlit Community Cloud

1. Pastikan repo GitHub berisi file ini di root:
   - `streamlit_app.py`
   - `requirements.txt`
   - `packages.txt`
   - `.streamlit/config.toml`
   - folder `modules/`
   - folder `data/` berisi template/seed, bukan `app.db`
2. Buka [share.streamlit.io](https://share.streamlit.io).
3. Login dengan GitHub.
4. Pilih `Create app`.
5. Pilih repository `keuanganuptgrsk/rab_nac_reviewer_streamlit`.
6. Branch: `main`.
7. Main file path: `streamlit_app.py`.
8. Klik `Deploy`.

Catatan penting: Streamlit Community Cloud gratis cocok untuk penggunaan ringan. SQLite di hosting gratis bersifat praktis, tetapi tetap perlu backup rutin dari tombol `Buat Backup Database`, terutama setelah menambah keyword atau feedback penting.

## Menjalankan Lokal

```powershell
cd "D:\17. Aplikasi NAC streamlit version"
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

Buka URL yang muncul, biasanya `http://localhost:8501`.

## Testing Lokal

```powershell
cd "D:\17. Aplikasi NAC streamlit version"
.\.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Database dan Backup

- Database default dibuat otomatis di `data/app.db`.
- File `data/app.db` tidak dikomit ke GitHub.
- Untuk backup, buka `Database NAC`, klik `Buat Backup Database`, lalu download file SQLite.
- Untuk restore, upload file backup SQLite pada bagian `Restore dari backup SQLite`.
- Env var opsional:
  - `RAB_NAC_DB_PATH`: lokasi file SQLite.
  - `RAB_NAC_DATA_DIR`: lokasi folder data.
  - `RAB_NAC_EXPORT_DIR`: lokasi file export.
  - `RAB_NAC_UPLOAD_DIR`: lokasi file upload sementara.

## OCR

OCR memakai Tesseract melalui `pytesseract`. Di Streamlit Cloud, `packages.txt` memasang:

```text
tesseract-ocr
tesseract-ocr-eng
tesseract-ocr-ind
```

Untuk Windows lokal, install Tesseract OCR dan pastikan command `tesseract` tersedia di `PATH`.

## Semantic Matching

Semantic matching default `Nonaktif` karena `sentence-transformers` berat untuk hosting gratis. Jika ingin mengaktifkan lokal, install manual:

```powershell
python -m pip install sentence-transformers scikit-learn
```

Lalu buka `Settings` dan ubah `Deteksi Sinonim/Parafrasa Otomatis` ke `Aktif`.

## Versioning dan Rollback

Rilis ini ditandai sebagai tag git `v1.0.0`.

Rollback lokal:

```powershell
git fetch --tags
git checkout v1.0.0
```

Rollback deploy Streamlit Cloud:

1. Buka app di Streamlit Community Cloud.
2. Masuk ke settings app.
3. Deploy ulang branch/tag yang ingin dipakai, atau kembalikan branch `main` ke commit/tag stabil dari GitHub.

## Batasan

- Hasil deteksi bukan keputusan final.
- PDF scan dan gambar bergantung pada kualitas OCR.
- SQLite gratis mudah dipakai, tetapi bukan pengganti database production multi-user yang kuat.
- Jangan upload dokumen finance sensitif ke cloud publik bila kebijakan internal melarang pemrosesan di layanan pihak ketiga.
