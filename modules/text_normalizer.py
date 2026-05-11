import re
from functools import lru_cache


ABBREVIATIONS = {
    "by": "biaya",
    "bya": "biaya",
    "kons": "konsumsi",
    "rapat koord": "rapat koordinasi",
    "koord": "koordinasi",
    "pjln": "perjalanan",
    "perjadin": "perjalanan dinas",
    "bbm": "bahan bakar minyak",
    "genset": "generator set",
    "pemel": "pemeliharaan",
    "inst": "instalasi",
    "uji": "pengujian",
    "gardu dist": "gardu distribusi",
}


@lru_cache(maxsize=1)
def _stemmer():
    try:
        from Sastrawi.Stemmer.StemmerFactory import StemmerFactory

        return StemmerFactory().create_stemmer()
    except Exception:
        return None


def normalize_text(text, enable_stemming=False):
    """Conservative Indonesian normalization; original wording stays elsewhere."""
    if text is None:
        return ""
    value = str(text).lower()
    for src, dst in ABBREVIATIONS.items():
        value = re.sub(rf"\b{re.escape(src)}\b", dst, value)
    value = re.sub(r"[^\w\s%./,-]", " ", value)
    value = re.sub(r"[_]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if enable_stemming:
        stemmer = _stemmer()
        if stemmer:
            value = stemmer.stem(value)
    return value
