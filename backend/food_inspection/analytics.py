"""不合格数据统计分析。"""

from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from typing import Any

from food_inspection.date_scope import filter_records_by_date_range
from food_inspection.category_junk import is_junk_category
from food_inspection.parser import (
    is_invalid_company,
    is_inspection_agency,
    normalize_company_name,
    normalize_failure_item_name,
    normalize_product_name,
    resolve_folder_province,
    resolve_record_city,
    resolve_record_failure_items,
    resolve_record_unqualified_item,
)
from food_inspection.parser.fields import (
    _FAILURE_ITEM_POOL_JUNK_MARKERS,
    _compact_failure_item_text,
    _is_junk_failure_item,
    _is_org_failure_item_name,
    sanitize_product_name,
)
from food_inspection.parser.text import _clean


def _record_sampled_company(record: dict[str, Any]) -> str:
    name = normalize_company_name(
        record.get("sampled_company_name")
        or record.get("sampled_company")
        or record.get("sampled_unit")
        or ""
    )
    if not name:
        legacy = normalize_company_name(record.get("company") or "")
        unit = normalize_company_name(record.get("sampled_unit") or "")
        if legacy and (not unit or legacy == unit):
            name = legacy
    if not name or name == "未知公司" or is_invalid_company(name) or is_inspection_agency(name):
        return ""
    return name


def _record_manufacturer(record: dict[str, Any]) -> str:
    name = normalize_company_name(
        record.get("manufacturer_name") or record.get("manufacturer") or ""
    )
    if name in ("/", "—", "-", "无", "暂无", "不详"):
        return ""
    if not name or name == "未知公司" or is_invalid_company(name) or is_inspection_agency(name):
        return ""
    sampled = _record_sampled_company(record)
    if sampled and name == sampled:
        return ""
    return name


def _record_company(record: dict[str, Any]) -> str:
    """兼容旧逻辑：统计用单位 = 被抽检单位。"""
    return _record_sampled_company(record)


def _record_manufacturer_address(record: dict[str, Any]) -> str:
    return _clean(record.get("manufacturer_address") or "")


def _record_sampled_address(record: dict[str, Any]) -> str:
    return _clean(record.get("sampled_company_address") or record.get("address") or "")


def _record_product(record: dict[str, Any]) -> str:
    return sanitize_product_name(record.get("product") or "")


_TABLEWARE_KEYWORDS: tuple[str, ...] = (
    "碗", "筷", "碟", "盘", "勺", "盆", "餐饮具", "餐具", "骨碟", "菜碟",
    "汤碗", "饭碗", "面碗", "菜碗", "料碗", "蘸料碟", "消毒", "复用"
)
_TABLEWARE_EXCLUDE: tuple[str, ...] = (
    "大米", "盘锦", "牛腩", "烧鸭", "叉烧", "披萨", "比萨", "套餐",
    "宽粉", "火锅", "麻辣烫", "茶叶", "食用油", "菜籽", "坚果"
)


def canonical_tableware_product_name(name: str) -> str:
    if not name:
        return ""
    text = str(name).strip()
    text = re.sub(r"[.。…,:;，；\s]+$", "", text).strip()
    if not any(ex in text for ex in _TABLEWARE_EXCLUDE) and any(kw in text for kw in _TABLEWARE_KEYWORDS):
        return "复用餐饮具"
    return text


def _record_sub_category(record: dict[str, Any]) -> str:
    raw = (record.get("minor_category") or record.get("sub_category") or "").strip()
    return canonical_tableware_product_name(raw)


def _normalize_rank_product(name: str) -> str:
    """榜单产品键：将碗/筷/碟/盘等餐具统一归为「复用餐饮具」。"""
    return canonical_tableware_product_name(name)


def _record_is_mappable(record: dict[str, Any]) -> bool:
    return bool(_record_sub_category(record))


def _mapped_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if _record_is_mappable(record)]


def _rollup_product_totals_by_subcategory(
    product_totals: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    from food_inspection.food_category_map import lookup_sub_category

    out: dict[str, dict[str, int]] = defaultdict(lambda: {"qualified": 0, "unqualified": 0})
    for food, counts in product_totals.items():
        sub = lookup_sub_category(food) or lookup_sub_category(sanitize_product_name(food))
        if not sub:
            continue
        bucket = out[sub]
        bucket["qualified"] += int(counts.get("qualified") or 0)
        bucket["unqualified"] += int(counts.get("unqualified") or 0)
    return out


def _city_stat_key(record: dict[str, Any], province_filter: str) -> str:
    """统计用城市键：优先文件夹城市；全国范围时带省份前缀。"""
    city = resolve_record_city(record)
    if not city:
        return ""
    if province_filter and province_filter != "全部":
        return city
    prov = resolve_folder_province(record)
    if prov:
        return f"{prov} / {city}"
    return city


def _filter_by_city(records: list[dict[str, Any]], city: str) -> list[dict[str, Any]]:
    if not city or city == "全部":
        return records
    return [r for r in records if resolve_record_city(r) == city]


def _split_items(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return ["未标注"]

    parts = re.split(r"[、;；|｜丨/]+", text)
    if len(parts) == 1:
        # 铅(Pb),总砷(As) 等英文逗号并列；排除 2,4-滴 等数字逗号
        parts = re.split(r"[,，](?=\D)", text)

    cleaned: list[str] = []
    for part in parts:
        name = normalize_failure_item_name(part.strip())
        if name and name not in cleaned:
            cleaned.append(name)

    if cleaned:
        return cleaned

    single = normalize_failure_item_name(text)
    return [single] if single else ["未标注"]


def count_qualified_items(records: list[dict[str, Any]]) -> int:
    """合格项次：每条合格记录计 1 项（一个样品）。"""
    return len(records)


def count_unqualified_items(records: list[dict[str, Any]]) -> int:
    """不合格项次：每条记录内不合格项目数之和；无项目名时计 1。"""
    total = 0
    for record in records:
        items = _record_failure_items(record)
        total += len(items) if items else 1
    return total


def _unqualified_item_weight(record: dict[str, Any]) -> int:
    items = _record_failure_items(record)
    return len(items) if items else 1


def _record_failure_items(record: dict[str, Any]) -> list[str]:
    """从记录解析不合格项目名；无法解析时返回空列表（统计层归入「其他」）。"""
    items = resolve_record_failure_items(record)
    if items:
        return items
    raw = record.get("standard_unqualified_items") or record.get("standard_unqualified_item") or ""
    if raw:
        return _split_items(str(raw))
    return []


def _accumulate_failure_items(counter: Counter[str], record: dict[str, Any]) -> None:
    _accumulate_failure_items_from_list(counter, _record_failure_items(record))


def _accumulate_failure_items_from_list(counter: Counter[str], items: list[str]) -> None:
    if not items:
        return
    for name in items:
        key = normalize_failure_item_name(name)
        if not key or key in ("未标注", "其他"):
            continue
        if _is_junk_failure_item(key):
            continue
        if _is_org_failure_item_name(key):
            continue
        if any(marker in key for marker in _FAILURE_ITEM_POOL_JUNK_MARKERS):
            continue
        counter[key] += 1


def _finalize_item_counter(counter: Counter[str]) -> Counter[str]:
    """去掉无效/meta 原因，仅保留可展示的项目名。"""
    out: Counter[str] = Counter()
    for name, count in counter.items():
        if name in ("未标注", "其他"):
            continue
        key = normalize_failure_item_name(name)
        if not key or key in ("未标注", "其他"):
            continue
        if _is_junk_failure_item(key):
            continue
        if _is_org_failure_item_name(key):
            continue
        if any(marker in key for marker in _FAILURE_ITEM_POOL_JUNK_MARKERS):
            continue
        out[key] += count
    return out


def _item_breakdown_from_counter(counter: Counter[str], limit: int = 8) -> list[dict[str, Any]]:
    finalized = _finalize_item_counter(counter)
    if not finalized:
        return []
    total = sum(finalized.values()) or 1
    named = sorted(
        finalized.items(),
        key=lambda item: (-item[1], item[0]),
    )
    head_limit = limit
    head = named[:head_limit]
    tail_count = sum(count for _, count in named[head_limit:])
    ranked = list(head)
    if tail_count > 0 and len(ranked) < limit:
        ranked.append(("其他", tail_count))
    elif tail_count > 0 and ranked:
        ranked[-1] = (ranked[-1][0], ranked[-1][1] + tail_count)
    return _to_ratio(ranked, total, limit=limit)


def _extract_failure_reason(record: dict[str, Any]) -> str:
    """仅使用不合格项目名称，分类（如食用农产品）不算原因。"""
    items = _record_failure_items(record)
    if items:
        key = normalize_failure_item_name(items[0])
        if key and not _is_junk_failure_item(key):
            return key
        return items[0] if items[0] and not _is_junk_failure_item(items[0]) else "其他"
    return "其他"


def _summarize_main_reasons(reason_counter: Counter, limit: int = 3) -> list[dict[str, Any]]:
    if not reason_counter:
        return []
    finalized = _finalize_item_counter(reason_counter)
    if not finalized:
        return []
    total = sum(finalized.values()) or 1
    named = sorted(
        finalized.items(),
        key=lambda item: (-item[1], item[0]),
    )
    head_limit = limit
    head = named[:head_limit]
    tail_count = sum(count for _, count in named[head_limit:])
    rows = list(head)
    if tail_count > 0 and len(rows) < limit:
        rows.append(("其他", tail_count))
    elif tail_count > 0 and rows:
        rows[-1] = (rows[-1][0], rows[-1][1] + tail_count)
    return [
        {
            "reason": reason,
            "count": count,
            "ratio": round(count / total * 100, 1),
        }
        for reason, count in rows[:limit]
    ]


def _counter_from_breakdown_rows(
    rows: list[dict[str, Any]] | None,
    *,
    name_keys: tuple[str, ...] = ("name", "reason"),
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows or []:
        raw = ""
        for key in name_keys:
            if row.get(key):
                raw = str(row[key])
                break
        count = int(row.get("count") or 0)
        if count <= 0:
            continue
        norm = normalize_failure_item_name(raw) if raw else ""
        if norm and norm not in ("未标注", "其他") and not _is_junk_failure_item(norm) and not _is_org_failure_item_name(norm):
            counter[norm] += count
        else:
            counter["其他"] += count
    return counter


def _authoritative_item_event_total(payload: dict[str, Any]) -> int:
    """与 /api/stats 一致的不合格项次，避免旧 analytics 缓存只统计已命名项目。"""
    if not payload or payload.get("loading"):
        return 0

    cached = int(payload.get("item_types_total") or payload.get("total") or 0)
    date_from = (payload.get("date_from") or "").strip()
    date_to = (payload.get("date_to") or "").strip()
    province = payload.get("province") or "全部"
    city = payload.get("city") or "全部"

    if date_from or date_to:
        return cached

    if province == "全部" and city == "全部":
        try:
            from food_inspection.mysql_stats import get_mysql_stats

            stats = get_mysql_stats()
            if stats and stats.get("count_mode") == "item":
                total = int(stats.get("unqualified_count") or 0)
                if total > 0:
                    return total
        except Exception:
            pass

    return cached


def _merge_product_failure_rank_rows(
    rows: list[dict[str, Any]] | None,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """按当前产品名归一化规则合并榜单行（兼容旧版磁盘缓存）。"""
    merged: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        product = _normalize_rank_product(str(row.get("product") or ""))
        if not product:
            continue
        if product not in merged:
            merged[product] = {
                "qualified_count": 0,
                "unqualified_count": 0,
                "reasons": Counter(),
            }
        info = merged[product]
        info["qualified_count"] += int(row.get("qualified_count") or 0)
        info["unqualified_count"] += int(row.get("unqualified_count") or 0)
        info["reasons"].update(
            _counter_from_breakdown_rows(row.get("main_reasons"), name_keys=("reason", "name"))
        )

    results: list[dict[str, Any]] = []
    for product, info in merged.items():
        total = info["qualified_count"] + info["unqualified_count"]
        results.append(
            {
                "product": product,
                "qualified_count": info["qualified_count"],
                "unqualified_count": info["unqualified_count"],
                "total_count": total,
                "failure_rate": round(info["unqualified_count"] / total * 100, 2) if total else 0,
                "main_reasons": _summarize_main_reasons(info["reasons"], limit=8),
            }
        )
    results.sort(
        key=lambda x: (x["failure_rate"], x["unqualified_count"], x["total_count"]),
        reverse=True,
    )
    return results[:limit]


def _aggregate_product_batch_totals(
    product_totals: dict[str, dict[str, int]] | None,
) -> dict[str, dict[str, int]]:
    merged: dict[str, dict[str, int]] = {}
    for raw_name, counts in (product_totals or {}).items():
        name = _normalize_rank_product(str(raw_name or ""))
        if not name:
            continue
        bucket = merged.setdefault(name, {"qualified": 0, "unqualified": 0})
        bucket["qualified"] += int(counts.get("qualified") or 0)
        bucket["unqualified"] += int(counts.get("unqualified") or 0)
    for bucket in merged.values():
        bucket["total_count"] = bucket["qualified"] + bucket["unqualified"]
    return merged


def _aggregate_product_batch_totals_from_records(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    merged: dict[str, dict[str, int]] = {}
    for record in qualified:
        product = _record_sub_category(record)
        if not product:
            continue
        bucket = merged.setdefault(product, {"qualified": 0, "unqualified": 0})
        bucket["qualified"] += 1
    for record in unqualified:
        product = _record_sub_category(record)
        if not product:
            continue
        bucket = merged.setdefault(product, {"qualified": 0, "unqualified": 0})
        bucket["unqualified"] += 1
    for bucket in merged.values():
        bucket["total_count"] = bucket["qualified"] + bucket["unqualified"]
    return merged


def _apply_repeat_product_batch_totals(
    row: dict[str, Any],
    batch_map: dict[str, dict[str, int]],
) -> None:
    product = _normalize_rank_product(str(row.get("product") or ""))
    if not product:
        return
    totals = batch_map.get(product)
    if not totals:
        return
    violation = int(row.get("count") or totals.get("unqualified") or 0)
    total = int(totals.get("total_count") or 0)
    if total <= 0:
        return
    row["qualified_count"] = int(totals.get("qualified") or max(total - violation, 0))
    row["unqualified_count"] = int(totals.get("unqualified") or violation)
    row["total_count"] = total


def _load_repeat_product_batch_totals(
    payload: dict[str, Any],
) -> dict[str, dict[str, int]]:
    """仅读 analytics 缓存内的 product_batch_totals，避免接口实时全表聚合卡顿。"""
    cached = payload.get("product_batch_totals")
    if isinstance(cached, dict) and cached:
        return cached
    return {}


def _merge_repeat_product_rows(
    rows: list[dict[str, Any]] | None,
    *,
    item_total: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        product = _normalize_rank_product(str(row.get("product") or ""))
        if not product:
            continue
        if product not in merged:
            merged[product] = {
                "count": 0,
                "total_count": 0,
                "qualified_count": 0,
                "provinces": set(),
                "cities": set(),
                "item_counts": Counter(),
            }
        info = merged[product]
        info["count"] += int(row.get("count") or 0)
        row_total = int(row.get("total_count") or 0)
        row_qualified = int(row.get("qualified_count") or 0)
        if row_total > info["total_count"]:
            info["total_count"] = row_total
        if row_qualified > info["qualified_count"]:
            info["qualified_count"] = row_qualified
        info["provinces"].update(row.get("provinces") or [])
        info["cities"].update(row.get("cities") or [])
        info["item_counts"].update(_counter_from_breakdown_rows(row.get("item_breakdown")))

    results: list[dict[str, Any]] = []
    for product, info in merged.items():
        item_counts = _finalize_item_counter(info["item_counts"])
        results.append(
            {
                "product": product,
                "count": info["count"],
                "total_count": info["total_count"],
                "qualified_count": info["qualified_count"],
                "ratio": round(info["count"] / item_total * 100, 2) if item_total else 0,
                "provinces": sorted(info["provinces"])[:8],
                "cities": sorted(info["cities"])[:8],
                "item_breakdown": _item_breakdown_from_counter(item_counts, limit=8),
                "main_reasons": _summarize_main_reasons(item_counts, limit=8),
            }
        )
    results.sort(key=lambda x: x["count"], reverse=True)
    return results[:limit]


def _collapse_preservative_item_name(name: str) -> str:
    """扇形图：仅将「防腐剂混合使用时各自用量…」类标准条文缩为「防腐剂」。"""
    compact = _compact_failure_item_text(name)
    if not compact:
        return ""
    if "防腐剂混合使用" in compact:
        return "防腐剂"
    return normalize_failure_item_name(name) or compact


def _collapse_preservative_counter(counter: Counter[str]) -> Counter[str]:
    merged: Counter[str] = Counter()
    for name, count in counter.items():
        merged[_collapse_preservative_item_name(name)] += count
    return merged


def _normalize_product_display_list(names: list[str] | None) -> list[str]:
    seen: list[str] = []
    for raw in names or []:
        name = sanitize_product_name(raw) or (raw or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def light_refresh_analytics_display(payload: dict[str, Any]) -> dict[str, Any]:
    """轻量刷新：产品名去尾号、扇形图防腐剂合并（毫秒级，不走全表重算）。"""
    if not payload or payload.get("loading"):
        return payload
    out = dict(payload)

    def _refresh_breakdown(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        refreshed: list[dict[str, Any]] = []
        for row in rows or []:
            item = dict(row)
            if item.get("item_breakdown"):
                counter = _collapse_preservative_counter(
                    _counter_from_breakdown_rows(item["item_breakdown"])
                )
                item["item_breakdown"] = _item_breakdown_from_counter(counter, limit=8)
            if item.get("main_reasons"):
                counter = _collapse_preservative_counter(
                    _counter_from_breakdown_rows(item["main_reasons"], name_keys=("reason", "name"))
                )
                item["main_reasons"] = _summarize_main_reasons(counter, limit=8)
            refreshed.append(item)
        return refreshed

    if out.get("repeat_companies"):
        out["repeat_companies"] = [
            {
                **row,
                "products": _normalize_product_display_list(row.get("products")),
            }
            for row in out["repeat_companies"]
        ]
    if out.get("repeat_products"):
        out["repeat_products"] = _refresh_breakdown(out["repeat_products"])
    if out.get("top_failure_products"):
        out["top_failure_products"] = _refresh_breakdown(out["top_failure_products"])
    return out


def refresh_analytics_failure_names(payload: dict[str, Any]) -> dict[str, Any]:
    """归一化规则升级后，对已缓存 analytics 中的项目名重新合并。"""
    if not payload or payload.get("loading"):
        return payload
    out = dict(payload)
    batch_total = _authoritative_item_event_total(out)

    if out.get("item_types"):
        counter = _counter_from_breakdown_rows(out["item_types"])
        out.update(_build_item_types_payload(counter, batch_total=batch_total))
        if batch_total > 0:
            out["total"] = batch_total
            out["item_types_total"] = batch_total

    def _refresh_rank_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        refreshed: list[dict[str, Any]] = []
        for row in rows or []:
            item = dict(row)
            if item.get("item_breakdown"):
                counter = _counter_from_breakdown_rows(item["item_breakdown"])
                item["item_breakdown"] = _item_breakdown_from_counter(counter, limit=8)
            if item.get("main_reasons"):
                counter = _counter_from_breakdown_rows(item["main_reasons"], name_keys=("reason", "name"))
                item["main_reasons"] = _summarize_main_reasons(counter, limit=8)
            refreshed.append(item)
        return refreshed

    item_total = int(out.get("total") or batch_total or 0)
    out["top_failure_products"] = _merge_product_failure_rank_rows(out.get("top_failure_products"))
    batch_map = _load_repeat_product_batch_totals(out)
    if batch_map:
        out["product_batch_totals"] = batch_map
    repeat_rows = _refresh_rank_rows(out.get("repeat_products"))
    for row in repeat_rows:
        _apply_repeat_product_batch_totals(row, batch_map)
        if not row.get("total_count"):
            product = _normalize_rank_product(str(row.get("product") or ""))
            for rank_row in out.get("top_failure_products") or []:
                if rank_row.get("product") == product:
                    row["total_count"] = int(rank_row.get("total_count") or 0)
                    row["qualified_count"] = int(rank_row.get("qualified_count") or 0)
                    break
    out["repeat_products"] = _merge_repeat_product_rows(
        repeat_rows,
        item_total=item_total,
    )
    out["repeat_product_count"] = len(out["repeat_products"])
    return out


def _resolve_city(record: dict[str, Any]) -> str:
    return resolve_record_city(record)


def _to_ratio(items: list[tuple[str, int]], total: int, limit: int = 30) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for name, count in items[:limit]:
        result.append(
            {
                "name": name,
                "count": count,
                "ratio": round(count / total * 100, 2) if total else 0,
            }
        )
    return result


def _filter_by_province(records: list[dict[str, Any]], province: str) -> list[dict[str, Any]]:
    if not province or province == "全部":
        return records
    return [r for r in records if resolve_folder_province(r) == province]


def _build_city_failure_rates(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    province: str,
    city: str = "全部",
    min_samples: int = 10,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """按文件夹城市计算不合格率 = 不合格批次 / (合格 + 不合格)。"""
    q_records = _filter_by_city(_filter_by_province(qualified, province), city)
    u_records = _filter_by_city(_filter_by_province(unqualified, province), city)

    city_qualified: Counter[str] = Counter()
    city_unqualified: Counter[str] = Counter()

    for record in q_records:
        key = _city_stat_key(record, province)
        if key:
            city_qualified[key] += 1
    for record in u_records:
        key = _city_stat_key(record, province)
        if key:
            city_unqualified[key] += 1

    results: list[dict[str, Any]] = []
    for city_name in set(city_qualified) | set(city_unqualified):

        q_count = city_qualified.get(city_name, 0)
        u_count = city_unqualified.get(city_name, 0)
        total = q_count + u_count
        if total < min_samples:
            continue

        results.append(
            {
                "name": city_name,
                "qualified_count": q_count,
                "unqualified_count": u_count,
                "total_count": total,
                "count": u_count,
                "ratio": round(u_count / total * 100, 2),
            }
        )

    results.sort(key=lambda x: (x["ratio"], x["unqualified_count"]), reverse=True)
    return results[:limit]


def _aggregate_company_stats(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    province: str,
    city: str = "全部",
) -> dict[str, dict[str, Any]]:
    q_records = _filter_by_city(_filter_by_province(qualified, province), city)
    u_records = _filter_by_city(_filter_by_province(unqualified, province), city)
    return _aggregate_company_stats_lists(q_records, u_records)


def _aggregate_company_stats_lists(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    *,
    name_fn=None,
    address_fn=None,
) -> dict[str, dict[str, Any]]:
    if name_fn is None:
        name_fn = _record_sampled_company
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "qualified": 0,
            "unqualified": 0,
            "products": set(),
            "cities": set(),
            "addresses": Counter(),
        }
    )

    def _accumulate(record: dict[str, Any], *, qualified_row: bool) -> None:
        company = name_fn(record)
        if not company or is_invalid_company(company) or is_inspection_agency(company):
            return
        info = stats[company]
        if qualified_row:
            info["qualified"] += 1
        else:
            info["unqualified"] += 1
        product = _record_sub_category(record)
        if product:
            info["products"].add(product)
        record_city = _resolve_city(record)
        if record_city:
            info["cities"].add(record_city)
        if address_fn:
            addr = address_fn(record)
            if addr:
                info["addresses"][addr] += 1

    for record in qualified:
        _accumulate(record, qualified_row=True)
    for record in unqualified:
        _accumulate(record, qualified_row=False)

    return stats


def _pick_entity_address(info: dict[str, Any]) -> str:
    addresses: Counter[str] = info.get("addresses") or Counter()
    if not addresses:
        return ""
    return addresses.most_common(1)[0][0]


def _company_failure_ranking_from_stats(
    stats: dict[str, dict[str, Any]],
    *,
    min_samples: int = 5,
    limit: int = 50,
    include_address: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for company, info in stats.items():
        if company == "未知公司" or is_invalid_company(company):
            continue
        total = info["qualified"] + info["unqualified"]
        if total < min_samples:
            continue
        entry = {
            "company": company,
            "qualified_count": info["qualified"],
            "unqualified_count": info["unqualified"],
            "total_count": total,
            "failure_rate": round(info["unqualified"] / total * 100, 2),
            "cities": sorted(info["cities"])[:6],
        }
        if include_address:
            entry["address"] = _pick_entity_address(info)
        results.append(entry)

    results.sort(
        key=lambda x: (x["failure_rate"], x["unqualified_count"], x["total_count"]),
        reverse=True,
    )
    return results[:limit]


def _perfect_company_ranking_from_stats(
    stats: dict[str, dict[str, Any]],
    *,
    min_samples: int = 2,
    limit: int = 100,
    include_address: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for company, info in stats.items():
        if company == "未知公司" or is_invalid_company(company):
            continue
        unqualified_count = info["unqualified"]
        qualified_count = info["qualified"]
        total = qualified_count + unqualified_count
        if unqualified_count > 0 or total < min_samples:
            continue
        entry = {
            "company": company,
            "qualified_count": qualified_count,
            "total_count": total,
            "pass_rate": 100.0,
            "products": sorted(info["products"])[:8],
            "cities": sorted(info["cities"])[:8],
        }
        if include_address:
            entry["address"] = _pick_entity_address(info)
        results.append(entry)

    results.sort(key=lambda x: (x["total_count"], x["qualified_count"]), reverse=True)
    return results[:limit]


def _enrich_perfect_rankings_with_products(
    rankings: list[dict[str, Any]],
    *,
    company_column: str,
    province: str,
    city: str,
    date_from: str | None,
    date_to: str | None,
) -> list[dict[str, Any]]:
    if not rankings:
        return rankings
    try:
        from food_inspection.db import fetch_company_top_products, mysql_enabled

        if not mysql_enabled():
            return rankings
        products_map = fetch_company_top_products(
            [row["company"] for row in rankings],
            company_column=company_column,
            province=province,
            city=city,
            date_from=date_from,
            date_to=date_to,
        )
    except Exception:
        return rankings
    for row in rankings:
        products = products_map.get(row["company"])
        if products:
            row["products"] = products
    return rankings


def _build_company_failure_ranking(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    province: str,
    city: str = "全部",
    min_samples: int = 5,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stats = _aggregate_company_stats(qualified, unqualified, province, city)
    return _company_failure_ranking_from_stats(stats, min_samples=min_samples, limit=limit)


def _build_perfect_company_ranking(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    province: str,
    city: str = "全部",
    min_samples: int = 2,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stats = _aggregate_company_stats(qualified, unqualified, province, city)
    return _perfect_company_ranking_from_stats(stats, min_samples=min_samples, limit=limit)


def _build_product_failure_ranking_lists(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    min_samples: int = 10,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"qualified": 0, "unqualified": 0, "reasons": Counter()}
    )

    for record in qualified:
        product = _record_sub_category(record)
        if not product:
            continue
        stats[product]["qualified"] += 1

    for record in unqualified:
        product = _record_sub_category(record)
        if not product:
            continue
        info = stats[product]
        info["unqualified"] += 1
        info["reasons"][_extract_failure_reason(record)] += 1

    results: list[dict[str, Any]] = []
    for product, info in stats.items():
        if info["unqualified"] <= 0:
            continue
        total = info["qualified"] + info["unqualified"]
        if total < min_samples:
            continue
        main_reasons = _summarize_main_reasons(info["reasons"], limit=8)
        results.append(
            {
                "product": product,
                "qualified_count": info["qualified"],
                "unqualified_count": info["unqualified"],
                "total_count": total,
                "failure_rate": round(info["unqualified"] / total * 100, 2),
                "main_reasons": main_reasons,
            }
        )

    results.sort(
        key=lambda x: (x["failure_rate"], x["unqualified_count"], x["total_count"]),
        reverse=True,
    )
    return results[:limit]


def _aggregate_company_stats_from_sql(
    company_totals: dict[str, dict[str, int]],
    unqualified: list[dict[str, Any]],
    *,
    name_fn=None,
    address_fn=None,
) -> dict[str, dict[str, Any]]:
    if name_fn is None:
        name_fn = _record_sampled_company
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "qualified": 0,
            "unqualified": 0,
            "products": set(),
            "cities": set(),
            "addresses": Counter(),
        }
    )
    for company, counts in company_totals.items():
        if not company or is_invalid_company(company) or is_inspection_agency(company):
            continue
        stats[company]["qualified"] = counts.get("qualified", 0)
        stats[company]["unqualified"] = counts.get("unqualified", 0)

    for record in unqualified:
        company = name_fn(record)
        if not company or is_invalid_company(company) or is_inspection_agency(company):
            continue
        info = stats[company]
        if company not in company_totals:
            info["unqualified"] += 1
        product = _record_sub_category(record)
        if product:
            info["products"].add(product)
        record_city = _resolve_city(record)
        if record_city:
            info["cities"].add(record_city)
        if address_fn:
            addr = address_fn(record)
            if addr:
                info["addresses"][addr] += 1
    return stats


def _build_product_failure_ranking_from_sql(
    product_totals: dict[str, dict[str, int]],
    unqualified: list[dict[str, Any]],
    min_samples: int = 10,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"qualified": 0, "unqualified": 0, "reasons": Counter()}
    )
    for product, counts in product_totals.items():
        product = (product or "").strip()
        if not product:
            continue
        stats[product]["qualified"] += counts.get("qualified", 0)
        stats[product]["unqualified"] += counts.get("unqualified", 0)

    for record in unqualified:
        product = _record_sub_category(record)
        if not product:
            continue
        stats[product]["reasons"][_extract_failure_reason(record)] += 1

    results: list[dict[str, Any]] = []
    for product, info in stats.items():
        if info["unqualified"] <= 0:
            continue
        total = info["qualified"] + info["unqualified"]
        if total < min_samples:
            continue
        main_reasons = _summarize_main_reasons(info["reasons"], limit=8)
        results.append(
            {
                "product": product,
                "qualified_count": info["qualified"],
                "unqualified_count": info["unqualified"],
                "total_count": total,
                "failure_rate": round(info["unqualified"] / total * 100, 2),
                "main_reasons": main_reasons,
            }
        )

    results.sort(
        key=lambda x: (x["failure_rate"], x["unqualified_count"], x["total_count"]),
        reverse=True,
    )
    return results[:limit]


def _build_city_failure_rates_from_sql(
    city_totals: dict[str, dict[str, int]],
    min_samples: int = 10,
    limit: int = 30,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for city_name, counts in city_totals.items():
        q_count = counts.get("qualified", 0)
        u_count = counts.get("unqualified", 0)
        total = q_count + u_count
        if total < min_samples:
            continue
        results.append(
            {
                "name": city_name,
                "qualified_count": q_count,
                "unqualified_count": u_count,
                "total_count": total,
                "count": u_count,
                "ratio": round(u_count / total * 100, 2),
            }
        )
    results.sort(key=lambda x: (x["ratio"], x["unqualified_count"]), reverse=True)
    return results[:limit]


def _build_product_failure_ranking(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    province: str,
    city: str = "全部",
    min_samples: int = 10,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q_records = _filter_by_city(_filter_by_province(qualified, province), city)
    u_records = _filter_by_city(_filter_by_province(unqualified, province), city)
    return _build_product_failure_ranking_lists(q_records, u_records, min_samples, limit)


def build_company_stats(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    keyword: str,
    province: str = "全部",
    city: str = "全部",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """按单位名称汇总抽检总数、不合格数与不合格率。"""
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return []

    stats = _aggregate_company_stats(qualified, unqualified, province, city)
    results: list[dict[str, Any]] = []

    for company, info in stats.items():
        if keyword not in company.lower():
            continue
        total = info["qualified"] + info["unqualified"]
        results.append(
            {
                "company": company,
                "qualified_count": info["qualified"],
                "unqualified_count": info["unqualified"],
                "total_count": total,
                "failure_rate": round(info["unqualified"] / total * 100, 2) if total else 0,
                "products": sorted(info["products"])[:6],
                "cities": sorted(info["cities"])[:6],
            }
        )

    results.sort(key=lambda x: (x["total_count"], x["failure_rate"]), reverse=True)
    return results[:limit]


def build_analytics(
    unqualified: list[dict[str, Any]],
    qualified: list[dict[str, Any]] | None = None,
    province: str = "全部",
    city: str = "全部",
    min_violations: int = 2,
    min_repeat_violations: int = 5,
    min_city_samples: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
    sql_aggregates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    qualified = filter_records_by_date_range(qualified or [], date_from, date_to)
    unqualified = filter_records_by_date_range(unqualified or [], date_from, date_to)
    scope_province = province or "全部"
    scope_city = city or "全部"
    records = _mapped_records(
        _filter_by_city(_filter_by_province(unqualified, scope_province), scope_city)
    )

    item_counter: Counter[str] = Counter()
    company_counter: Counter[str] = Counter()
    product_counter: Counter[str] = Counter()

    company_details: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"items": set(), "products": set(), "cities": set()}
    )
    product_details: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"item_counts": Counter(), "cities": set(), "provinces": set()}
    )

    for record in records:
        failure_items = _record_failure_items(record)

        _accumulate_failure_items_from_list(item_counter, failure_items)

        record_city = _resolve_city(record)
        company = _record_sampled_company(record) or "未知公司"
        product = _record_sub_category(record) or "未知产品"
        province_name = (record.get("source_province") or record.get("province") or "").strip()

        company_counter[company] += 1
        if product != "未知产品":
            product_counter[product] += 1
            _accumulate_failure_items_from_list(product_details[product]["item_counts"], failure_items)
            product_details[product]["cities"].add(record_city)
            if province_name:
                product_details[product]["provinces"].add(province_name)

        for item_name in failure_items:
            company_details[company]["items"].add(item_name)
        company_details[company]["products"].add(product)
        company_details[company]["cities"].add(record_city)

    event_total = count_unqualified_items(records)
    item_payload = _build_item_types_payload(item_counter, batch_total=event_total)
    item_total = item_payload["item_types_total"]

    repeat_companies = []
    for company, count in company_counter.most_common():
        if count < min_repeat_violations or company == "未知公司" or is_invalid_company(company):
            continue
        detail = company_details[company]
        products = sorted(p for p in detail["products"] if p and p != "未知产品")
        items = sorted(detail["items"])
        repeat_companies.append(
            {
                "company": company,
                "count": count,
                "ratio": round(count / item_total * 100, 2) if item_total else 0,
                "products": products[:30],
                "cities": sorted(detail["cities"])[:8],
                "items": items[:30],
            }
        )

    repeat_products = []
    for product, count in product_counter.most_common():
        if count < min_repeat_violations:
            continue
        detail = product_details[product]
        item_counts = _finalize_item_counter(detail["item_counts"])
        repeat_products.append(
            {
                "product": product,
                "count": count,
                "ratio": round(count / item_total * 100, 2) if item_total else 0,
                "provinces": sorted(detail["provinces"])[:8],
                "cities": sorted(detail["cities"])[:8],
                "item_breakdown": _item_breakdown_from_counter(item_counts, limit=8),
                "main_reasons": _summarize_main_reasons(item_counts, limit=8),
            }
        )

    product_min_samples = 20

    u_scope = _mapped_records(
        _filter_by_city(_filter_by_province(unqualified, scope_province), scope_city)
    )
    if sql_aggregates:
        # SQL 已按 sub_category 聚合，无需再从 food_name 二次映射
        product_totals = sql_aggregates.get("products") or {}
        sampled_stats = _aggregate_company_stats_from_sql(
            sql_aggregates.get("sampled_companies") or {},
            u_scope,
            name_fn=_record_sampled_company,
            address_fn=_record_sampled_address,
        )
        manufacturer_stats = _aggregate_company_stats_from_sql(
            sql_aggregates.get("manufacturers") or {},
            u_scope,
            name_fn=_record_manufacturer,
            address_fn=_record_manufacturer_address,
        )
        top_failure_products = _build_product_failure_ranking_from_sql(
            product_totals,
            u_scope,
            min_samples=product_min_samples,
            limit=50,
        )
        all_city_failure_rates = _build_city_failure_rates_from_sql(
            sql_aggregates.get("cities") or {},
            min_samples=min_city_samples,
            limit=50,
        )
    else:
        q_scope = _mapped_records(
            _filter_by_city(_filter_by_province(qualified, scope_province), scope_city)
        )
        sampled_stats = _aggregate_company_stats_lists(
            q_scope,
            u_scope,
            name_fn=_record_sampled_company,
            address_fn=_record_sampled_address,
        )
        manufacturer_stats = _aggregate_company_stats_lists(
            q_scope,
            u_scope,
            name_fn=_record_manufacturer,
            address_fn=_record_manufacturer_address,
        )
        top_failure_products = _build_product_failure_ranking_lists(
            q_scope,
            u_scope,
            min_samples=product_min_samples,
            limit=50,
        )
        all_city_failure_rates = _build_city_failure_rates(
            qualified, unqualified, scope_province, "全部", min_samples=min_city_samples, limit=50
        )
    top_failure_companies = _company_failure_ranking_from_stats(
        sampled_stats, min_samples=min_violations, limit=50
    )
    top_failure_manufacturers = _company_failure_ranking_from_stats(
        manufacturer_stats, min_samples=min_violations, limit=50, include_address=True
    )
    city_failure_rates = all_city_failure_rates[:30]
    top_failure_cities = all_city_failure_rates
    perfect_companies = _perfect_company_ranking_from_stats(
        sampled_stats,
        min_samples=min_violations,
        limit=100,
    )
    perfect_manufacturers = _perfect_company_ranking_from_stats(
        manufacturer_stats,
        min_samples=min_violations,
        limit=100,
        include_address=True,
    )
    if sql_aggregates:
        perfect_companies = _enrich_perfect_rankings_with_products(
            perfect_companies,
            company_column="sampled_company_name",
            province=scope_province,
            city=scope_city,
            date_from=date_from,
            date_to=date_to,
        )
        perfect_manufacturers = _enrich_perfect_rankings_with_products(
            perfect_manufacturers,
            company_column="manufacturer_name",
            province=scope_province,
            city=scope_city,
            date_from=date_from,
            date_to=date_to,
        )

    product_batch_map = (
        _aggregate_product_batch_totals(product_totals)
        if sql_aggregates
        else _aggregate_product_batch_totals_from_records(
            _mapped_records(
                _filter_by_city(_filter_by_province(qualified, scope_province), scope_city)
            ),
            u_scope,
        )
    )
    for row in repeat_products:
        _apply_repeat_product_batch_totals(row, product_batch_map)
    repeat_batch_totals = {
        row["product"]: product_batch_map[row["product"]]
        for row in repeat_products[:100]
        if row.get("product") in product_batch_map
    }

    return {
        "total": item_total,
        "province": scope_province,
        "city": scope_city,
        "date_from": date_from or "",
        "date_to": date_to or "",
        "min_violations": min_violations,
        "min_repeat_violations": min_repeat_violations,
        **item_payload,
        "cities": city_failure_rates,
        "top_failure_companies": top_failure_companies,
        "top_failure_manufacturers": top_failure_manufacturers,
        "top_failure_products": top_failure_products,
        "top_failure_cities": top_failure_cities,
        "repeat_companies": repeat_companies[:100],
        "repeat_products": repeat_products[:100],
        "repeat_company_count": len(repeat_companies),
        "repeat_product_count": len(repeat_products),
        "product_batch_totals": repeat_batch_totals,
        "perfect_companies": perfect_companies,
        "perfect_company_count": len(perfect_companies),
        "perfect_manufacturers": perfect_manufacturers,
        "perfect_manufacturer_count": len(perfect_manufacturers),
    }


_CATEGORY_PLACEHOLDERS = frozenset(
    {"", "/", "-", "—", "无", "暂无", "不详", "未知", "nan", "none", "null", "其他", "其他食品", "非食品"}
)

# 表内大类过于笼统或易误导时，优先按产品名/不合格项目推断具体大类
_CATEGORY_PREFER_INFERENCE = frozenset(
    {
        "食品相关产品",  # 多为餐饮具消毒抽检，少数为包装材料
        "工业加工食品",
        "餐饮加工食品",
        "其他食品",
    }
)

# 别名 / OCR 空格错误 → 标准食品大类
_CATEGORY_CANONICAL: dict[str, str] = {
    "食用农产 品": "食用农产品",
    "食用农产": "食用农产品",
    "食用农 产品": "食用农产品",
    "粮食加工 品": "粮食加工品",
    "茶叶及相 关制品": "茶叶及相关制品",
    "茶叶及相": "茶叶及相关制品",
    "食品添加 剂": "食品添加剂",
    "可可及焙 烤咖啡产 品": "可可及焙烤咖啡产品",
    "烤咖啡产": "可可及焙烤咖啡产品",
    "品": "未分类",
    "月饼": "糕点",
    "水果类（必检）": "食用农产品",
    "水果类（普通食品）": "食用农产品",
    "蔬菜（必检）": "食用农产品",
    # 东莞 PDF OCR 列错位产生的残缺分类名
    "品蔬菜制": "蔬菜制品",
    "产品食用农": "食用农产品",
    "工品粮食加": "粮食加工品",
    "食用农": "食用农产品",
    "蔬菜": "蔬菜制品",
    "品餐饮食": "餐饮食品",
}

# 细分类并入常见大类，减少饼图「其他分类」
_CATEGORY_ROLLUP: dict[str, str] = {
    "速冻面米制品": "速冻食品",
    "速冻调制食品": "速冻食品",
    "淀粉": "淀粉及淀粉制品",
    "特殊膳食": "特殊膳食食品",
    "婴幼儿配方食品": "特殊膳食食品",
    "罐头": "罐头",
    "食糖": "食糖",
}

# 从文件名/产品名推断（按长度降序匹配）
_INFER_CATEGORY_KEYWORDS: tuple[str, ...] = (
    "食用油、油脂及其制品",
    "炒货食品及坚果制品",
    "淀粉及淀粉制品",
    "茶叶及相关制品",
    "可可及焙烤咖啡产品",
    "特殊膳食食品",
    "薯类和膨化食品",
    "食用农产品",
    "餐饮食品",
    "保健食品",
    "蔬菜制品",
    "水果制品",
    "水产制品",
    "粮食加工品",
    "冷冻饮品",
    "速冻食品",
    "方便食品",
    "糖果制品",
    "特殊膳食",
    "婴幼儿配方",
    "食品添加剂",
    "调味品",
    "肉制品",
    "豆制品",
    "乳制品",
    "蛋制品",
    "餐饮具",
    "糕点",
    "饮料",
    "酒类",
    "罐头",
    "食糖",
    "饼干",
    "蜂产品",
    "餐饮",
    "农产品",
)

# 产品名 / 不合格项目关键词 → 食品大类（按优先级排列）
_PRODUCT_CATEGORY_SPECS: tuple[tuple[str, str], ...] = (
    (
        r"阴离子合成洗涤剂|合成洗涤剂|餐饮具|"
        r"(?:密胺|陶瓷|不锈钢|仿瓷|Melamine)?(?:碗|碟|盘|杯|筷|勺|餐盘|骨碟|汤碗|饭碗|菜盘|方盘|圆盘|长条盘|"
        r"面碗|凉菜盘|小菜碗|大圆盘|米饭碗|菜碗|水杯|料碗|蘸料碟|寿司盘|水果盘|豆浆碗|小吃盘|小圆盘|方形盘)",
        "餐饮具",
    ),
    (
        r"塑料编织袋|淋膜纸|一次性纸碗|纸碗|品尝杯|食品包装|包装材料|复合膜|保鲜膜|"
        r"塑料袋|塑料杯|纸杯|刀叉|吸管|纸制品",
        "食品包装材料",
    ),
    (
        r"胶囊|口服液|片剂|软糖|压片糖果|维生素|鱼油|钙片|锌片|硒片|蛋白粉|氨糖|"
        r"辅酶|褪黑素|益生菌|保健|磷脂|胶原蛋白|氨基酸|甘草片|常菁茶|胖大海",
        "保健食品",
    ),
    (
        r"(?:花生|菜籽|葵花籽|玉米|橄榄|大豆|调和|胡麻|茶籽|油茶籽|亚麻籽|核桃|芝麻|香)油|"
        r"麻油|香油|猪油|牛油|羊油|油脂|煎炸过程用油",
        "食用油、油脂及其制品",
    ),
    (
        r"鲜玉米|牛蛙|"
        r"香蕉|芒果|荔枝|龙眼|枇杷|杨桃|火龙果|百香果|山竹|榴莲|椰[子青]?|哈密瓜|甜瓜|西瓜|"
        r"草莓|樱桃|葡萄|乌梅|李[子子]?|桃[子子]?|杏[子子]?|枣[子子]?|橙[子子]?|桔[子子]?|橘[子子]?|"
        r"柚[子子]?|柠檬|苹果|梨[子子]?|柿子|石榴|猕猴桃|奇异果|蓝莓|杨梅|桑葚|无花果|番石榴|"
        r"菠萝|凤梨|甘蔗|莲雾|释迦|青枣|冬枣|蜜柚|砂糖橘|沃柑|丑橘|脐橙|金桔|提子|青提|红提|"
        r"山药|生姜|姜[片块丝]?|南姜|韭菜|芹菜|菠菜|生菜|油麦|茼蒿|莴笋|萝卜|胡萝卜|土豆|马铃薯|"
        r"莲藕|竹笋|丝瓜|冬瓜|南瓜|黄瓜|番茄|西红柿|茄子|辣椒|青椒|菜心|芥蓝|空心菜|茭白|芋头|"
        r"红薯|地瓜|荸荠|菱角|蘑菇|香菇|平菇|金针菇|杏鲍菇|木耳|银耳|"
        r"豇豆|四季豆|荷兰豆|螺丝椒|小米椒|尖椒|甜椒|彩椒|线椒|青线椒|黄皮椒|陇椒|甜圆椒|青圆椒|"
        r"黄豆芽|绿豆芽|豆芽|"
        r"小葱|大葱|蒜苗|洋葱|香葱|白芷|山奈|"
        r"小台芒|台芒|金煌芒|木瓜|粉蕉|皇帝蕉|蜜薯|芋儿|"
        r"食荚豌豆|豆角|青豆角|白豆角|小白菜|上海青|香芹|梅干菜|"
        r"花生米|"
        r"鲜鸡|活鸡|鲜鸭|活鸭|排骨|猪蹄|鸡翅|鸡爪|牛腩|羊肉卷|鲜蛋|鸡蛋|鸭蛋|鹅蛋|鹌鹑蛋",
        "食用农产品",
    ),
    (
        r"鱼片|鱼块|虾仁|蟹肉|贝类|螺肉|鱿鱼|带鱼|花甲|蛏子|鲍鱼|"
        r"海参|海带|紫菜|海蜇|泥鳅|黄鳝|鳗鱼|鲫鱼|草鱼|鲤鱼|鲈鱼|黄鳍|黑鱼|基围虾|小龙虾|"
        r"罗非鱼|多宝鱼|石斑|三文鱼|金枪鱼|鳕鱼|墨鱼|章鱼|扇贝|生蚝|牡蛎|河虾|白虾|"
        r"大口黑鲈|黄辣丁|鳊鱼|九节虾|沙甲|带子",
        "水产制品",
    ),
    (
        r"馒头|包子|油条|烧[卖麦]|盒饭|煎饼|手抓饼|热干面|米粉|河粉|凉皮|肉夹馍|水饺|馄饨|"
        r"汤圆|元宵|豆浆|豆腐脑|小作坊|餐饮|快餐|熟制|现制|豆沙包|红糖馒|切粉",
        "餐饮食品",
    ),
    (
        r"大米|面粉|小麦|挂面|面条|粉丝|粉条|凉[（(]?皮[)）]?|方便[面米]|年糕|糍粑|"
        r"河粉[（(]?干[)）]?|米粉[（(]?干[)）]?",
        "粮食加工品",
    ),
    (
        r"酱油|食醋|蚝油|料酒|味精|鸡精|火锅底料|豆瓣|腐乳|辣酱|调味|香[料油]|十三香|"
        r"花椒|八角|桂皮|孜然|胡椒",
        "调味品",
    ),
    (
        r"蛋糕|面包|月饼|酥[饼]|曲奇|蛋挞|派|糕点|桃酥|沙琪玛|麻花|糖[果糕]|巧克力",
        "糕点",
    ),
    (
        r"矿泉水|饮用水|果汁|汽水|可乐|茶饮|奶茶|咖啡|啤酒|白酒|葡萄酒|黄酒|功能饮料|"
        r"运动饮料|乳饮料|豆奶|椰汁|劲酒|配制酒|露酒|保健酒|养生酒|高粱酒",
        "饮料",
    ),
    (
        r"牛奶|酸奶|奶酪|芝士|奶粉|炼乳|黄油|奶油|乳清",
        "乳制品",
    ),
    (
        r"火腿|香肠|腊肉|腊肠|酱肉|酱卤|肉松|肉干|肉脯|扒鸡|烧鸡|烤鸭|酱鸭",
        "肉制品",
    ),
    (
        r"豆腐|豆干|豆皮|腐竹|豆浆|素鸡|千张|百叶|豆[制品腐]",
        "豆制品",
    ),
    (
        r"薯片|虾条|膨化|锅巴|雪[米米]花|仙贝|浪味仙",
        "薯类和膨化食品",
    ),
    (
        r"坚果|瓜子|花生[（(]?炒[)）]?|核桃[（(]?炒[)）]?|腰果|开心果|巴旦木|夏威夷果|"
        r"碧根果|松子|榛子|杏仁",
        "炒货食品及坚果制品",
    ),
    (
        r"蜜饯|果脯|果干|话梅|山楂[片糕]|枣[糕片]|芒果干|葡萄干",
        "水果制品",
    ),
    (
        r"酱菜|泡菜|酸菜|榨菜|萝卜干|脱水|干制|蔬菜干",
        "蔬菜制品",
    ),
)

_PRODUCT_CATEGORY_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), category) for pattern, category in _PRODUCT_CATEGORY_SPECS
)

# 极短产品名精确匹配（避免误伤「洋葱」等复合词）
_PRODUCT_SHORT_EXACT: dict[str, str] = {
    "葱": "食用农产品",
    "姜": "食用农产品",
    "蒜": "食用农产品",
    "碗": "餐饮具",
    "碟": "餐饮具",
    "盘": "餐饮具",
    "杯": "餐饮具",
    "筷": "餐饮具",
    "勺": "餐饮具",
}

_PATH_INFER_HINTS: tuple[tuple[str, str], ...] = (
    ("小作坊", "餐饮食品"),
    ("餐饮店", "餐饮食品"),
    ("餐饮服务", "餐饮食品"),
    ("流通环节", "食用农产品"),
    ("农产品", "食用农产品"),
    ("农贸", "食用农产品"),
    ("餐具", "餐饮具"),
    ("阴离子合成洗涤剂", "餐饮具"),
    ("合成洗涤剂", "餐饮具"),
)


def _canonical_category_name(text: str) -> str:
    compact = re.sub(r"\s+", "", _clean(text))
    if not compact:
        return "未分类"
    if compact in _CATEGORY_CANONICAL:
        return _CATEGORY_CANONICAL[compact]
    for alias, canonical in _CATEGORY_CANONICAL.items():
        if compact == re.sub(r"\s+", "", alias):
            return canonical
    return _clean(text)


def _rollup_category(name: str) -> str:
    text = (name or "").strip()
    if not text or text == "未分类":
        return text
    compact = re.sub(r"\s+", "", text)
    if compact in _CATEGORY_ROLLUP:
        return _CATEGORY_ROLLUP[compact]
    for alias, canonical in _CATEGORY_ROLLUP.items():
        if compact == re.sub(r"\s+", "", alias):
            return canonical
    return text


def _path_hints_for_category(source: str) -> list[str]:
    hints: list[str] = []
    if not source:
        return hints
    normalized = source.replace("\\", "/")
    skip = frozenset({"合格", "不合格", "PDF", "Sheet1", "Sheet2", "Worksheet1", "Worksheet"})
    for part in reversed(normalized.split("/")):
        if not part or part in skip:
            continue
        if re.fullmatch(r"20\d{2}", part):
            continue
        hints.append(part)
        if len(hints) >= 8:
            break
    return hints


def _infer_category_from_product(product: str) -> str:
    text = re.sub(r"\s+", "", _clean(product))
    if not text or len(text) > 80:
        return ""
    if text in _PRODUCT_SHORT_EXACT:
        return _PRODUCT_SHORT_EXACT[text]
    for pattern, category in _PRODUCT_CATEGORY_RULES:
        if pattern.search(text):
            return category
    return ""


def _infer_category_from_record(record: dict[str, Any]) -> str:
    """分类列为空时，从产品名、附件名、路径、不合格项目等推断。"""
    product = (record.get("product") or "").strip()
    from_product = _infer_category_from_product(product)
    if from_product:
        return from_product

    for key in ("unqualified_item", "reason"):
        text = (record.get(key) or "").strip()
        if not text:
            continue
        from_item = _infer_category_from_product(text)
        if from_item:
            return from_item

    parts: list[str] = [
        record.get("source_file_name") or "",
        record.get("source_sheet") or "",
        product,
    ]
    source = record.get("source_file") or ""
    if source:
        parts.append(os.path.basename(source))
        parts.extend(_path_hints_for_category(source))

    compact = re.sub(r"\s+", "", " ".join(parts))
    if not compact:
        return ""

    for keyword, category in _PATH_INFER_HINTS:
        if keyword.replace(" ", "") in compact:
            return category

    for keyword in _INFER_CATEGORY_KEYWORDS:
        key = keyword.replace(" ", "")
        if key in compact:
            if keyword == "餐饮":
                return "餐饮食品"
            if keyword == "农产品":
                return "食用农产品"
            return keyword

    return ""


def _resolve_record_category(record: dict[str, Any]) -> str:
    """解析记录的食品大类：优先表内分类列，否则从上下文推断。"""
    raw = (record.get("category") or "").strip()
    inferred = _infer_category_from_record(record)

    if raw and raw.lower() not in _CATEGORY_PLACEHOLDERS:
        canonical = _rollup_category(_canonical_category_name(raw))
        if canonical in _CATEGORY_PREFER_INFERENCE and inferred:
            return _rollup_category(inferred)
        if _is_plausible_category(canonical):
            return canonical

    if inferred:
        return _rollup_category(inferred)

    return "未分类"


def _normalize_category(record: dict[str, Any]) -> str:
    """统计规整：仅使用已映射小类。"""
    return _record_sub_category(record)


def resolve_category_from_mysql_row(
    *,
    category: str | None = None,
    food_name: str | None = None,
    unqualified_item: str | None = None,
    unqualified_reason: str | None = None,
    file_source: str | None = None,
) -> str:
    """与缓存统计一致：按表内分类列 + 产品/路径推断食品大类。"""
    return _resolve_record_category(
        {
            "category": (category or "").strip(),
            "product": (food_name or "").strip(),
            "unqualified_item": (unqualified_item or "").strip(),
            "reason": (unqualified_reason or "").strip(),
            "source_file": (file_source or "").strip(),
        }
    )


def _build_item_types_payload(
    item_counter: Counter[str],
    *,
    batch_total: int,
    head_limit: int = 199,
) -> dict[str, Any]:
    item_counter = _finalize_item_counter(item_counter)
    named_total = sum(item_counter.values())
    item_total = batch_total if batch_total > 0 else named_total
    if item_total < named_total:
        item_total = named_total
    unlabeled = max(item_total - named_total, 0)

    ranked = item_counter.most_common()
    head = ranked[:head_limit]
    tail = ranked[head_limit:]
    tail_count = sum(count for _, count in tail)
    other_count = tail_count + unlabeled
    item_types = _to_ratio(head, item_total, limit=head_limit)
    if other_count > 0:
        item_types.append(
            {
                "name": "其他",
                "count": other_count,
                "ratio": round(other_count / item_total * 100, 2),
            }
        )
    return {
        "item_types": item_types,
        "item_types_total": item_total,
        "item_types_unique": len(item_counter),
        "item_types_tail_unique": len(tail),
        "item_types_tail_count": other_count,
        "item_types_unlabeled": unlabeled,
    }


def _is_plausible_category(name: str) -> bool:
    text = (name or "").strip()
    if not text or text in ("未分类", "非食品"):
        return False
    if re.fullmatch(r"\d+", text):
        return False
    if is_junk_category(text):
        return False
    if len(text) > 24:
        return False
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text):
        return False
    if any(marker in text for marker in ("║", "mg/", "mg/kg", "不得检出", "检出值")):
        return False
    return True


def _unqualified_category_share(
    cat_unqualified: Counter[str],
    *,
    limit: int = 22,
    total_unqualified: int = 0,
) -> tuple[list[dict[str, Any]], int, int]:
    """不合格项次按食品分类占比（供总览饼图）。"""
    merged: Counter[str] = Counter()
    for name, count in cat_unqualified.items():
        merged[_normalize_category_key(name)] += count
    cat_unqualified = merged
    full_total = total_unqualified or sum(cat_unqualified.values())
    if full_total <= 0:
        return [], 0, 0

    ranked: list[tuple[str, int]] = []
    uncategorized = 0
    for name, count in cat_unqualified.items():
        if count <= 0 or name == "未分类":
            if name == "未分类":
                uncategorized += count
            continue
        if _is_plausible_category(name):
            ranked.append((name, count))
        else:
            uncategorized += count

    ranked.sort(key=lambda x: (-x[1], x[0]))
    head = ranked[:limit]
    tail = ranked[limit:]
    items = [
        {
            "name": name,
            "count": count,
            "ratio": round(count / full_total * 100, 2),
        }
        for name, count in head
    ]
    other = sum(count for _, count in tail) + uncategorized
    if other > 0:
        items.append(
            {
                "name": "其他",
                "count": other,
                "ratio": round(other / full_total * 100, 2),
            }
        )
    categorized = full_total - uncategorized
    return items, full_total, categorized


def _normalize_category_key(name: str) -> str:
    """聚合统计用：别名合并 + 脏值过滤。"""
    canonical = _rollup_category(_canonical_category_name(name))
    if not _is_plausible_category(canonical):
        return "未分类"
    return canonical or "未分类"


def _categories_from_counters(
    cat_qualified: Counter[str],
    cat_unqualified: Counter[str],
    *,
    limit: int = 12,
    min_samples: int = 100,
) -> list[dict[str, Any]]:
    merged_q: Counter[str] = Counter()
    merged_u: Counter[str] = Counter()
    for name, count in cat_qualified.items():
        merged_q[_normalize_category_key(name)] += count
    for name, count in cat_unqualified.items():
        merged_u[_normalize_category_key(name)] += count
    cat_qualified = merged_q
    cat_unqualified = merged_u
    items: list[dict[str, Any]] = []
    for name in set(cat_qualified) | set(cat_unqualified):
        if name == "未分类" or not _is_plausible_category(name):
            continue
        q_count = cat_qualified[name]
        u_count = cat_unqualified[name]
        total = q_count + u_count
        if total < min_samples:
            continue
        items.append(
            {
                "category": name,
                "qualified_count": q_count,
                "unqualified_count": u_count,
                "total_count": total,
                "qualified_ratio": round(q_count / total * 100, 2) if total else 0,
                "unqualified_ratio": round(u_count / total * 100, 2) if total else 0,
                "failure_rate": round(u_count / total * 100, 2) if total else 0,
            }
        )

    items.sort(key=lambda x: (-x["failure_rate"], -x["total_count"]))
    return items[:limit]


def _build_category_breakdown(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """按食品分类汇总合格/不合格项次占比。"""
    cat_qualified: Counter[str] = Counter()
    cat_unqualified: Counter[str] = Counter()

    for record in qualified:
        cat = _normalize_category(record)
        if cat:
            cat_qualified[cat] += 1
    for record in unqualified:
        cat = _normalize_category(record)
        if cat:
            cat_unqualified[cat] += 1

    return _categories_from_counters(cat_qualified, cat_unqualified, limit=limit)


def _overview_scope(province: str, city: str) -> tuple[str, str]:
    if city and city != "全部":
        return city, "city"
    if province and province != "全部":
        return province, "province"
    return "全国", "national"


def _overview_result(
    *,
    province: str,
    city: str,
    q_count: int,
    u_count: int,
    cat_qualified: Counter[str],
    cat_unqualified: Counter[str],
) -> dict[str, Any]:
    scope, scope_type = _overview_scope(province, city)
    unqualified_categories, _, categorized_count = _unqualified_category_share(
        cat_unqualified,
        total_unqualified=u_count,
    )
    return {
        "scope": scope,
        "scope_type": scope_type,
        "province": province,
        "city": city,
        "qualified_count": q_count,
        "unqualified_count": u_count,
        "total_count": q_count + u_count,
        "failure_rate": round(u_count / (q_count + u_count) * 100, 2) if q_count + u_count else 0,
        "categories": _categories_from_counters(cat_qualified, cat_unqualified),
        "unqualified_categories": unqualified_categories,
        "unqualified_categories_total": u_count,
        "unqualified_categorized_count": categorized_count,
        "unqualified_uncategorized_count": max(u_count - categorized_count, 0),
    }


def build_overview_index(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """单次遍历构建总览图索引，供按省市即时查询。"""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}

    def _bucket(key: tuple[str, str]) -> dict[str, Any]:
        if key not in buckets:
            buckets[key] = {
                "qualified_count": 0,
                "unqualified_count": 0,
                "cat_qualified": Counter(),
                "cat_unqualified": Counter(),
            }
        return buckets[key]

    def _ingest(record: dict[str, Any], *, is_qualified: bool) -> None:
        prov = resolve_folder_province(record) or "未知"
        city = resolve_record_city(record) or ""
        cat = _normalize_category(record)
        weight = 1 if is_qualified else _unqualified_item_weight(record)
        keys = [(prov, "全部")]
        if city:
            keys.append((prov, city))
        for key in keys:
            slot = _bucket(key)
            if is_qualified:
                slot["qualified_count"] += 1
                slot["cat_qualified"][cat] += 1
            else:
                slot["unqualified_count"] += weight
                slot["cat_unqualified"][cat] += weight

    national = _bucket(("全部", "全部"))
    for record in qualified:
        _ingest(record, is_qualified=True)
        cat = _normalize_category(record)
        national["qualified_count"] += 1
        national["cat_qualified"][cat] += 1
    for record in unqualified:
        weight = _unqualified_item_weight(record)
        _ingest(record, is_qualified=False)
        cat = _normalize_category(record)
        national["unqualified_count"] += weight
        national["cat_unqualified"][cat] += weight

    return buckets


def lookup_overview_chart(
    index: dict[tuple[str, str], dict[str, Any]],
    province: str = "全部",
    city: str = "全部",
) -> dict[str, Any]:
    province = province or "全部"
    city = city or "全部"
    slot = index.get((province, city))
    if not slot:
        return _overview_result(
            province=province,
            city=city,
            q_count=0,
            u_count=0,
            cat_qualified=Counter(),
            cat_unqualified=Counter(),
        )
    return _overview_result(
        province=province,
        city=city,
        q_count=slot["qualified_count"],
        u_count=slot["unqualified_count"],
        cat_qualified=slot["cat_qualified"],
        cat_unqualified=slot["cat_unqualified"],
    )


def build_overview_chart(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    province: str = "全部",
    city: str = "全部",
) -> dict[str, Any]:
    """按所选省市汇总合格/不合格项次，供总览图表使用。"""
    index = build_overview_index(qualified, unqualified)
    return lookup_overview_chart(index, province, city)


def _map_region_entry(slot: dict[str, Any]) -> dict[str, Any]:
    q_count = slot["qualified_count"]
    u_count = slot["unqualified_count"]
    total = q_count + u_count
    return {
        "qualified_count": q_count,
        "unqualified_count": u_count,
        "total_count": total,
        "failure_rate": round(u_count / total * 100, 2) if total else 0,
    }


def lookup_overview_map(
    index: dict[tuple[str, str], dict[str, Any]],
    province: str = "全部",
    city: str = "",
) -> dict[str, Any]:
    """供地图着色：全国各省或某省内各城市的不合格率。"""
    province = province or "全部"

    provinces: list[dict[str, Any]] = []
    for (prov, city_name), slot in index.items():
        if city_name != "全部" or prov == "全部":
            continue
        entry = _map_region_entry(slot)
        provinces.append({"name": prov, **entry})

    provinces.sort(key=lambda item: item["failure_rate"], reverse=True)
    rates = [item["failure_rate"] for item in provinces if item["total_count"] > 0]

    result: dict[str, Any] = {
        "level": "province",
        "scope": "全国",
        "regions": provinces,
        "max_failure_rate": max(rates) if rates else 0,
        "min_failure_rate": min(rates) if rates else 0,
    }

    if province != "全部":
        cities: list[dict[str, Any]] = []
        for (prov, city_name), slot in index.items():
            if prov != province or not city_name or city_name == "全部":
                continue
            entry = _map_region_entry(slot)
            cities.append({"name": city_name, **entry})
        cities.sort(key=lambda item: item["failure_rate"], reverse=True)
        city_rates = [item["failure_rate"] for item in cities if item["total_count"] > 0]
        result = {
            "level": "city",
            "scope": province,
            "province": province,
            "regions": cities,
            "max_failure_rate": max(city_rates) if city_rates else 0,
            "min_failure_rate": min(city_rates) if city_rates else 0,
        }

    return result


def lookup_city_district_map(
    index: dict[tuple[str, str], dict[str, Any]],
    province: str,
    city: str,
    *,
    qualified: list[dict[str, Any]] | None = None,
    unqualified: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """某市内各区县不合格率（从地址提取区县名）。"""
    from food_inspection.mysql_search import extract_county_from_address

    districts: dict[str, dict[str, int]] = defaultdict(lambda: {"qualified": 0, "unqualified": 0})

    def _consume(records: list[dict[str, Any]], *, qualified_row: bool) -> None:
        for record in records:
            if (record.get("province") or "") != province:
                continue
            if resolve_record_city(record) != city:
                continue
            county = extract_county_from_address(
                record.get("sampled_company_address") or record.get("address") or "",
                city,
            )
            name = county or "未标注"
            key = "qualified" if qualified_row else "unqualified"
            districts[name][key] += 1

    if qualified is not None and unqualified is not None:
        _consume(qualified, qualified_row=True)
        _consume(unqualified, qualified_row=False)
    else:
        for (prov, c), slot in index.items():
            if prov != province or c != city:
                continue
            # 索引无区县维度时无法从 index 还原
            break

    regions: list[dict[str, Any]] = []
    for name, counts in districts.items():
        q_count = counts["qualified"]
        u_count = counts["unqualified"]
        regions.append(
            {
                "name": name,
                **_map_region_entry(
                    {"qualified_count": q_count, "unqualified_count": u_count}
                ),
            }
        )

    regions.sort(key=lambda item: item["failure_rate"], reverse=True)
    rates = [item["failure_rate"] for item in regions if item["total_count"] > 0]
    return {
        "level": "district",
        "scope": f"{province} · {city}",
        "province": province,
        "city": city,
        "regions": regions,
        "max_failure_rate": max(rates) if rates else 0,
        "min_failure_rate": min(rates) if rates else 0,
    }


def _company_pass_ranking_from_stats(
    stats: dict[str, dict[str, Any]],
    *,
    min_samples: int = 3,
    limit: int = 3,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for company, info in stats.items():
        if company == "未知公司" or is_invalid_company(company):
            continue
        qualified_count = info["qualified"]
        unqualified_count = info["unqualified"]
        total = qualified_count + unqualified_count
        if total < min_samples:
            continue
        results.append(
            {
                "company": company,
                "qualified_count": qualified_count,
                "unqualified_count": unqualified_count,
                "total_count": total,
                "pass_rate": round(qualified_count / total * 100, 2),
            }
        )
    results.sort(
        key=lambda item: (item["pass_rate"], item["total_count"], item["qualified_count"]),
        reverse=True,
    )
    return results[:limit]


def _product_pass_ranking_from_stats(
    stats: dict[str, dict[str, Any]],
    *,
    min_samples: int = 5,
    limit: int = 3,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for product, info in stats.items():
        qualified_count = info["qualified"]
        unqualified_count = info["unqualified"]
        total = qualified_count + unqualified_count
        if total < min_samples:
            continue
        results.append(
            {
                "product": product,
                "qualified_count": qualified_count,
                "unqualified_count": unqualified_count,
                "total_count": total,
                "pass_rate": round(qualified_count / total * 100, 2),
            }
        )
    results.sort(
        key=lambda item: (item["pass_rate"], item["total_count"], item["qualified_count"]),
        reverse=True,
    )
    return results[:limit]


def city_insight_min_samples(total_count: int) -> tuple[int, int]:
    """按区域样本量动态调整榜单最低抽检次数（企业, 产品）。"""
    if total_count <= 0:
        return 3, 5
    if total_count <= 15:
        return 1, 1
    if total_count <= 50:
        return 2, 2
    if total_count <= 200:
        return 2, 3
    return 3, 5


def build_city_insights(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
    province: str,
    city: str,
    *,
    limit: int = 3,
) -> dict[str, Any]:
    """城市下钻：风险/优秀企业与产品各取前几名。"""
    scope_province = province or "全部"
    scope_city = city or "全部"
    q_scope = _mapped_records(
        _filter_by_city(_filter_by_province(qualified, scope_province), scope_city)
    )
    u_scope = _mapped_records(
        _filter_by_city(_filter_by_province(unqualified, scope_province), scope_city)
    )
    company_stats = _aggregate_company_stats_lists(q_scope, u_scope)

    product_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"qualified": 0, "unqualified": 0, "reasons": Counter()}
    )
    for record in q_scope:
        product = _record_sub_category(record)
        if product:
            product_stats[product]["qualified"] += 1
    for record in u_scope:
        product = _record_sub_category(record)
        if product:
            product_stats[product]["unqualified"] += 1

    q_count = len(q_scope)
    u_count = sum(_unqualified_item_weight(record) for record in u_scope)
    total = q_count + u_count
    company_min, product_min = city_insight_min_samples(total)

    return {
        "province": scope_province,
        "city": scope_city,
        "qualified_count": q_count,
        "unqualified_count": u_count,
        "total_count": total,
        "failure_rate": round(u_count / total * 100, 2) if total else 0,
        "top_risk_companies": _company_failure_ranking_from_stats(
            company_stats, min_samples=company_min, limit=limit
        ),
        "top_risk_products": _build_product_failure_ranking_lists(
            q_scope, u_scope, min_samples=product_min, limit=limit
        ),
        "top_safe_companies": _company_pass_ranking_from_stats(
            company_stats, min_samples=company_min, limit=limit
        ),
        "top_safe_products": _product_pass_ranking_from_stats(
            product_stats, min_samples=product_min, limit=limit
        ),
    }
