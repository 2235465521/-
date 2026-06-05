"""高级检索条件解析与 SQL 片段构建。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from config import PRODUCT_CLUSTERS_PATH


@dataclass
class AdvancedFilters:
    ex_states: list[int] = field(default_factory=list)
    std_type: str = ""
    province: str = ""
    city: str = ""
    county: str = ""
    product: str = ""
    company: str = ""
    year_from: int | None = None
    year_to: int | None = None

    def active(self) -> bool:
        return bool(
            self.ex_states
            or self.std_type
            or self.province
            or self.city
            or self.county
            or self.product
            or self.company
            or self.year_from is not None
            or self.year_to is not None
        )

    def cache_suffix(self) -> str:
        parts = [
            f"ex{','.join(map(str, self.ex_states))}",
            f"t{self.std_type}",
            f"p{self.province}|{self.city}|{self.county}",
            f"pd{self.product}",
            f"co{self.company}",
            f"y{self.year_from}-{self.year_to}",
        ]
        return "|".join(parts)


def parse_advanced_filters(args: dict[str, Any]) -> AdvancedFilters:
    ex_raw = (args.get("ex_state") or args.get("ex_states") or "").strip()
    ex_states: list[int] = []
    if ex_raw:
        for part in ex_raw.replace("，", ",").split(","):
            part = part.strip()
            if part.isdigit():
                ex_states.append(int(part))

    def _txt(key: str) -> str:
        return (args.get(key) or "").strip()

    year_from = _parse_int(args.get("year_from"))
    year_to = _parse_int(args.get("year_to"))

    return AdvancedFilters(
        ex_states=ex_states,
        std_type=_txt("std_type"),
        province=_txt("province"),
        city=_txt("city"),
        county=_txt("county"),
        product=_txt("product"),
        company=_txt("company"),
        year_from=year_from,
        year_to=year_to,
    )


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _load_product_clusters() -> list[dict]:
    if not PRODUCT_CLUSTERS_PATH.is_file():
        return []
    try:
        data = json.loads(PRODUCT_CLUSTERS_PATH.read_text(encoding="utf-8"))
        return list(data.get("clusters") or [])
    except Exception:
        return []


def product_keywords(product: str) -> list[str]:
    """产品条件：cluster id / 组名 / 关键词 → 检索词列表。"""
    p = (product or "").strip()
    if not p:
        return []
    clusters = _load_product_clusters()
    for c in clusters:
        cid = str(c.get("id") or "")
        name = str(c.get("name") or "")
        kws = [str(k).strip() for k in (c.get("keywords") or []) if str(k).strip()]
        if p == cid or p == name or p in kws:
            return kws or [p]
    return [p]


def build_advanced_where(
    filters: AdvancedFilters,
    q: str,
    *,
    pdf_only: bool,
    std_folder: str | None,
    folder_sql: str,
    folder_args: tuple,
) -> tuple[str, list[Any]]:
    """返回附加 WHERE 片段（含 AND 前缀）与参数。"""
    clauses: list[str] = []
    args: list[Any] = []

    q = (q or "").strip()
    if q:
        pattern = f"%{q}%"
        clauses.append(
            "(b.std_chinesename LIKE ? OR b.std_id LIKE ? OR EXISTS "
            "(SELECT 1 FROM std_filepath f2 WHERE f2.base_id = b.id AND f2.file_name LIKE ?))"
        )
        args.extend([pattern, pattern, pattern])

    if filters.ex_states:
        placeholders = ",".join("?" * len(filters.ex_states))
        clauses.append(f"b.ex_state IN ({placeholders})")
        args.extend(filters.ex_states)

    if filters.std_type:
        clauses.append("b.std_type LIKE ?")
        args.append(f"%{filters.std_type}%")

    for term in (filters.province, filters.city, filters.county, filters.company):
        if term:
            clauses.append("b.std_chinesename LIKE ?")
            args.append(f"%{term}%")

    if filters.product:
        kws = product_keywords(filters.product)
        if kws:
            or_parts = " OR ".join(["b.std_chinesename LIKE ?"] * len(kws))
            clauses.append(f"({or_parts})")
            args.extend([f"%{kw}%" for kw in kws])

    if filters.year_from is not None:
        clauses.append(
            "(CAST(substr(b.release_date, 1, 4) AS INTEGER) >= ? "
            "OR CAST(substr(b.std_id, -4) AS INTEGER) >= ?)"
        )
        args.extend([filters.year_from, filters.year_from])

    if filters.year_to is not None:
        clauses.append(
            "(CAST(substr(b.release_date, 1, 4) AS INTEGER) <= ? "
            "OR CAST(substr(b.std_id, -4) AS INTEGER) <= ?)"
        )
        args.extend([filters.year_to, filters.year_to])

    if std_folder and folder_sql:
        clauses.append(folder_sql.lstrip(" AND "))
        args.extend(folder_args)

    if pdf_only:
        clauses.append(
            "EXISTS (SELECT 1 FROM std_filepath f WHERE f.base_id = b.id)"
        )

    if not clauses:
        return "", []

    return " AND " + " AND ".join(clauses), args


def filter_options_payload(
    *,
    std_types: list[str],
    provinces: list[str],
    cities: list[str],
    counties: list[str],
    products: list[dict],
    companies: list[str],
) -> dict:
    return {
        "ex_states": [
            {"value": 1, "label": "现行"},
            {"value": 2, "label": "即将实施"},
            {"value": 0, "label": "废止"},
        ],
        "std_types": std_types,
        "provinces": provinces,
        "cities": cities,
        "counties": counties,
        "products": products,
        "companies": companies,
    }
