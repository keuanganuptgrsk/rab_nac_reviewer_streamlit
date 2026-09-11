from __future__ import annotations

import contextlib
import io
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from .adaptive_parser import file_sha256, parse_dataframe_tables
from .rab_models import MappingDiagnostic, ParsedDocument, RABItem, TableRegion


def extract_text_from_pdf(file_path):
    """Compatibility text extractor used by OCR fallback tests and callers."""
    import fitz

    chunks = []
    with fitz.open(file_path) as document:
        for page_no, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                chunks.append({"page_or_sheet": f"Page {page_no}", "text": text})
    scanned = not any(chunk["text"] for chunk in chunks)
    warning = (
        f"Berhasil ekstrak teks dari {len(chunks)} halaman PDF digital."
        if not scanned
        else "PDF tidak memiliki text layer yang cukup; OCR diperlukan."
    )
    return chunks, warning, scanned


def parse_pdf_document(
    file_path: str | Path,
    manual_mappings: dict[str, dict[str, Any]] | None = None,
) -> ParsedDocument:
    import fitz

    path = Path(file_path)
    source_hash = file_sha256(path)
    document = ParsedDocument(path.name, source_hash, "adaptive_pdf", source_quality="digital_pdf")
    with fitz.open(path) as pdf:
        if not pdf.page_count:
            document.review_blocked = True
            document.warnings.append("PDF kosong.")
            return document
        title = _document_title(pdf) or path.stem
        table_document = _parse_pdf_tables(
            path,
            pdf,
            source_hash,
            title,
            manual_mappings or {},
        )
        if table_document.items:
            return table_document
        page_blocks = [_page_blocks(page, number + 1) for number, page in enumerate(pdf)]
        repeated = _repeated_margin_text(page_blocks, len(page_blocks))
        sequence = 0
        active_section = ""
        for page_no, blocks in enumerate(page_blocks, start=1):
            page_items = []
            for block in blocks:
                if block["normalized"] in repeated:
                    continue
                text = block["text"]
                if not text or _is_page_noise(text):
                    continue
                if _looks_like_section(text):
                    active_section = text
                    continue
                for part_no, part in enumerate(_split_block(text), start=1):
                    sequence += 1
                    coordinate = f"page{page_no}:block{block['index']}.{part_no}"
                    item = RABItem(
                        source_id=f"{source_hash[:12]}:PDF!{coordinate}",
                        source_file=path.name,
                        source_hash=source_hash,
                        source_location=coordinate,
                        page_or_sheet=f"Page {page_no}",
                        source_row=None,
                        source_coordinate=coordinate,
                        item_no=str(sequence),
                        display_sequence=sequence,
                        judul_rab=title,
                        section=active_section,
                        item_per_rab=part,
                        raw_values={"block_bbox": block["bbox"], "block_text": text},
                        provenance={"description": "source", "financial_fields": "missing"},
                        parser_strategy="pdf_coordinate_blocks",
                        parser_confidence=72.0,
                        parser_warnings=["PDF diproses sebagai blok teks; komponen angka tidak diasumsikan."],
                        source_quality="digital_pdf",
                    )
                    page_items.append(item)
            diagnostic = MappingDiagnostic(
                region_id=f"PDF:page{page_no}",
                confidence=72.0,
                confidence_label="Sedang",
                header_rows=[],
                warnings=["Region PDF memakai koordinat blok dan tidak mengarang mapping harga."],
                review_blocked=False,
            )
            document.regions.append(
                TableRegion(
                    region_id=f"PDF:page{page_no}",
                    sheet=f"Page {page_no}",
                    header_start=0,
                    header_end=0,
                    data_start=1,
                    data_end=len(blocks),
                    diagnostic=diagnostic,
                    parser_strategy="pdf_coordinate_blocks",
                )
            )
            document.items.extend(page_items)
    if not document.items:
        document.review_blocked = True
        document.warnings.append("PDF tidak memiliki text layer yang cukup; OCR diperlukan.")
    return document


def _parse_pdf_tables(
    path: Path,
    pdf: Any,
    source_hash: str,
    title: str,
    manual_mappings: dict[str, dict[str, Any]],
) -> ParsedDocument:
    document = ParsedDocument(path.name, source_hash, "pdf_coordinate_tables", source_quality="digital_pdf")
    sequence = 0
    for page_no, page in enumerate(pdf, start=1):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                located = page.find_tables()
        except Exception as exc:
            document.warnings.append(f"Page {page_no}: deteksi tabel dilewati ({str(exc)[:120]}).")
            continue
        for table_no, table in enumerate(getattr(located, "tables", []), start=1):
            matrix = table.extract()
            if not matrix or len(matrix) < 2:
                continue
            header_names = [str(value or "").strip() for value in getattr(table.header, "names", [])]
            if header_names and not _matrix_has_header(matrix):
                matrix = [header_names] + matrix
            width = max((len(row) for row in matrix), default=0)
            if width < 2:
                continue
            normalized = [list(row) + [None] * (width - len(row)) for row in matrix]
            table_name = f"Page {page_no} Table {table_no}"
            parsed = parse_dataframe_tables(
                path,
                {table_name: pd.DataFrame(normalized)},
                "pdf_coordinate_table",
                manual_mappings,
                source_hash,
            )
            for item in parsed.items:
                sequence += 1
                row_number = item.source_row or sequence
                coordinate = f"page{page_no}:table{table_no}:row{row_number}"
                item.source_id = f"{source_hash[:12]}:PDF!{coordinate}"
                item.source_location = coordinate
                item.page_or_sheet = f"Page {page_no}"
                item.source_coordinate = coordinate
                item.display_sequence = sequence
                item.judul_rab = title
                item.parser_strategy = "pdf_coordinate_table"
                item.source_quality = "digital_pdf"
                item.raw_values["table_bbox"] = [round(float(value), 2) for value in table.bbox]
            for region in parsed.regions:
                region.sheet = f"Page {page_no}"
                region.parser_strategy = "pdf_coordinate_table"
                region.diagnostic.region_id = region.region_id
            document.items.extend(parsed.items)
            document.regions.extend(parsed.regions)
            document.warnings.extend(parsed.warnings)
            if parsed.items and parsed.review_blocked:
                document.review_blocked = True
    return document


def _matrix_has_header(matrix: list[list[Any]]) -> bool:
    first_rows = " ".join(
        str(value or "").lower()
        for row in matrix[:3]
        for value in row
    )
    description = any(token in first_rows for token in ("uraian", "deskripsi", "nama barang", "pekerjaan"))
    numeric = any(token in first_rows for token in ("volume", "vol", "qty", "harga", "total", "jumlah"))
    return description and numeric


def ocr_text_document(file_path: str | Path, text: str, source_label: str = "OCR") -> ParsedDocument:
    path = Path(file_path)
    source_hash = file_sha256(path)
    document = ParsedDocument(path.name, source_hash, "ocr_text_fallback", source_quality="ocr")
    parts = _split_block(text, max_length=700)
    for sequence, part in enumerate(parts, start=1):
        coordinate = f"ocr:{sequence}"
        document.items.append(
            RABItem(
                source_id=f"{source_hash[:12]}:{source_label}!{coordinate}",
                source_file=path.name,
                source_hash=source_hash,
                source_location=coordinate,
                page_or_sheet=source_label,
                source_row=None,
                source_coordinate=coordinate,
                item_no=str(sequence),
                display_sequence=sequence,
                judul_rab=path.stem,
                section="",
                item_per_rab=part,
                raw_values={"ocr_text": part},
                provenance={"description": "ocr", "financial_fields": "missing"},
                parser_strategy="ocr_text_fallback",
                parser_confidence=48.0,
                parser_warnings=["OCR tidak menyediakan struktur tabel tepercaya; validasi redaksi secara manual."],
                source_quality="ocr",
            )
        )
    diagnostic = MappingDiagnostic(
        region_id=f"{source_label}:text",
        confidence=48.0,
        confidence_label="Rendah",
        warnings=["Struktur OCR ber-confidence rendah; tidak ada angka yang direkonstruksi."],
        review_blocked=True,
    )
    document.regions.append(TableRegion(f"{source_label}:text", source_label, 0, 0, 1, len(parts), diagnostic, "ocr_text_fallback"))
    document.review_blocked = bool(parts)
    if not parts:
        document.warnings.append("OCR tidak menghasilkan teks yang dapat direview.")
    return document


def _document_title(pdf: Any) -> str:
    page = pdf[0]
    candidates = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text") or "").strip()
                if text and len(text) >= 6:
                    candidates.append((float(span.get("size") or 0), text))
    return max(candidates, default=(0, ""))[1]


def _page_blocks(page: Any, page_no: int) -> list[dict[str, Any]]:
    blocks = []
    height = float(page.rect.height or 1)
    for index, raw in enumerate(page.get_text("blocks"), start=1):
        x0, y0, x1, y1, text = raw[:5]
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if not clean:
            continue
        blocks.append(
            {
                "index": index,
                "page": page_no,
                "text": clean,
                "normalized": re.sub(r"\d+", "#", clean.lower()),
                "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                "margin": y0 <= height * 0.12 or y1 >= height * 0.88,
            }
        )
    return sorted(blocks, key=lambda item: (item["bbox"][1], item["bbox"][0]))


def _repeated_margin_text(page_blocks: list[list[dict[str, Any]]], page_count: int) -> set[str]:
    counts = Counter(
        block["normalized"]
        for blocks in page_blocks
        for block in blocks
        if block["margin"] and len(block["normalized"]) >= 4
    )
    threshold = max(2, (page_count + 1) // 2)
    return {text for text, count in counts.items() if count >= threshold}


def _split_block(text: str, max_length: int = 900) -> list[str]:
    lines = [line.strip() for line in re.split(r"[\r\n]+", str(text)) if line.strip()]
    if len(lines) <= 1:
        lines = [str(text).strip()]
    parts = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > max_length and current:
            parts.append(current)
            current = line
        else:
            current = f"{current} {line}".strip()
    if current:
        parts.append(current)
    return parts


def _looks_like_section(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    return 4 <= len(text) <= 120 and letters and sum(char.isupper() for char in letters) / len(letters) >= 0.9


def _is_page_noise(text: str) -> bool:
    normalized = text.lower().strip()
    return bool(re.fullmatch(r"(?:page|halaman)?\s*\d+(?:\s*(?:of|dari)\s*\d+)?", normalized))
