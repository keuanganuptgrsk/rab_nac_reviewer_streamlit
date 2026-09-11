from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ColumnMapping:
    role: str
    column_index: int | None
    column_label: str = ""
    header_text: str = ""
    score: float = 0.0
    header_score: float = 0.0
    value_score: float = 0.0
    arithmetic_score: float = 0.0
    structure_score: float = 0.0
    runner_up_score: float = 0.0
    ambiguous: bool = False
    confirmed_manually: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MappingDiagnostic:
    region_id: str
    confidence: float
    confidence_label: str
    header_rows: list[int] = field(default_factory=list)
    mappings: dict[str, ColumnMapping] = field(default_factory=dict)
    arithmetic_failures: int = 0
    hidden_rows_skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    review_blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mappings"] = {key: value.to_dict() for key, value in self.mappings.items()}
        return data


@dataclass
class TableRegion:
    region_id: str
    sheet: str
    header_start: int
    header_end: int
    data_start: int
    data_end: int
    diagnostic: MappingDiagnostic
    parser_strategy: str = "adaptive_excel"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["diagnostic"] = self.diagnostic.to_dict()
        return data


@dataclass
class RABItem:
    source_id: str
    source_file: str
    source_hash: str
    source_location: str
    page_or_sheet: str
    source_row: int | None
    source_coordinate: str
    item_no: str
    display_sequence: int
    judul_rab: str
    section: str
    item_per_rab: str
    unit: str = ""
    volume: float | None = None
    material_unit_price: float | None = None
    service_unit_price: float | None = None
    unit_price: float | None = None
    material_total: float | None = None
    service_total: float | None = None
    total_price: float | None = None
    notes: str = ""
    raw_values: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    parser_strategy: str = "adaptive_excel"
    parser_confidence: float = 0.0
    parser_warnings: list[str] = field(default_factory=list)
    source_quality: str = "table"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "row_id": self.item_no or str(self.display_sequence),
                "item_description": self.item_per_rab,
                "original_text": self.item_per_rab,
                "review_text": " | ".join(
                    part for part in (self.judul_rab, self.section, self.item_per_rab) if part
                ),
                "sheet": self.page_or_sheet,
            }
        )
        return data


@dataclass
class ParsedDocument:
    source_file: str
    source_hash: str
    parser_strategy: str
    items: list[RABItem] = field(default_factory=list)
    regions: list[TableRegion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review_blocked: bool = False
    source_quality: str = "table"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "source_hash": self.source_hash,
            "parser_strategy": self.parser_strategy,
            "items": [item.to_dict() for item in self.items],
            "regions": [region.to_dict() for region in self.regions],
            "warnings": list(self.warnings),
            "review_blocked": self.review_blocked,
            "source_quality": self.source_quality,
        }


def confidence_label(score: float) -> str:
    if score >= 85:
        return "Tinggi"
    if score >= 65:
        return "Sedang"
    return "Rendah"
