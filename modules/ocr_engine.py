import importlib.util
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory


def _module_available(module_name):
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def ocr_runtime_status():
    tesseract_ready = (
        _module_available("pytesseract")
        and _module_available("PIL")
        and shutil.which("tesseract") is not None
    )
    available_engines = []
    if tesseract_ready:
        available_engines.append("tesseract")
    if _module_available("paddleocr"):
        available_engines.append("paddleocr")
    if _module_available("easyocr"):
        available_engines.append("easyocr")

    if available_engines:
        message = "OCR tersedia pada runtime ini: " + ", ".join(available_engines) + "."
    else:
        message = (
            "OCR tidak tersedia pada hosting ini. Gunakan Excel, CSV, atau PDF berbasis teks; "
            "gambar dan PDF scan dapat diproses pada instalasi lokal yang memiliki Tesseract."
        )
    return {
        "available": bool(available_engines),
        "available_engines": available_engines,
        "tesseract_binary": shutil.which("tesseract") or "",
        "message": message,
    }


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
    if mode == "disabled":
        return "", "OCR dinonaktifkan."

    runtime = ocr_runtime_status()
    available = runtime["available_engines"]
    engines = available if mode in ("auto", "", None) else ([mode] if mode in available else [])
    if not engines:
        return "", runtime["message"]

    errors = []
    for engine in engines:
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
    return "", "OCR tersedia tetapi gagal membaca file. Coba upload Excel, CSV, atau PDF berbasis teks. " + " | ".join(errors[:3])


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
