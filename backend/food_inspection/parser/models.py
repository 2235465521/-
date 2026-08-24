"""解析结果数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

@dataclass
class Record:
    status: str
    company: str
    product: str
    province: str
    city: str
    province_city: str
    unqualified_item: str
    reason: str
    category: str
    source_file: str
    source_file_name: str
    source_sheet: str
    source_province: str
    source_city: str
    sampled_unit: str = ""
    manufacturer: str = ""
    address: str = ""
    manufacturer_address: str = ""
    serial_number: str = ""
    year: str = ""


def record_to_dict(record: Record) -> dict[str, Any]:
    return asdict(record)
