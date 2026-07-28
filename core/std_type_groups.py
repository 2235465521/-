"""标准类型：按四类（国/行/地/团）分组，组内按首字母排序。"""
from __future__ import annotations

GROUP_ORDER = (
    "国家标准",
    "行业标准",
    "地方标准",
    "团体标准",
)

_CN_NAME_MAP = {
    "国标": "国家标准",
    "国家标准": "国家标准",
    "行标": "行业标准",
    "行业标准": "行业标准",
    "地标": "地方标准",
    "地方标准": "地方标准",
    "团标": "团体标准",
    "团体标准": "团体标准",
    # 企标不再单独成类，并入行业标准
    "企标": "行业标准",
    "企业标准": "行业标准",
}


def classify_std_type(raw: str) -> str:
    """将库内 std_type（代号或中文简称）归入四类之一。"""
    t = (raw or "").strip()
    if not t:
        return "行业标准"
    if t in _CN_NAME_MAP:
        return _CN_NAME_MAP[t]

    u = t.upper().replace(" ", "")
    if u.startswith("GB"):
        return "国家标准"
    if u.startswith("DB"):
        return "地方标准"
    # 团体标准多为 T/xxx；单独的 T 也归团体。TB/T、TD/T 等为行业标准
    if u == "T" or u.startswith("T/"):
        return "团体标准"
    return "行业标准"


def _sort_key(label: str) -> tuple:
    s = (label or "").strip()
    # 字母/数字代号优先按 ASCII 不区分大小写；中文按原文字符序
    return (s.casefold(), s)


def group_std_types(types: list[str], *, include_empty: bool = False) -> list[dict]:
    """
    返回 [{"name": "国家标准", "items": ["GB", "GB/T", ...]}, ...]
    默认空分组不返回；组内按首字母（不区分大小写）排序。
    include_empty=True 时四类均返回（items 可为 []），供大类下拉使用。
    """
    buckets: dict[str, list[str]] = {g: [] for g in GROUP_ORDER}
    seen: set[str] = set()
    for raw in types or []:
        t = (raw or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        buckets[classify_std_type(t)].append(t)

    out: list[dict] = []
    for name in GROUP_ORDER:
        items = sorted(buckets[name], key=_sort_key)
        if items or include_empty:
            out.append({"name": name, "items": items})
    return out


def _norm_expr(col: str = "b.std_type") -> str:
    """SQL：去空格并转大写，便于与代号规则对齐。"""
    return f"UPPER(REPLACE(TRIM({col}), ' ', ''))"


def std_category_clause(category: str, *, param: str = "%s") -> tuple[str | None, list]:
    """
    按四类大类生成 SQL 条件与绑定参数。
    规则与 classify_std_type 一致；行业标准 = 非国/地/团。
    LIKE 模式一律走绑定参数，避免与 PyMySQL 的 %s 格式化冲突。
    """
    cat = (category or "").strip()
    if cat not in GROUP_ORDER:
        return None, []

    n = _norm_expr()
    is_gb = (
        f"({n} LIKE {param} OR TRIM(b.std_type) IN ({param}, {param}))"
    )
    gb_args = ["GB%", "国标", "国家标准"]
    is_db = (
        f"({n} LIKE {param} OR TRIM(b.std_type) IN ({param}, {param}))"
    )
    db_args = ["DB%", "地标", "地方标准"]
    is_t = (
        f"({n} = {param} OR {n} LIKE {param} "
        f"OR TRIM(b.std_type) IN ({param}, {param}))"
    )
    t_args = ["T", "T/%", "团标", "团体标准"]
    nonempty = "(b.std_type IS NOT NULL AND TRIM(b.std_type) != '')"

    if cat == "国家标准":
        return is_gb, gb_args
    if cat == "地方标准":
        return is_db, db_args
    if cat == "团体标准":
        return is_t, t_args
    # 行业标准：其余非空类型（含原企标等）
    sql = f"({nonempty} AND NOT ({is_gb} OR {is_db} OR {is_t}))"
    return sql, gb_args + db_args + t_args


def std_category_sql(category: str) -> str | None:
    sql, _ = std_category_clause(category)
    return sql
