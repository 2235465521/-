"""食品安全监督抽查数据解析公共 API。"""

from __future__ import annotations

from config import DATA_ROOT
from food_inspection.parser.classification import (
    is_non_inspection_detail_file,
    is_planned_sampling_file,
)
from food_inspection.parser.food_scope import (
    is_food_product,
    is_non_food_inspection_file,
)
from food_inspection.parser.constants import COLUMN_ALIASES, SCAN_FILE_EXTENSIONS
from food_inspection.parser.fields import (
    normalize_failure_item_name,
    resolve_folder_city,
    resolve_folder_province,
    resolve_record_city,
    resolve_record_failure_items,
    resolve_record_unqualified_item,
    resolve_unqualified_fields,
)
from food_inspection.parser.io import _read_all_sheets
from food_inspection.parser.layout import (
    _build_column_map,
    _find_extended_header_row,
    _find_header_row,
)
from food_inspection.parser.models import Record, record_to_dict
from food_inspection.parser.parse import iter_excel_files, parse_file
from food_inspection.parser.text import (
    _clean,
    is_inspection_agency,
    is_invalid_company,
    normalize_company_name,
    normalize_product_name,
    strip_product_enumeration_suffix,
)

__all__ = [
    "COLUMN_ALIASES",
    "DATA_ROOT",
    "Record",
    "SCAN_FILE_EXTENSIONS",
    "_build_column_map",
    "_clean",
    "_find_extended_header_row",
    "_find_header_row",
    "_read_all_sheets",
    "is_inspection_agency",
    "is_invalid_company",
    "is_non_inspection_detail_file",
    "is_non_food_inspection_file",
    "is_food_product",
    "is_planned_sampling_file",
    "iter_excel_files",
    "normalize_company_name",
    "normalize_failure_item_name",
    "normalize_product_name",
    "strip_product_enumeration_suffix",
    "parse_file",
    "record_to_dict",
    "resolve_folder_city",
    "resolve_folder_province",
    "resolve_record_city",
    "resolve_record_failure_items",
    "resolve_record_unqualified_item",
    "resolve_unqualified_fields",
]
