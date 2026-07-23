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
    unit_rank: int | None = None
    unit_rank_gt3: bool = False
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
            or self.unit_rank is not None
            or self.unit_rank_gt3
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
            f"rk{self.unit_rank}{'gt3' if self.unit_rank_gt3 else ''}",
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
    unit_rank, unit_rank_gt3 = _parse_unit_rank(args.get("unit_rank"))
    year_to = _parse_int(args.get("year_to"))

    return AdvancedFilters(
        ex_states=ex_states,
        std_type=_txt("std_type"),
        province=_txt("province"),
        city=_txt("city"),
        county=_txt("county"),
        product=_txt("product"),
        company=_normalize_company(_txt("company")),
        unit_rank=unit_rank,
        unit_rank_gt3=unit_rank_gt3,
        year_from=year_from,
        year_to=year_to,
    )


def _normalize_company(name: str) -> str:
    s = (name or "").strip()
    while s and s[-1] in "。，,;；.·":
        s = s[:-1].strip()
    return s


def _parse_unit_rank(value: Any) -> tuple[int | None, bool]:
    raw = (value or "").strip().lower()
    if not raw:
        return None, False
    if raw in ("gt3", "gt_3", ">3", "4+"):
        return None, True
    if raw.isdigit():
        n = int(raw)
        if n in (1, 2, 3):
            return n, False
        if n > 3:
            return None, True
    return None, False


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _looks_like_file_keyword(q: str) -> bool:
    """编号/文件名类关键词才值得扫 file_name；纯中文产品名扫文件名很慢。"""
    s = (q or "").strip()
    if not s:
        return False
    if re.search(r"[A-Za-z0-9_/\\\-.]", s):
        return True
    return len(s) >= 8


def _load_product_clusters() -> list[dict]:
    if not PRODUCT_CLUSTERS_PATH.is_file():
        return []
    try:
        data = json.loads(PRODUCT_CLUSTERS_PATH.read_text(encoding="utf-8"))
        return list(data.get("clusters") or [])
    except Exception:
        return []


def product_keywords(product: str) -> list[str]:
    """产品条件：组名/关键词/自定义输入 → 检索词列表（匹配词组时自动扩展）。"""
    from core.product_clusters import resolve_keywords

    p = (product or "").strip()
    if not p:
        return []
    resolved = resolve_keywords(p)
    kws = [str(k).strip() for k in (resolved.get("keywords") or []) if str(k).strip()]
    return kws if kws else [p]


def build_advanced_where(
    filters: AdvancedFilters,
    q: str,
    *,
    pdf_only: bool,
    std_folder: str | None,
    folder_sql: str,
    folder_args: tuple,
    param: str = "?",
) -> tuple[str, list[Any]]:
    """返回附加 WHERE 片段（含 AND 前缀）与参数。"""
    clauses: list[str] = []
    args: list[Any] = []

    q = (q or "").strip()
    if q:
        pattern = f"%{q}%"
        # 检索策略：
        # - 纯中文/短词：只扫标准名称（避免无意义的 std_id LIKE '%中文%'）
        # - 编号类：与普通检索一致（标准号前缀 + 名称），不扫 filepath，避免先查询后筛选变慢
        if _looks_like_file_keyword(q):
            # 与普通检索一致：前缀命中 std_id（可走索引）+ 名称模糊；不做 filepath 全表扫描
            prefix = f"{q}%"
            norm = re.sub(r"\s+", "", q.strip().upper()).replace("／", "/")
            clauses.append(
                f"(b.std_id LIKE {param} OR REPLACE(UPPER(b.std_id),' ','') = {param} "
                f"OR b.std_chinesename LIKE {param})"
            )
            args.extend([prefix, norm, pattern])
        else:
            clauses.append(f"b.std_chinesename LIKE {param}")
            args.append(pattern)

    if filters.ex_states:
        placeholders = ",".join(param for _ in filters.ex_states)
        clauses.append(f"b.ex_state IN ({placeholders})")
        args.extend(filters.ex_states)

    if filters.std_type:
        clauses.append(f"b.std_type LIKE {param}")
        args.append(f"%{filters.std_type}%")

    from core.unit_geo import build_geo_where, build_rank_where, needs_geo_filter

    if needs_geo_filter(filters):
        geo_sql, geo_args = build_geo_where(filters, param=param, mysql=(param == "%s"))
        if geo_sql:
            clauses.append(geo_sql.strip())
            args.extend(geo_args)

    rank_sql, rank_args = build_rank_where(filters, param=param, mysql=(param == "%s"))
    if rank_sql:
        clauses.append(rank_sql.strip())
        args.extend(rank_args)

    if filters.product:
        kws = product_keywords(filters.product)
        if kws:
            or_parts = " OR ".join([f"b.std_chinesename LIKE {param}"] * len(kws))
            clauses.append(f"({or_parts})")
            args.extend([f"%{kw}%" for kw in kws])

    # 年份：走 release_date 区间以利用索引（无发布日期的记录不纳入年份筛选）
    if filters.year_from is not None or filters.year_to is not None:
        y_from = filters.year_from
        y_to = filters.year_to
        if y_from is not None:
            clauses.append(f"b.release_date >= {param}")
            args.append(f"{y_from:04d}-01-01")
        if y_to is not None:
            clauses.append(f"b.release_date <= {param}")
            args.append(f"{y_to:04d}-12-31")

    if std_folder and folder_sql:
        fsql = folder_sql.lstrip(" AND ")
        clauses.append(fsql)
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
    product_suggestions: list[str] | None = None,
) -> dict:
    payload = {
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
    if product_suggestions is not None:
        payload["product_suggestions"] = product_suggestions
    return payload


def parse_workflow(value: Any) -> str:
    raw = (value or "").strip().lower()
    if raw in ("filter_first", "filter-first", "filter"):
        return "filter_first"
    if raw in ("search_first", "search-first", "search"):
        return "search_first"
    return "combined"


def validate_search_workflow(
    workflow: str,
    *,
    q: str,
    filters: AdvancedFilters,
) -> str | None:
    """兼容旧客户端显式 workflow；合并模式下不强制步骤顺序。"""
    q = (q or "").strip()
    if workflow in ("", "combined", "auto"):
        return None
    if workflow == "filter_first":
        if q and not filters.active():
            return "请先设置高级筛选条件，再输入关键词"
        if not q and not filters.active():
            return "请输入关键词或设置高级筛选条件"
    elif workflow == "search_first":
        if filters.active() and not q:
            return "请先输入关键词检索，再叠加高级筛选"
        if not q and not filters.active():
            return "请输入关键词或设置高级筛选条件"
    return None
