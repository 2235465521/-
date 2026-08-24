"""数据缓存、内存状态与扫描调度。"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any

from config import (
    AUTO_SCAN_INTERVAL_SEC,
    CACHE_FILE,
    DATA_ROOT,
    DISABLE_AUTO_SCAN,
    PENDING_COUNT_TTL_SEC,
    ROOT_DIR,
)
from food_inspection.analytics import (
    build_analytics,
    build_overview_index,
    count_qualified_items,
    count_unqualified_items,
)
from food_inspection.parser import resolve_folder_province, resolve_record_city
from food_inspection.redis_cache import get_json as redis_get_json
from food_inspection.redis_cache import set_json as redis_set_json
from food_inspection.scan import count_pending_work, repair_cache_payload, scan_files

_cache_mtime: float | None = None
_pending_count_cache: dict[str, int] | None = None
_pending_count_ts: float = 0.0
_pending_count_running = False
_pending_count_lock = threading.Lock()
_scan_lock = threading.Lock()
_scan_state: dict[str, Any] = {
    "running": False,
    "progress": 0,
    "total": 0,
    "message": "",
    "finished_at": None,
    "error": None,
    "auto_scan_enabled": not DISABLE_AUTO_SCAN,
    "pending_new": 0,
}
_data: dict[str, Any] = {
    "qualified": [],
    "unqualified": [],
    "stats": {},
    "scan_info": {},
}
_overview_index: dict | None = None
_overview_index_lock = threading.Lock()
_cities_index: dict[str, list[str]] | None = None
_cities_index_lock = threading.Lock()
_scope_index: dict[tuple[str, str, str], list[dict[str, Any]]] | None = None
_scope_index_lock = threading.Lock()
_provinces_list: list[str] | None = None
_ANALYTICS_CACHE_VERSION = 49
_analytics_cache: dict[tuple[str, str, str, int], dict[str, Any]] = {}
_analytics_cache_lock = threading.Lock()
_analytics_compute_lock = threading.Lock()
_analytics_jobs: set[tuple[Any, ...]] = set()
_analytics_jobs_lock = threading.Lock()
_ANALYTICS_DISK_DIR = os.environ.get(
    "ANALYTICS_DISK_DIR",
    os.path.join(ROOT_DIR, "data", "analytics_disk_cache"),
)


def _analytics_cache_digest(key: tuple[Any, ...]) -> str:
    return hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:20]


def _analytics_redis_key(key: tuple[Any, ...]) -> str:
    return f"analytics:{_analytics_cache_digest(key)}"


def _analytics_disk_path(key: tuple[Any, ...]) -> str:
    digest = _analytics_cache_digest(key)
    os.makedirs(_ANALYTICS_DISK_DIR, exist_ok=True)
    return os.path.join(_ANALYTICS_DISK_DIR, f"{digest}.json")


def _read_analytics_disk(key: tuple[Any, ...]) -> dict[str, Any] | None:
    cached = redis_get_json(_analytics_redis_key(key))
    if cached and int(cached.get("cache_version") or 0) == _ANALYTICS_CACHE_VERSION:
        return cached
    path = _analytics_disk_path(key)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if int(data.get("cache_version") or 0) == _ANALYTICS_CACHE_VERSION:
            redis_set_json(_analytics_redis_key(key), data, ttl_sec=86400)
        return data
    except Exception:
        return None


def _write_analytics_disk(key: tuple[Any, ...], result: dict[str, Any]) -> None:
    try:
        path = _analytics_disk_path(key)
        payload = dict(result)
        payload["cache_version"] = _ANALYTICS_CACHE_VERSION
        sanitized = _sanitize_for_json(payload)
        redis_set_json(_analytics_redis_key(key), sanitized, ttl_sec=86400)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(sanitized, handle, ensure_ascii=False)
    except Exception:
        pass


def _looks_like_analytics_payload(data: dict[str, Any]) -> bool:
    return bool(
        data.get("total")
        or data.get("item_types")
        or data.get("top_failure_products")
        or data.get("repeat_product_count")
    )


def _read_fallback_analytics_disk(
    province: str,
    city: str,
    date_from: str = "",
    date_to: str = "",
) -> dict[str, Any] | None:
    """版本升级后精确 key 未命中时，仅复用同版本磁盘缓存。"""
    if not os.path.isdir(_ANALYTICS_DISK_DIR):
        return None
    best: dict[str, Any] | None = None
    best_mtime = 0.0
    for name in os.listdir(_ANALYTICS_DISK_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(_ANALYTICS_DISK_DIR, name)
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            if int(data.get("cache_version") or 0) != _ANALYTICS_CACHE_VERSION:
                continue
            if not _looks_like_analytics_payload(data):
                continue
            if (data.get("province") or "全部") != (province or "全部"):
                continue
            if (data.get("city") or "全部") != (city or "全部"):
                continue
            if date_from and (data.get("date_from") or "") not in ("", date_from):
                continue
            if date_to and (data.get("date_to") or "") not in ("", date_to):
                continue
            mtime = os.path.getmtime(path)
            if mtime >= best_mtime:
                best = data
                best_mtime = mtime
        except Exception:
            continue
    return best


def _analytics_loading_payload(province: str, city: str) -> dict[str, Any]:
    return {
        "loading": True,
        "message": "统计数据计算中，请稍候…",
        "data_source": "mysql",
        "province": province or "全部",
        "city": city or "全部",
        "total": 0,
        "item_types": [],
        "item_types_total": 0,
        "item_types_unique": 0,
        "top_failure_products": [],
        "repeat_products": [],
        "repeat_product_count": 0,
        "repeat_company_count": 0,
        "perfect_company_count": 0,
        "perfect_manufacturer_count": 0,
    }


def _compute_analytics_payload(
    key: tuple[Any, ...],
    scope_province: str,
    scope_city: str,
    min_violations: int,
    min_repeat_violations: int,
    date_from: str | None,
    date_to: str | None,
) -> dict[str, Any] | None:
    try:
        from food_inspection.mysql_search import mysql_enabled
        from food_inspection.mysql_stats import get_mysql_analytics

        if mysql_enabled():
            mysql_result = get_mysql_analytics(
                scope_province,
                scope_city,
                min_violations,
                min_repeat_violations=min_repeat_violations,
                date_from=date_from or None,
                date_to=date_to or None,
            )
            if mysql_result is not None:
                with _analytics_cache_lock:
                    _analytics_cache[key] = mysql_result
                _write_analytics_disk(key, mysql_result)
                return mysql_result
    except Exception:
        pass

    payload = get_data()
    result = build_analytics(
        payload.get("unqualified", []),
        payload.get("qualified", []),
        scope_province,
        scope_city,
        min_violations,
        min_repeat_violations=min_repeat_violations,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    with _analytics_cache_lock:
        _analytics_cache[key] = result
    _write_analytics_disk(key, result)
    return result


def _schedule_analytics_compute(
    key: tuple[Any, ...],
    scope_province: str,
    scope_city: str,
    min_violations: int,
    min_repeat_violations: int,
    date_from: str | None,
    date_to: str | None,
) -> None:
    with _analytics_jobs_lock:
        if key in _analytics_jobs:
            return
        _analytics_jobs.add(key)

    def _run() -> None:
        try:
            with _analytics_compute_lock:
                with _analytics_cache_lock:
                    if _analytics_cache.get(key):
                        return
                _compute_analytics_payload(
                    key,
                    scope_province,
                    scope_city,
                    min_violations,
                    min_repeat_violations,
                    date_from,
                    date_to,
                )
        finally:
            with _analytics_jobs_lock:
                _analytics_jobs.discard(key)

    threading.Thread(target=_run, daemon=True, name="analytics-compute").start()
_cache_load_lock = threading.Lock()
_cache_loading = False


def _sync_item_stats(payload: dict[str, Any]) -> None:
    """将 stats 中的合格/不合格数同步为项次口径（与 analytics 一致）。"""
    qualified = payload.get("qualified", [])
    unqualified = payload.get("unqualified", [])
    stats = payload.setdefault("stats", {})
    stats["qualified_count"] = count_qualified_items(qualified)
    stats["unqualified_count"] = count_unqualified_items(unqualified)
    stats["count_mode"] = "item"


def get_data() -> dict[str, Any]:
    return _data


def is_cache_loading() -> bool:
    return _cache_loading


def get_scan_state() -> dict[str, Any]:
    with _scan_lock:
        return dict(_scan_state)


def get_overview_index() -> dict | None:
    with _overview_index_lock:
        return _overview_index


def get_cities(province: str = "全部") -> list[str] | None:
    with _cities_index_lock:
        if _cities_index is None:
            return None
        if province and province != "全部":
            return list(_cities_index.get(province, []))
        return list(_cities_index.get("全部", []))


def get_provinces() -> list[str]:
    global _provinces_list
    if _provinces_list is not None:
        return list(_provinces_list)
    stats = _data.get("stats", {}).get("provinces", {})
    return sorted(stats.keys())


def get_scoped_records(
    record_type: str,
    province: str = "全部",
    city: str = "全部",
) -> list[dict[str, Any]] | None:
    prov = province or "全部"
    scope_city = city or "全部"
    with _scope_index_lock:
        if _scope_index is None:
            return None
        if scope_city != "全部":
            return _scope_index.get((record_type, prov, scope_city))
        return _scope_index.get((record_type, prov, "全部"))


def is_pending_count_computing() -> bool:
    with _pending_count_lock:
        return _pending_count_running


def invalidate_analytics_cache() -> None:
    global _analytics_cache
    with _analytics_cache_lock:
        _analytics_cache = {}


def invalidate_indexes() -> None:
    global _overview_index, _cities_index, _scope_index, _provinces_list
    invalidate_analytics_cache()
    with _overview_index_lock:
        _overview_index = None
    with _cities_index_lock:
        _cities_index = None
    with _scope_index_lock:
        _scope_index = None
    _provinces_list = None


def get_analytics(
    province: str = "全部",
    city: str = "全部",
    min_violations: int = 2,
    min_repeat_violations: int = 5,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    scope_province = province or "全部"
    scope_city = city or "全部"
    scope_date_from = date_from or ""
    scope_date_to = date_to or ""
    key = (
        scope_province,
        scope_city,
        _ANALYTICS_CACHE_VERSION,
        min_violations,
        min_repeat_violations,
        scope_date_from,
        scope_date_to,
    )

    def _cache_hit(cached: dict[str, Any] | None) -> bool:
        if cached is None:
            return False
        try:
            from food_inspection.mysql_search import mysql_enabled

            if mysql_enabled():
                return cached.get("data_source") == "mysql"
        except Exception:
            pass
        payload = get_data()
        has_records = bool(payload.get("qualified") or payload.get("unqualified"))
        cached_empty = not (
            cached.get("total")
            or cached.get("perfect_company_count")
            or cached.get("top_failure_companies")
        )
        return not (has_records and cached_empty)

    with _analytics_cache_lock:
        cached = _analytics_cache.get(key)
    if _cache_hit(cached):
        return cached

    disk_cached = _read_analytics_disk(key)
    if _cache_hit(disk_cached):
        with _analytics_cache_lock:
            _analytics_cache[key] = disk_cached
        return disk_cached

    fallback = _read_fallback_analytics_disk(
        scope_province, scope_city, scope_date_from, scope_date_to
    )
    if fallback and _cache_hit(fallback):
        _schedule_analytics_compute(
            key,
            scope_province,
            scope_city,
            min_violations,
            min_repeat_violations,
            date_from,
            date_to,
        )
        return fallback

    _schedule_analytics_compute(
        key,
        scope_province,
        scope_city,
        min_violations,
        min_repeat_violations,
        date_from,
        date_to,
    )
    return fallback or _analytics_loading_payload(scope_province, scope_city)


def schedule_analytics_prewarm() -> None:
    if os.environ.get("DISABLE_ANALYTICS_PREWARM", "").strip().lower() in ("1", "true", "yes"):
        return
    key = ("全部", "全部", _ANALYTICS_CACHE_VERSION, 2, 5, "", "")
    disk_cached = _read_analytics_disk(key)
    if disk_cached and _looks_like_analytics_payload(disk_cached):
        with _analytics_cache_lock:
            _analytics_cache[key] = disk_cached
        print("[预热] 分析缓存已从磁盘载入，跳过重算", flush=True)
        return
    _schedule_analytics_compute(key, "全部", "全部", 2, 5, None, None)


def schedule_stats_prewarm() -> None:
    def _run() -> None:
        try:
            from food_inspection.mysql_stats import get_mysql_stats

            stats = get_mysql_stats()
            if stats:
                print(
                    f"[预热] 统计缓存就绪：合格 {stats.get('qualified_count', 0):,}，"
                    f"不合格 {stats.get('unqualified_count', 0):,}",
                    flush=True,
                )
        except Exception as exc:
            print(f"[预热] 统计缓存失败: {exc}", flush=True)

    threading.Thread(target=_run, daemon=True, name="stats-prewarm").start()


def build_scope_index(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    def _add(bucket: str, record: dict[str, Any]) -> None:
        province = resolve_folder_province(record) or "未知"
        city = resolve_record_city(record) or ""
        keys = {(bucket, "全部", "全部"), (bucket, province, "全部")}
        if city:
            keys.add((bucket, province, city))
        for key in keys:
            index.setdefault(key, []).append(record)

    for record in qualified:
        _add("qualified", record)
    for record in unqualified:
        _add("unqualified", record)
    return index


def schedule_index_rebuild(*, prewarm_analytics: bool = True) -> None:
    qualified = list(_data.get("qualified", []))
    unqualified = list(_data.get("unqualified", []))
    if not qualified and not unqualified:
        return

    def _run() -> None:
        global _overview_index, _cities_index, _scope_index, _provinces_list
        overview = build_overview_index(qualified, unqualified)
        cities = build_cities_index(qualified, unqualified)
        scope = build_scope_index(qualified, unqualified)
        provinces = sorted(_data.get("stats", {}).get("provinces", {}).keys())
        with _overview_index_lock:
            _overview_index = overview
        with _cities_index_lock:
            _cities_index = cities
        with _scope_index_lock:
            _scope_index = scope
        _provinces_list = provinces
        if prewarm_analytics:
            get_analytics("全部", "全部", 2)

    threading.Thread(target=_run, daemon=True, name="index-rebuild").start()


def empty_data() -> dict[str, Any]:
    return {
        "qualified": [],
        "unqualified": [],
        "stats": {
            "qualified_count": 0,
            "unqualified_count": 0,
            "total_files": 0,
            "parsed_files": 0,
            "failed_files": 0,
            "provinces": {},
        },
        "scan_info": {},
    }


def _split_cache_paths() -> tuple[str, str, str]:
    base = CACHE_FILE[:-5] if CACHE_FILE.lower().endswith(".json") else CACHE_FILE
    return (
        f"{base}_meta.json",
        f"{base}_qualified.jsonl",
        f"{base}_unqualified.jsonl",
    )


def _sanitize_for_json(obj: Any) -> Any:
    from decimal import Decimal

    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    return str(obj)


def _write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")
    os.replace(tmp, path)


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _cache_marker_mtime() -> float | None:
    meta_path, _, _ = _split_cache_paths()
    if os.path.isfile(meta_path):
        return os.path.getmtime(meta_path)
    if os.path.isfile(CACHE_FILE):
        return os.path.getmtime(CACHE_FILE)
    return None


def _migrate_legacy_cache_to_split() -> dict[str, Any] | None:
    """将超大单体 JSON 缓存流式拆分为 meta + jsonl，避免一次性 read 导致 MemoryError。"""
    if not os.path.isfile(CACHE_FILE):
        return None
    meta_path, qual_path, unqual_path = _split_cache_paths()
    if os.path.isfile(meta_path):
        return load_cache()

    try:
        import ijson  # type: ignore
    except ImportError:
        return None

    meta: dict[str, Any] = {"stats": {}, "scan_info": {}}
    try:
        with open(CACHE_FILE, "rb") as f:
            for key in ("stats", "scan_info"):
                try:
                    f.seek(0)
                    meta[key] = _sanitize_for_json(next(ijson.items(f, key), {}))
                except (ijson.JSONError, StopIteration):
                    meta[key] = {}
        _write_jsonl(qual_path, [])
        _write_jsonl(unqual_path, [])
        with open(qual_path, "w", encoding="utf-8") as qf, open(
            unqual_path, "w", encoding="utf-8"
        ) as uqf:
            with open(CACHE_FILE, "rb") as f:
                for rec in ijson.items(f, "qualified.item"):
                    qf.write(json.dumps(rec, ensure_ascii=False))
                    qf.write("\n")
            with open(CACHE_FILE, "rb") as f:
                for rec in ijson.items(f, "unqualified.item"):
                    uqf.write(json.dumps(rec, ensure_ascii=False))
                    uqf.write("\n")
        meta_tmp = f"{meta_path}.tmp"
        with open(meta_tmp, "w", encoding="utf-8") as mf:
            json.dump(meta, mf, ensure_ascii=False)
        os.replace(meta_tmp, meta_path)
        legacy_bak = f"{CACHE_FILE}.legacy.bak"
        if not os.path.isfile(legacy_bak):
            os.replace(CACHE_FILE, legacy_bak)
        with open(CACHE_FILE, "w", encoding="utf-8") as mf:
            json.dump({"format": "split", "meta": meta_path}, mf, ensure_ascii=False)
        return {
            **meta,
            "qualified": _read_jsonl(qual_path),
            "unqualified": _read_jsonl(unqual_path),
        }
    except (OSError, json.JSONDecodeError, MemoryError, ValueError):
        return None


def save_cache(payload: dict[str, Any]) -> None:
    meta_path, qual_path, unqual_path = _split_cache_paths()
    meta = _sanitize_for_json(
        {
            "stats": payload.get("stats", {}),
            "scan_info": payload.get("scan_info", {}),
        }
    )
    meta_tmp = f"{meta_path}.tmp"
    with open(meta_tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(meta_tmp, meta_path)
    _write_jsonl(qual_path, payload.get("qualified", []))
    _write_jsonl(unqual_path, payload.get("unqualified", []))
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"format": "split", "meta": meta_path}, f, ensure_ascii=False)


def _maybe_repair_loaded_cache(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("qualified") and not payload.get("unqualified"):
        return payload
    repaired = repair_cache_payload(payload)
    dropped = repaired.get("scan_info", {}).get("dropped_duplicate_records", 0)
    locations_repaired = repaired.get("scan_info", {}).get("locations_repaired", 0)
    old_parsed = payload.get("stats", {}).get("parsed_files")
    new_parsed = repaired.get("stats", {}).get("parsed_files")
    old_provinces = set(payload.get("stats", {}).get("provinces", {}).keys())
    new_provinces = set(repaired.get("stats", {}).get("provinces", {}).keys())
    if (
        dropped
        or locations_repaired
        or old_parsed != new_parsed
        or old_provinces != new_provinces
    ):
        save_cache(repaired)
    return repaired


def load_cache() -> dict[str, Any] | None:
    meta_path, qual_path, unqual_path = _split_cache_paths()
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            payload = {
                **meta,
                "qualified": _read_jsonl(qual_path),
                "unqualified": _read_jsonl(unqual_path),
            }
            return _maybe_repair_loaded_cache(payload)
        except (json.JSONDecodeError, OSError, MemoryError):
            return None

    if not os.path.isfile(CACHE_FILE):
        return None

    try:
        if os.path.getsize(CACHE_FILE) > 80 * 1024 * 1024:
            migrated = _migrate_legacy_cache_to_split()
            if migrated is not None:
                return _maybe_repair_loaded_cache(migrated)
    except OSError:
        return None

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("format") == "split":
            return load_cache()
        if isinstance(data, dict):
            return _maybe_repair_loaded_cache(data)
        return data
    except MemoryError:
        migrated = _migrate_legacy_cache_to_split()
        return _maybe_repair_loaded_cache(migrated) if migrated is not None else migrated
    except (json.JSONDecodeError, OSError):
        return None


def _cached_payload_for_scan() -> dict[str, Any]:
    if _data.get("qualified") or _data.get("unqualified") or _data.get("stats"):
        return _data
    cached = load_cache()
    return cached or _data


def build_cities_index(
    qualified: list[dict[str, Any]],
    unqualified: list[dict[str, Any]],
) -> dict[str, list[str]]:
    by_province: dict[str, set[str]] = {"全部": set()}
    for bucket in (qualified, unqualified):
        for record in bucket:
            city = resolve_record_city(record)
            if not city:
                continue
            by_province["全部"].add(city)
            province = record.get("source_province")
            if province:
                by_province.setdefault(province, set()).add(city)
    return {key: sorted(values) for key, values in by_province.items()}


def schedule_overview_index_rebuild() -> None:
    schedule_index_rebuild(prewarm_analytics=False)


def schedule_cities_index_rebuild() -> None:
    schedule_index_rebuild(prewarm_analytics=False)


def _compute_pending_count() -> None:
    global _pending_count_cache, _pending_count_ts
    try:
        counts = count_pending_work(_cached_payload_for_scan())
    except Exception:
        counts = {"pending_new": 0, "skipped_non_detail": 0}
    with _scan_lock:
        _pending_count_cache = counts
        _pending_count_ts = time.time()
        _scan_state["pending_new"] = counts.get("pending_new", 0)


def refresh_pending_count(*, force: bool = False, blocking: bool = False) -> int:
    global _pending_count_running

    now = time.time()
    with _scan_lock:
        if (
            not force
            and _pending_count_cache is not None
            and now - _pending_count_ts < PENDING_COUNT_TTL_SEC
        ):
            return _scan_state.get("pending_new", _pending_count_cache.get("pending_new", 0))

    def _start_compute() -> None:
        global _pending_count_running
        with _pending_count_lock:
            _pending_count_running = True
        try:
            _compute_pending_count()
        finally:
            with _pending_count_lock:
                _pending_count_running = False

    if blocking:
        _start_compute()
    else:
        with _pending_count_lock:
            already_running = _pending_count_running
        if not already_running:
            threading.Thread(
                target=_start_compute,
                daemon=True,
                name="pending-count",
            ).start()

    with _scan_lock:
        if _pending_count_cache is not None:
            return _scan_state.get("pending_new", _pending_count_cache.get("pending_new", 0))
        return _scan_state.get("pending_new", 0)


def start_background_scan(*, full_rescan: bool = False, trigger: str = "manual") -> bool:
    with _scan_lock:
        if _scan_state["running"]:
            return False

    def _run() -> None:
        scan_data(full_rescan=full_rescan, trigger=trigger)

    label = "auto-scan" if trigger == "auto" else "scan"
    threading.Thread(target=_run, daemon=True, name=label).start()
    return True


def scan_data(full_rescan: bool = False, *, trigger: str = "manual") -> dict[str, Any]:
    global _data, _cache_mtime

    with _scan_lock:
        if _scan_state["running"]:
            return _data
        mode_label = "自动增量" if trigger == "auto" else ("全量" if full_rescan else "增量")
        _scan_state.update(
            {
                "running": True,
                "progress": 0,
                "total": 0,
                "message": f"正在{mode_label}扫描...",
                "error": None,
            }
        )

    cached = load_cache() if not full_rescan else None

    def _progress(current: int, total: int, message: str) -> None:
        with _scan_lock:
            _scan_state["progress"] = current
            _scan_state["total"] = total
            _scan_state["message"] = message

    try:
        payload = scan_files(cached=cached, full_rescan=full_rescan, progress_cb=_progress)
    except Exception as exc:
        with _scan_lock:
            _scan_state.update(
                {
                    "running": False,
                    "error": str(exc),
                    "message": f"扫描失败: {exc}",
                }
            )
        raise

    save_cache(payload)
    _cache_mtime = _cache_marker_mtime()

    with _scan_lock:
        _data = payload
    invalidate_indexes()
    schedule_index_rebuild()
    refresh_pending_count(force=True, blocking=True)
    with _scan_lock:
        pending = _scan_state.get("pending_new", 0)
        _scan_state.update(
            {
                "running": False,
                "progress": payload["scan_info"].get("new_files_processed", 0),
                "total": payload["scan_info"].get("new_files_processed", 0),
                "message": (
                    f"扫描完成（{'全量' if full_rescan else '增量'}，"
                    f"本次处理 {payload['scan_info'].get('new_files_processed', 0)} 个文件）"
                ),
                "finished_at": payload["scan_info"]["scanned_at"],
                "pending_new": pending,
            }
        )

    return payload


def reload_data_if_cache_updated() -> None:
    global _data, _cache_mtime
    if _cache_loading:
        return
    mtime = _cache_marker_mtime()
    if mtime is None:
        return
    if _cache_mtime is not None and mtime <= _cache_mtime:
        return
    with _cache_load_lock:
        if _cache_loading:
            return
        cached = load_cache()
    if cached:
        _sync_item_stats(cached)
        _data = cached
        _cache_mtime = mtime
        invalidate_indexes()
        schedule_index_rebuild()
        with _scan_lock:
            _scan_state["finished_at"] = cached.get("scan_info", {}).get("scanned_at")
            _scan_state["message"] = "已加载最新缓存数据"


def _run_startup_tasks() -> None:
    global _pending_count_running

    with _pending_count_lock:
        _pending_count_running = True
    try:
        _compute_pending_count()
    finally:
        with _pending_count_lock:
            _pending_count_running = False

    if DISABLE_AUTO_SCAN:
        return
    if not os.path.isdir(DATA_ROOT):
        with _scan_lock:
            _scan_state["message"] = f"数据目录不可用: {DATA_ROOT}"
        return
    with _scan_lock:
        pending = _scan_state.get("pending_new", 0)
    if pending > 0:
        start_background_scan(trigger="auto")
    elif not (_data.get("qualified") or _data.get("unqualified")):
        start_background_scan(trigger="auto")


def _bootstrap_cache_load() -> None:
    global _data, _cache_mtime, _cache_loading

    try:
        from food_inspection.mysql_search import mysql_enabled

        if mysql_enabled():
            _data = empty_data()
            with _scan_lock:
                _scan_state["message"] = "MySQL 数据就绪，正在预热统计缓存…"
            print("[缓存] MySQL 模式，跳过 JSON 缓存加载", flush=True)
            schedule_stats_prewarm()
            schedule_analytics_prewarm()
            _run_startup_tasks()
            return
    except Exception:
        pass

    print("[缓存] 正在后台加载数据，请稍候…", flush=True)
    with _scan_lock:
        _scan_state["message"] = "正在加载缓存数据，请稍候..."

    cached = None
    with _cache_load_lock:
        _cache_loading = True
        try:
            cached = load_cache()
        except MemoryError:
            cached = None
        finally:
            _cache_loading = False

    if cached:
        _sync_item_stats(cached)
        _data = cached
        _cache_mtime = _cache_marker_mtime()
        invalidate_analytics_cache()
        schedule_index_rebuild()
        with _scan_lock:
            _scan_state["finished_at"] = cached.get("scan_info", {}).get("scanned_at")
            _scan_state["message"] = "已加载缓存数据，正在后台检查新文件..."
        q = len(cached.get("qualified", []))
        u = len(cached.get("unqualified", []))
        print(f"[缓存] 加载完成：合格 {q:,} 条，不合格 {u:,} 条", flush=True)
    else:
        _data = empty_data()
        with _scan_lock:
            if _cache_marker_mtime() is not None or os.path.isfile(CACHE_FILE):
                _scan_state["message"] = "缓存过大或损坏，正在后台重建..."
            else:
                _scan_state["message"] = "正在后台准备首次扫描..."

    _run_startup_tasks()


def bootstrap() -> None:
    threading.Thread(
        target=_bootstrap_cache_load,
        daemon=True,
        name="bootstrap-cache-load",
    ).start()


def _auto_scan_loop() -> None:
    while True:
        time.sleep(AUTO_SCAN_INTERVAL_SEC)
        pending = refresh_pending_count()
        if pending > 0:
            start_background_scan(trigger="auto")


def schedule_startup_auto_scan() -> None:
    if DISABLE_AUTO_SCAN:
        return
    threading.Thread(target=_auto_scan_loop, daemon=True, name="auto-scan-periodic").start()
