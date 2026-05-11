from pathlib import Path

import pandas as pd


COLUMN_HINTS = {
    "item_number": ["no", "nomor", "item", "kode"],
    "work_title": ["pekerjaan", "judul", "uraian pekerjaan"],
    "description": ["uraian", "deskripsi", "keterangan", "spesifikasi"],
    "material_service_name": ["material", "barang", "jasa", "nama"],
    "volume": ["volume", "vol", "qty", "kuantitas"],
    "unit": ["satuan", "unit", "uom"],
    "unit_price": ["harga satuan", "harga", "price", "harsat"],
    "total_price": ["jumlah", "total", "subtotal", "nilai"],
    "notes": ["catatan", "notes", "remark"],
}


def load_excel_or_csv(file_path):
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            df = pd.read_csv(path)
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="latin-1")
        return {"dataframe": df, "sheet": "CSV", "warning": ""}
    sheets = pd.read_excel(path, sheet_name=None)
    first_name = next(iter(sheets))
    return {"dataframe": sheets[first_name], "sheet": first_name, "warning": f"Sheet aktif: {first_name}"}


def load_rab_excel_items(file_path):
    """Best-effort extractor for Indonesian RAB workbooks with title rows and item sheets."""
    path = Path(file_path)
    if path.suffix.lower() not in [".xlsx", ".xls"]:
        return None
    sheets = pd.read_excel(path, sheet_name=None, header=None)
    title = _extract_title(sheets) or path.stem
    rows = []
    for sheet_name, raw in sheets.items():
        sheet_upper = str(sheet_name).upper()
        if "RESUME" in sheet_upper or "EXTRA" in sheet_upper:
            continue
        if "REALISASI" in sheet_upper:
            rows.extend(_extract_realisasi_rows(raw, sheet_name, title))
        else:
            rows.extend(_extract_rab_rows(raw, sheet_name, title))
    if not rows:
        for sheet_name, raw in sheets.items():
            rows.extend(_extract_rab_rows(raw, sheet_name, title))
    if not rows:
        return None
    return pd.DataFrame(rows)


def _extract_title(sheets):
    for raw in sheets.values():
        for _, row in raw.iterrows():
            values = ["" if pd.isna(v) else str(v).strip() for v in row.tolist()]
            for idx, value in enumerate(values):
                value_l = value.lower().strip()
                if value_l in ("nama pekerjaan", "judul pekerjaan", "pekerjaan") or value_l.startswith(("pekerjaan", "pekerjaan :")):
                    for candidate in values[idx + 1 :]:
                        candidate = candidate.strip()
                        if candidate and candidate != ":":
                            return candidate[1:].strip() if candidate.startswith(":") else candidate
    return ""


def _extract_rab_rows(raw, sheet_name, title):
    rows = []
    current_section = ""
    active_group = ""
    active_number = ""
    child_index = 0
    for idx, row in raw.iterrows():
        no, desc, layout = _detect_item_position(row)
        if not desc or _is_number(desc) or _looks_like_header(desc):
            continue

        unit = _unit_for_layout(row, layout)
        volume = _volume_for_layout(row, layout)
        unit_price = _unit_price_for_layout(row, layout)
        total = _total_for_layout(row, layout)
        is_group = _looks_like_section(desc, unit, volume, unit_price, total)

        if _is_number(no):
            row_id = _clean_number(no)
            section = current_section
            rows.append(
                {
                    "row_id": row_id,
                    "judul_rab": title,
                    "item_per_rab": desc,
                    "section": section,
                    "sheet": sheet_name,
                    "volume": volume,
                    "unit": unit,
                    "unit_price": unit_price,
                    "total_price": total,
                    "notes": "",
                    "review_text": " | ".join(x for x in [title, section, desc] if x),
                }
            )
            active_number = row_id
            child_index = 0
            active_group = desc if is_group else ""
            continue

        if active_number and active_group and _has_detail(unit, volume, unit_price, total):
            child_index += 1
            row_id = f"{active_number}.{child_index}"
            rows.append(
                {
                    "row_id": row_id,
                    "judul_rab": title,
                    "item_per_rab": desc,
                    "section": active_group,
                    "sheet": sheet_name,
                    "volume": volume,
                    "unit": unit,
                    "unit_price": unit_price,
                    "total_price": total,
                    "notes": "",
                    "review_text": " | ".join(x for x in [title, active_group, desc] if x),
                }
            )
            continue

        if desc:
            current_section = desc
            active_group = ""
            active_number = ""
            child_index = 0
    return rows


def _detect_item_position(row):
    if _is_number(_cell(row, 0)) and _cell(row, 1):
        return _cell(row, 0), _cell(row, 1), "no0_desc1"
    if _is_number(_cell(row, 1)) and _cell(row, 2):
        return _cell(row, 1), _cell(row, 2), "no1_desc2"
    if _cell(row, 1) and not _is_number(_cell(row, 1)) and not _is_number(_cell(row, 0)):
        return "", _cell(row, 1), "no0_desc1"
    if _cell(row, 2) and not _is_number(_cell(row, 2)) and not _is_number(_cell(row, 1)):
        return "", _cell(row, 2), "no1_desc2"
    return "", "", "unknown"


def _unit_for_layout(row, layout):
    return _cell(row, 2) if layout == "no0_desc1" else _cell(row, 6)


def _volume_for_layout(row, layout):
    return _cell(row, 3) if layout == "no0_desc1" else _cell(row, 7)


def _unit_price_for_layout(row, layout):
    return _first_non_empty([_cell(row, 4), _cell(row, 5)]) if layout == "no0_desc1" else _cell(row, 8)


def _total_for_layout(row, layout):
    if layout == "no0_desc1":
        return _first_non_empty([_cell(row, 10), _cell(row, 6), _cell(row, 5)])
    return _first_non_empty([_cell(row, 11), _cell(row, 10), _cell(row, 9)])


def _clean_number(value):
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def _is_zeroish(value):
    text = str(value or "").strip().replace(",", "").replace(".", "")
    return text in ("", "0")


def _has_detail(unit, volume, unit_price, total):
    return bool(unit or volume or unit_price or not _is_zeroish(total))


def _looks_like_section(desc, unit, volume, unit_price, total):
    return bool(desc and not unit and not volume and not unit_price and _is_zeroish(total))


def _extract_realisasi_rows(raw, sheet_name, title):
    rows = []
    for _, row in raw.iterrows():
        item = _cell(row, 0)
        if not item or item.upper() == "REALISASI":
            continue
        total = _first_non_empty([_cell(row, 1), _cell(row, 7)])
        if not item and not total:
            continue
        rows.append(
            {
                "row_id": str(len(rows) + 1),
                "judul_rab": title,
                "item_per_rab": item,
                "section": "Realisasi",
                "sheet": sheet_name,
                "volume": "",
                "unit": "",
                "unit_price": "",
                "total_price": total,
                "notes": _cell(row, 2),
                "review_text": " | ".join(x for x in [title, "Realisasi", item, _cell(row, 2)] if x),
            }
        )
    return rows


def _cell(row, pos):
    if pos >= len(row):
        return ""
    value = row.iloc[pos]
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _first_non_empty(values):
    for value in values:
        if value not in ("", None):
            return value
    return ""


def _is_number(value):
    try:
        float(str(value).strip())
        return True
    except Exception:
        return False


def _looks_like_header(text):
    lower = str(text).lower()
    header_tokens = [
        "nama barang",
        "nama material",
        "uraian kegiatan",
        "harga satuan",
        "jumlah",
        "satuan",
    ]
    return any(token in lower for token in header_tokens) and not lower.startswith("biaya ")


def detect_columns(df):
    detected = {}
    normalized = {str(c).lower().strip(): c for c in df.columns}
    for target, hints in COLUMN_HINTS.items():
        for lc, original in normalized.items():
            if any(h in lc for h in hints):
                detected[target] = original
                break
    return detected


def combine_selected_text_columns(df, text_columns):
    if not text_columns:
        raise ValueError("Pilih minimal satu kolom teks untuk review.")
    existing = [c for c in text_columns if c in df.columns]
    combined = df[existing].fillna("").astype(str).agg(" | ".join, axis=1)
    return combined


def normalize_dataframe(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df
