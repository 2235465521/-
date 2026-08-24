"""统一数据访问 Seam：InspectionRepository

深模块 (Deep Module)：
- 统一 Interface：对外提供一致的数据检索、聚合统计与榜单洞察方法。
- Ports & Adapters：
  - MySQLInspectionAdapter：直接利用 MySQL 索引与 SQL 聚合（生产默认）。
  - InMemoryInspectionAdapter：基于加载到内存中的 data_cache.json / SQLite（用于开发/测试/无 DB 离线模式）。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from config import USE_MYSQL


@runtime_checkable
class InspectionRepository(Protocol):
    """抽检数据仓储标准接口 (The Seam Interface)"""

    is_mysql: bool

    def is_ready(self) -> bool:
        """仓储底层数据是否准备就绪"""
        ...

    def get_scan_info(self) -> dict[str, Any]:
        """获取当前扫描与索引元信息"""
        ...

    def get_stats(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """获取全国/过滤日期范围内的总体统计"""
        ...

    def get_provinces(self) -> list[str]:
        """获取所有有数据的省份列表"""
        ...

    def get_cities(self, province: str = "全部") -> list[str]:
        """获取指定省份下的城市列表"""
        ...

    def search_records(
        self,
        status: str = "qualified",
        province: str = "全部",
        city: str = "全部",
        county: str = "",
        company: str = "",
        product: str = "",
        category: str = "",
        item: str = "",
        reason: str = "",
        q: str = "",
        entity_role: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        page_size: int = 50,
        skip_total: bool = False,
    ) -> dict[str, Any]:
        """分页搜索抽检明细记录"""
        ...

    def get_overview_chart(
        self,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """获取省市概览图表数据"""
        ...

    def get_overview_map(
        self,
        province: str = "全部",
        city: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """获取省市地图分布数据"""
        ...

    def get_city_insights(
        self,
        province: str,
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 3,
    ) -> dict[str, Any]:
        """获取城市深度洞察（重点企业、高发问题）"""
        ...

    def get_province_trend(
        self,
        province: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """获取省份历史趋势"""
        ...

    def get_unit_ranks(
        self,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """获取企业红黑榜"""
        ...

    def get_product_ranks(
        self,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """获取产品品类榜单"""
        ...

    def get_company_stats(
        self,
        keyword: str,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """获取特定企业主体抽检记录统计"""
        ...

    def get_analytics(
        self,
        province: str = "全部",
        city: str = "全部",
        min_violations: int = 2,
        min_repeat_violations: int = 5,
        date_from: str | None = None,
        date_to: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """获取多维交叉分析指标"""
        ...


def _read_ranks_helper(rank_type: str, province: str, city: str, date_from: str | None, date_to: str | None) -> dict[str, Any]:
    """统一榜单读取与加载态封装"""
    from food_inspection.rank_store import read_product_ranks, read_unit_ranks
    fn = read_unit_ranks if rank_type == "unit" else read_product_ranks
    res = fn(province, city, date_from, date_to)
    if not res:
        label = "单位" if rank_type == "unit" else "产品"
        return {
            "loading": True,
            "message": f"{label}榜单数据加载中，请稍后重试",
            "province": province,
            "city": city,
        }
    return res


def _read_company_stats_helper(keyword: str, province: str, city: str, date_from: str | None, date_to: str | None) -> dict[str, Any]:
    """统一企业主体抽检数据统计"""
    from food_inspection import store
    from food_inspection.analytics import build_company_stats
    from food_inspection.date_scope import filter_records_by_date_range

    if not keyword:
        return {"items": [], "total": 0}
    data = store.get_data()
    qualified = filter_records_by_date_range(data.get("qualified", []), date_from, date_to)
    unqualified = filter_records_by_date_range(data.get("unqualified", []), date_from, date_to)
    items = build_company_stats(qualified, unqualified, keyword, province, city)
    return {"items": items, "total": len(items)}


class MySQLInspectionAdapter:
    """基于 MySQL 数据库的仓储适配器"""

    is_mysql: bool = True

    def is_ready(self) -> bool:
        from food_inspection.db import ping
        return ping()

    def get_scan_info(self) -> dict[str, Any]:
        from food_inspection import store
        return store.get_data().get("scan_info", {})

    def get_stats(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        from food_inspection import store
        from food_inspection.mysql_stats import get_mysql_stats

        stats = get_mysql_stats()
        if stats is not None:
            state = store.get_scan_state()
            stats["pending_new"] = state.get("pending_new", 0)
            stats["scanned_at"] = None
            return stats
        return {"error": "MySQL 统计暂不可用", "loading": True}

    def get_provinces(self) -> list[str]:
        from food_inspection.region_meta import get_provinces
        return get_provinces()

    def get_cities(self, province: str = "全部") -> list[str]:
        from food_inspection.region_meta import get_cities
        return get_cities(province)

    def search_records(
        self,
        status: str = "qualified",
        province: str = "全部",
        city: str = "全部",
        county: str = "",
        company: str = "",
        product: str = "",
        category: str = "",
        item: str = "",
        reason: str = "",
        q: str = "",
        entity_role: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        page_size: int = 50,
        skip_total: bool = False,
    ) -> dict[str, Any]:
        from food_inspection.mysql_search import search_records
        return search_records(
            status=status,
            province=province,
            city=city,
            county=county,
            company=company,
            product=product,
            category=category,
            item=item,
            reason=reason,
            q=q,
            entity_role=entity_role,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
            skip_total=skip_total,
        )

    def get_overview_chart(
        self,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        from food_inspection.mysql_stats import get_mysql_overview_chart
        res = get_mysql_overview_chart(province, city, date_from, date_to)
        if res is not None:
            res["date_from"] = date_from or ""
            res["date_to"] = date_to or ""
            return res
        return {"loading": True, "message": "图表计算中…"}

    def get_overview_map(
        self,
        province: str = "全部",
        city: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        from food_inspection.mysql_stats import get_mysql_overview_map
        from food_inspection.region_cache import _cache_key, get_or_compute, map_loading_payload

        key = _cache_key("map", province, city, date_from or "", date_to or "")
        result = get_or_compute(
            key,
            lambda: get_mysql_overview_map(province, date_from, date_to, city=city),
            loading_factory=lambda: map_loading_payload(province, city),
            allow_async=True,
        )
        if result:
            result["date_from"] = date_from or ""
            result["date_to"] = date_to or ""
            return result
        return {"loading": True, "message": "地图统计计算中，请稍候…"}

    def get_city_insights(
        self,
        province: str,
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 3,
    ) -> dict[str, Any]:
        from food_inspection.mysql_stats import get_mysql_city_insights
        from food_inspection.region_cache import _cache_key, get_or_compute, insights_loading_payload

        key = _cache_key("insights", province, city, date_from or "", date_to or "", limit)
        result = get_or_compute(
            key,
            lambda: get_mysql_city_insights(province, city, date_from, date_to, limit=limit),
            loading_factory=lambda: insights_loading_payload(province, city),
            allow_async=True,
        )
        if result:
            result["limit"] = limit
            result["date_from"] = date_from or ""
            result["date_to"] = date_to or ""
            return result
        return insights_loading_payload(province, city)

    def get_province_trend(
        self,
        province: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        from food_inspection.mysql_stats import get_mysql_province_trend
        return get_mysql_province_trend(province, date_from=date_from, date_to=date_to)

    def get_unit_ranks(
        self,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        return _read_ranks_helper("unit", province, city, date_from, date_to)

    def get_product_ranks(
        self,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        return _read_ranks_helper("product", province, city, date_from, date_to)

    def get_company_stats(
        self,
        keyword: str,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        return _read_company_stats_helper(keyword, province, city, date_from, date_to)

    def get_analytics(
        self,
        province: str = "全部",
        city: str = "全部",
        min_violations: int = 2,
        min_repeat_violations: int = 5,
        date_from: str | None = None,
        date_to: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        from food_inspection import store
        from food_inspection.analytics import light_refresh_analytics_display, refresh_analytics_failure_names

        result = store.get_analytics(
            province,
            city,
            min_violations,
            min_repeat_violations=min_repeat_violations,
            date_from=date_from,
            date_to=date_to,
        )
        if (
            not force_refresh
            and result
            and not result.get("loading")
            and result.get("data_source") == "mysql"
            and (
                result.get("total")
                or result.get("top_failure_companies")
                or result.get("item_types")
            )
        ):
            return result
        return light_refresh_analytics_display(refresh_analytics_failure_names(result))


class InMemoryInspectionAdapter:
    """基于内存数据缓存 (data_cache.json) 的仓储适配器"""

    is_mysql: bool = False

    def is_ready(self) -> bool:
        from food_inspection import store
        return not store.is_cache_loading()

    def get_scan_info(self) -> dict[str, Any]:
        from food_inspection import store
        return store.get_data().get("scan_info", {})

    def get_stats(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        from food_inspection import store
        from food_inspection.analytics import count_qualified_items, count_unqualified_items

        if store.is_cache_loading():
            return {
                "qualified_count": 0,
                "unqualified_count": 0,
                "total_files": 0,
                "parsed_files": 0,
                "provinces": {},
                "count_mode": "item",
                "cache_loading": True,
                "message": "正在加载缓存数据，请稍候…",
            }
        data = store.get_data()
        stats = dict(data.get("stats", {}))
        if stats.get("count_mode") != "item":
            qualified = data.get("qualified", [])
            unqualified = data.get("unqualified", [])
            stats["qualified_count"] = count_qualified_items(qualified)
            stats["unqualified_count"] = count_unqualified_items(unqualified)
            stats["count_mode"] = "item"
        stats["scanned_at"] = data.get("scan_info", {}).get("scanned_at")
        state = store.get_scan_state()
        stats["pending_new"] = state.get("pending_new", 0)
        stats["skipped_non_detail_files"] = stats.get(
            "skipped_non_detail_files",
            data.get("scan_info", {}).get("skipped_non_detail", 0),
        )
        stats["skipped_non_detail"] = stats["skipped_non_detail_files"]
        return stats

    def get_provinces(self) -> list[str]:
        from food_inspection import store
        return store.get_provinces()

    def get_cities(self, province: str = "全部") -> list[str]:
        from food_inspection import store
        from food_inspection.parser import resolve_record_city

        cached = store.get_cities(province)
        if cached is not None:
            return cached
        cities: set[str] = set()
        data = store.get_data()
        for bucket in ("qualified", "unqualified"):
            for record in data.get(bucket, []):
                if province and province != "全部" and record.get("source_province") != province:
                    continue
                city = resolve_record_city(record)
                if city:
                    cities.add(city)
        return sorted(cities)

    def search_records(
        self,
        status: str = "qualified",
        province: str = "全部",
        city: str = "全部",
        county: str = "",
        company: str = "",
        product: str = "",
        category: str = "",
        item: str = "",
        reason: str = "",
        q: str = "",
        entity_role: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        page_size: int = 50,
        skip_total: bool = False,
    ) -> dict[str, Any]:
        from food_inspection import store
        from food_inspection.date_scope import filter_records_by_date_range
        from food_inspection.parser import resolve_folder_province, resolve_record_city

        records = store.get_scoped_records(status, province, city)
        scope_applied = records is not None
        if records is None:
            records = store.get_data().get(status, [])

        filtered = records
        if not scope_applied:
            if province and province != "全部":
                filtered = [r for r in filtered if resolve_folder_province(r) == province]
            if city and city != "全部":
                filtered = [r for r in filtered if resolve_record_city(r) == city]

        has_field_filters = any((company, product, item, reason, category, county))
        if has_field_filters:
            result = []
            for r in filtered:
                if company:
                    if entity_role == "manufacturer":
                        if company not in (r.get("manufacturer") or "").lower():
                            continue
                    elif entity_role == "sampled":
                        if company not in (r.get("sampled_company") or r.get("company") or "").lower():
                            continue
                    elif company not in (r.get("company") or "").lower() and company not in (r.get("manufacturer") or "").lower():
                        continue
                if product and product not in (r.get("product") or "").lower():
                    continue
                if item and item not in (r.get("unqualified_item") or "").lower():
                    continue
                if reason and reason not in (r.get("reason") or "").lower():
                    continue
                if category and category not in (r.get("category") or "").lower():
                    continue
                if county and county not in (r.get("county") or r.get("province_city") or "").lower():
                    continue
                result.append(r)
            filtered = result
        elif q:
            kw = q.lower()
            filtered = [
                r for r in filtered
                if kw in (r.get("company") or "").lower()
                or kw in (r.get("product") or "").lower()
                or kw in (r.get("province_city") or "").lower()
                or kw in (r.get("unqualified_item") or "").lower()
                or kw in (r.get("category") or "").lower()
                or kw in (r.get("reason") or "").lower()
            ]

        filtered = filter_records_by_date_range(filtered, date_from, date_to)
        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size

        return {
            "items": filtered[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max((total + page_size - 1) // page_size, 1),
        }

    def get_overview_chart(
        self,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        from food_inspection import store
        from food_inspection.analytics import build_overview_chart, lookup_overview_chart

        index = store.get_overview_index()
        data = store.get_data()
        if index is not None and not date_from and not date_to:
            result = lookup_overview_chart(index, province, city)
        else:
            qualified, unqualified = self._overview_records(date_from, date_to)
            result = build_overview_chart(qualified, unqualified, province, city)
        result["date_from"] = date_from or ""
        result["date_to"] = date_to or ""
        return result

    def get_overview_map(
        self,
        province: str = "全部",
        city: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        from food_inspection import store
        from food_inspection.analytics import build_overview_index, lookup_city_district_map, lookup_overview_map

        if store.is_cache_loading():
            return {"loading": True, "message": "正在加载缓存数据，请稍候…"}
        qualified, unqualified = self._overview_records(date_from, date_to)
        if city and city != "全部" and province != "全部":
            result = lookup_city_district_map(
                {}, province, city, qualified=qualified, unqualified=unqualified
            )
        elif date_from or date_to:
            index = build_overview_index(qualified, unqualified)
            result = lookup_overview_map(index, province)
        else:
            index = store.get_overview_index()
            if index is None:
                return {"loading": True, "message": "索引预计算中，请稍候…"}
            result = lookup_overview_map(index, province)
        result["date_from"] = date_from or ""
        result["date_to"] = date_to or ""
        return result

    def get_city_insights(
        self,
        province: str,
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 3,
    ) -> dict[str, Any]:
        from food_inspection import store
        from food_inspection.analytics import build_city_insights

        if store.is_cache_loading():
            return {"loading": True, "message": "正在加载缓存数据，请稍候…"}
        qualified, unqualified = self._overview_records(date_from, date_to)
        result = build_city_insights(qualified, unqualified, province, city, limit=limit)
        result["limit"] = limit
        result["date_from"] = date_from or ""
        result["date_to"] = date_to or ""
        return result

    def get_province_trend(
        self,
        province: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        return {"error": "离线缓存模式暂不支持趋势分析，请配置 MySQL"}

    def get_unit_ranks(
        self,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        return _read_ranks_helper("unit", province, city, date_from, date_to)

    def get_product_ranks(
        self,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        return _read_ranks_helper("product", province, city, date_from, date_to)

    def get_company_stats(
        self,
        keyword: str,
        province: str = "全部",
        city: str = "全部",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        return _read_company_stats_helper(keyword, province, city, date_from, date_to)

    def get_analytics(
        self,
        province: str = "全部",
        city: str = "全部",
        min_violations: int = 2,
        min_repeat_violations: int = 5,
        date_from: str | None = None,
        date_to: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        from food_inspection import store
        from food_inspection.analytics import light_refresh_analytics_display, refresh_analytics_failure_names

        result = store.get_analytics(
            province,
            city,
            min_violations,
            min_repeat_violations=min_repeat_violations,
            date_from=date_from,
            date_to=date_to,
        )
        return light_refresh_analytics_display(refresh_analytics_failure_names(result))

    def _overview_records(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[list, list]:
        from food_inspection import store
        from food_inspection.date_scope import filter_records_by_date_range

        data = store.get_data()
        qualified = data.get("qualified", [])
        unqualified = data.get("unqualified", [])
        if date_from or date_to:
            qualified = filter_records_by_date_range(qualified, date_from, date_to)
            unqualified = filter_records_by_date_range(unqualified, date_from, date_to)
        return qualified, unqualified


# 单例实例
_mysql_adapter = MySQLInspectionAdapter()
_in_memory_adapter = InMemoryInspectionAdapter()


def get_current_repository() -> InspectionRepository:
    """获取当前生效的数据仓储适配器"""
    from food_inspection.mysql_search import mysql_enabled
    if mysql_enabled():
        return _mysql_adapter
    return _in_memory_adapter
