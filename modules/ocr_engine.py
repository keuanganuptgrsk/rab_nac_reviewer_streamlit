from pathlib import Path
from tempfile import TemporaryDirectory


def _easyocr_text(image_path):
    import easyocr

    reader = easyocr.Reader(["id", "en"], gpu=False)
    result = reader.readtext(str(image_path), detail=0)
    return "\n".join(result)


def _paddleocr_text(image_path):
    from paddleocr import PaddleOCR

    ocr = _build_paddleocr()
    result = ocr.ocr(str(image_path), cls=True)
    lines = []
    for page in result or []:
        if isinstance(page, dict):
            texts = page.get("rec_texts") or page.get("texts") or []
            lines.extend(str(text) for text in texts if text)
            continue
        for item in page or []:
            if item and len(item) > 1:
                lines.append(str(item[1][0]))
    return "\n".join(lines)


def _build_paddleocr():
    from paddleocr import PaddleOCR

    attempts = [
        {"use_angle_cls": True, "lang": "latin", "show_log": False},
        {"use_angle_cls": True, "lang": "en", "show_log": False},
        {"lang": "latin"},
        {"lang": "en"},
    ]
    last_error = None
    for kwargs in attempts:
        try:
            return PaddleOCR(**kwargs)
        except Exception as exc:
            last_error = exc
    raise last_error


def _tesseract_text(image_path):
    import pytesseract
    from PIL import Image, ImageOps

    with Image.open(image_path) as image:
        image = ImageOps.grayscale(image)
        width, height = image.size
        if width < 1800:
            scale = 1800 / max(width, 1)
            image = image.resize((int(width * scale), int(height * scale)))
        image = ImageOps.autocontrast(image)
        return pytesseract.image_to_string(image, lang="ind+eng", config="--psm 6")


def extract_text_from_image(image_path, mode="auto"):
    path = Path(image_path)
    errors = []
    engines = ["tesseract", "paddleocr", "easyocr"] if mode in ("auto", "", None) else [mode]
    for engine in engines:
        if engine == "disabled":
            return "", "OCR dinonaktifkan."
        try:
            if engine == "easyocr":
                text = _easyocr_text(path)
            elif engine == "paddleocr":
                text = _paddleocr_text(path)
            elif engine == "tesseract":
                text = _tesseract_text(path)
            else:
                continue
            if text.strip():
                return text, f"OCR berhasil menggunakan {engine}."
        except Exception as exc:
            errors.append(f"{engine}: {exc}")
    return "", "OCR tidak tersedia/berhasil. Pastikan dependency OCR terpasang, atau upload Excel/CSV/PDF berbasis teks. " + " | ".join(errors[:3])


def extract_text_from_pdf_scan(pdf_path, mode="auto", max_pages=25):
    if mode == "disabled":
        return "", "OCR dinonaktifkan."
    try:
        import fitz
    except Exception as exc:
        return "", f"PyMuPDF tidak tersedia untuk render OCR: {exc}"
    texts, notes = [], []
    with TemporaryDirectory(prefix="rab_nac_ocr_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        with fitz.open(pdf_path) as doc:
            total_pages = len(doc)
            pages_to_process = min(total_pages, max_pages)
            for i in range(pages_to_process):
                page = doc[i]
                pix = page.get_pixmap(dpi=220, alpha=False)
                tmp = tmp_root / f"page_{i + 1}.png"
                pix.save(tmp)
                text, note = extract_text_from_image(tmp, mode)
                texts.append(text)
                notes.append(f"Halaman {i+1}: {note}")
            if total_pages > max_pages:
                notes.append(f"OCR dibatasi {max_pages} dari {total_pages} halaman agar tetap ringan di hosting gratis.")
    return "\n".join(texts), " ".join(notes)
