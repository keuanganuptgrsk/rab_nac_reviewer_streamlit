# RAB NAC Reviewer Streamlit

RAB NAC Reviewer adalah aplikasi Streamlit untuk membantu reviewer finance melakukan review awal dokumen RAB dan mendeteksi potensi NAC. Aplikasi ini tidak menggantikan keputusan reviewer; hasil deteksi wajib divalidasi terhadap PMK, kebijakan internal, dan konteks pekerjaan.

Versi aktif: `v1.4.0 - Adaptive RAB Parser and AI Review Providers`.

## Fitur

- Upload RAB Excel, CSV, PDF digital, PDF scan, dan gambar.
- Parser adaptif XLSX, XLS, CSV, PDF digital, dan PDF OCR dengan diagnostics mapping per tabel.
- Deteksi NAC context-aware: exact keyword, sinonim, fuzzy, dan semantic dinilai terpisah pada item, subjudul, serta judul.
- Pilihan review `Python Lokal`, `OpenAI API`, dan `Gemini Flash API`; mode lokal selalu menjadi default sesi baru.
- Database SQLite lokal untuk keyword NAC 2026 Kategori A/B, sinonim, allowable keyword, exception, settings, dan feedback.
- Output review memisahkan `Prosentase NAC` sebagai aturan koreksi dan `Confidence` sebagai keyakinan klasifikasi.
- Stable source ID, provenance nilai, parser confidence, provider audit, dan sumber keputusan untuk penelusuran hasil.
- Export PDF ringkasan potensi NAC, PDF seluruh material, Excel seluruh material, Excel audit lengkap, dan database keyword.
- Backup dan restore SQLite dari UI.
- Bulk nonaktifkan, restore, dan hapus permanen keyword NAC dari tabel checkbox.
- Siap deploy ke Streamlit Community Cloud gratis.

## Cara Pakai Web

1. Buka aplikasi Streamlit.
2. Masuk ke halaman `Review RAB`.
3. Upload file RAB. Format paling disarankan adalah `.xlsx` atau `.csv`.
4. Periksa preview dan `Parser diagnostics`. Mapping rendah atau ambigu harus dikonfirmasi pada form mapping manual sebelum review.
5. Pilih `Python Lokal` untuk review offline, atau provider cloud bila credential tersedia.
6. Untuk provider cloud, periksa data yang akan dikirim lalu centang persetujuan sesi.
7. Tekan `Run NAC Review`.
8. Baca tabel `Temuan prioritas` untuk item confidence `Sedang`, `Tinggi`, dan `Sangat tinggi`.
9. Cek `Prosentase NAC`, `Status Prosentase`, dan `Type of Transaction` untuk melihat aturan koreksi yang diterapkan.
10. Baca `Confidence`, bukti match judul/subjudul/item, dan alasan keputusan sebagai audit keyakinan sistem.
11. Buka `Tabel seluruh item RAB` untuk melihat semua material, termasuk confidence rendah.
12. Isi `Feedback reviewer` bila ada false positive, false negative, atau sinonim baru.
13. Gunakan bagian `Export hasil` untuk membuat PDF atau Excel dokumentasi review.

## Parser Adaptif dan Diagnostics

- Setiap sheet dipindai untuk menemukan satu atau beberapa region tabel dan header bertingkat 1-4 baris.
- Mapping mempertimbangkan arti header, pola data, relasi aritmetika, serta posisi kolom. Workbook dengan layout berbeda boleh menghasilkan mapping yang berbeda.
- Hidden row tidak masuk preview, review, feedback, atau export. Jumlahnya tetap dicatat pada diagnostics.
- Harga satuan dapat berasal dari material, jasa, atau penjumlahan keduanya. Total memprioritaskan kolom total valid, lalu komponen total, lalu volume dikali harga satuan.
- Nilai hasil formula memakai cached value dari workbook bila tersedia. `include`, `included`, `N/A`, tanda hubung, dan blank disimpan sebagai raw marker, bukan angka nol.
- Konflik aritmetika menjadi warning dan tidak dikoreksi diam-diam.
- Mapping manual hanya berlaku untuk file dan sesi aktif; aplikasi tidak menyimpan asumsi layout tersebut sebagai aturan global.

## Cara Kerja Review Hierarkis

- `item_per_rab` adalah bukti utama dengan bobot 60%.
- `section/subjudul` memberi konteks 25%.
- `judul_rab` memberi konteks 15%.
- Dukungan transaksi yang sama pada beberapa field menaikkan konsistensi; kandidat berbeda memberi penalti konflik.
- Judul yang mengandung redaksi NAC tidak otomatis menjadikan seluruh item di bawahnya NAC. Tanpa bukti pada item, confidence dibatasi dan prosentase tidak diterapkan.
- Konteks teknis seperti pembangkit, gardu, transmisi, distribusi, operasi, dan pemeliharaan tetap dinilai melalui allowable/exception.
- Bila dua transaksi kuat memiliki prosentase berbeda, hasil ditandai `Perlu penentuan reviewer - Ambigu` tanpa angka tebakan.

`Prosentase NAC` selalu berasal dari `correction_percentage` keyword pack/PPT. Semantic score dan Confidence tidak pernah digunakan untuk menciptakan prosentase baru.

## Engine Review dan AI Provider

`Python Lokal` memakai deterministic NAC engine dan tidak melakukan network call. OpenAI/Gemini menerima seluruh baris RAB dalam batch maksimal 20 hanya setelah persetujuan eksplisit pada sesi tersebut. UI menampilkan data yang dikirim: judul, section, uraian item, dan kandidat transaksi tepercaya.

AI hanya boleh merangking maksimal lima candidate ID dari deterministic engine. Payload provider tidak memiliki field prosentase. Candidate ID asing, schema invalid, upaya menambahkan prosentase, atau konflik allowable/exception ditolak. Alternate AI baru dapat dipakai bila AI confidence minimal 80, tidak ambigu, kandidat deterministic awal di bawah 75, dan tidak ada guard conflict. Kegagalan API mempertahankan hasil deterministic sebagai fallback.

Credential dapat disimpan melalui `Manage app > Settings > Secrets` di Streamlit Community Cloud:

```toml
OPENAI_API_KEY = "isi-key-openai"
OPENAI_MODEL = "gpt-5.6-luna"
GEMINI_API_KEY = "isi-key-gemini"
GEMINI_MODEL = "gemini-3.8-flash"
```

Jangan simpan key asli di `.env.example`, source code, commit Git, database, atau file export. Status package, credential, model, dan tombol test connection tersedia pada halaman `Settings`.

## Keyword Pack NAC 2026

- Seed produksi berada di `data/nac_2026_keyword_pack.xlsx`.
- Kategori A memakai rujukan PMK 20 Tahun 2025 dan slide internal NAC 2026.
- Kategori B memakai daftar transaksi NAC Kategori B pada PPT, termasuk `Prosentase` dan `Type of Transaction`.
- Saat app start, database lama yang masih berisi seed demo sistem akan otomatis dimigrasikan ke pack `nac_2026_v1`.
- Keyword yang ditambahkan user tetap dipertahankan; lakukan backup SQLite sebelum deploy besar.
- Sumber regulasi: [JDIH Kemenkeu PMK 20 Tahun 2025](https://jdih.kemenkeu.go.id/dok/pmk-20-tahun-2025), [PDF resmi PMK](https://jdih.kemenkeu.go.id/download/e0fbc6a3-ecfb-4c4f-8f87-23854b1c01e6/2025pmkeuangan020.pdf), dan [Database Peraturan BPK](https://peraturan.bpk.go.id/Details/316100/pmk-no-20-tahun-2025).

## Deploy Gratis ke Streamlit Community Cloud

1. Pastikan repo GitHub berisi file ini di root:
   - `streamlit_app.py`
   - `requirements.txt`
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

Tambahkan API key pada Secrets hanya bila engine cloud memang akan dipakai. Aplikasi tetap berfungsi penuh dengan `Python Lokal` tanpa credential eksternal.

Catatan penting: Streamlit Community Cloud gratis cocok untuk penggunaan ringan. SQLite di hosting gratis bersifat praktis, tetapi tetap perlu backup rutin dari tombol `Buat Backup Database`, terutama setelah menambah keyword atau feedback penting.

Repo tidak memakai `packages.txt` agar build Cloud tidak bergantung pada instalasi APT Debian. Perubahan dependency dari GitHub biasanya memicu redeploy otomatis. Jika build lama masih tampil, buka `Manage app`, pilih menu tambahan, lalu klik `Reboot app`.

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
- Sebelum migrasi keyword, klik `Buat Backup Database` agar perubahan keyword lokal/cloud bisa dipulihkan.
- Untuk mengelola banyak keyword, buka `Database NAC`, centang beberapa baris pada tabel, lalu pilih `Nonaktifkan Selected`.
- Untuk restore, buka `Keyword nonaktif`, centang keyword yang ingin dikembalikan, lalu pilih `Restore Selected`.
- Untuk hapus permanen, buka panel `Hapus permanen selected`, ketik `HAPUS PERMANEN`, lalu klik tombol hapus. Gunakan hanya bila data memang tidak perlu jejak keyword/sinonim/exception.
- Untuk backup, buka `Database NAC`, klik `Buat Backup Database`, lalu download file SQLite.
- Untuk restore, upload file backup SQLite pada bagian `Restore dari backup SQLite`.
- Env var opsional:
  - `RAB_NAC_DB_PATH`: lokasi file SQLite.
  - `RAB_NAC_DATA_DIR`: lokasi folder data.
  - `RAB_NAC_EXPORT_DIR`: lokasi file export.
  - `RAB_NAC_UPLOAD_DIR`: lokasi file upload sementara.
  - `OPENAI_API_KEY` / `OPENAI_MODEL`: credential dan override model OpenAI.
  - `GEMINI_API_KEY` / `GEMINI_MODEL`: credential dan override model Gemini.

Restore database memeriksa header SQLite, integrity check, tabel, dan kolom wajib pada staging file. Database aktif hanya diganti setelah validasi berhasil; rollback backup dipakai bila inisialisasi database hasil restore gagal.

## OCR

OCR gambar dan PDF scan memakai Tesseract secara lokal. Streamlit Community Cloud tidak memasang binary Tesseract pada rilis ini agar deployment tetap stabil; gunakan Excel, CSV, atau PDF berbasis teks saat memakai Cloud.

Windows lokal:

```powershell
# Install Tesseract OCR beserta data bahasa Indonesia, lalu pastikan command tersedia.
tesseract --version
tesseract --list-langs
```

Linux lokal:

```bash
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-eng tesseract-ocr-ind
```

Halaman `Settings` menampilkan status OCR runtime. Jika statusnya `Tidak tersedia pada hosting ini`, file selain gambar/PDF scan tetap dapat direview seperti biasa.

## Semantic Bahasa Indonesia

Semantic matching default `Nonaktif` agar app tetap ringan saat pertama dibuka. Rilis `v1.2.0` sudah memasang `sentence-transformers` di `requirements.txt`, sehingga Streamlit Community Cloud dapat menjalankan semantic mode tanpa API eksternal.

Model default: `LazarusNLP/all-indo-e5-small-v4`.

Cara mengaktifkan:

1. Buka `Settings`.
2. Pada `Deteksi Sinonim/Parafrasa Otomatis`, pilih `Aktif`.
3. Pilih model semantic. Rekomendasi Cloud: `LazarusNLP/all-indo-e5-small-v4`.
4. Klik `Simpan Settings`.
5. Jalankan review seperti biasa.

First run di Streamlit Cloud bisa lebih lama karena model Hugging Face perlu diunduh dan dimuat. Jika Cloud terasa lambat atau muncul resource limit, kembali ke `Settings` dan pilih `Nonaktif`; app otomatis kembali ke lexical mode: exact keyword, sinonim manual, fuzzy, allowable, exception, dan feedback.

Roadmap dan catatan teknis semantic berada di [docs/semantic_similarity_indonesia_plan.md](docs/semantic_similarity_indonesia_plan.md).

## Versioning dan Rollback

Rilis ini ditandai sebagai tag git `v1.4.0`.

Rollback lokal:

```powershell
git fetch --tags
git checkout v1.3.0
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

Arsitektur, boundary keamanan, dan roadmap penggunaan enterprise dijelaskan di [docs/architecture_v1_4.md](docs/architecture_v1_4.md).
