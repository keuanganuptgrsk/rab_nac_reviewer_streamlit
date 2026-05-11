from pathlib import Path


def extract_text_from_pdf(file_path):
    try:
        import fitz
    except Exception as exc:
        return [], f"PyMuPDF tidak tersedia: {exc}", True
    chunks = []
    with fitz.open(file_path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                chunks.append({"page_or_sheet": f"Halaman {i}", "text": text})
    total_len = sum(len(c["text"]) for c in chunks)
    scanned = total_len < 40
    warning = "PDF kemungkinan hasil scan; OCR diperlukan." if scanned else f"Berhasil ekstrak teks dari {Path(file_path).name}."
    return chunks, warning, scanned
