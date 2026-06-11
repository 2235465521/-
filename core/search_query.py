"""检索关键词规范化与 SQL 匹配片段（容错符号/空格/大小写，提取核心词）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.std_normalize import (
    std_id_compact_key,
    std_id_norm_key,
)

_STD_FRAGMENT = re.compile(
    r"([A-Za-z]{1,6}(?:\s*/\s*[A-Za-z])?\s*[\d]+(?:\.\d+)*(?:\s*[-－—]\s*\d{2,4})?)",
    re.IGNORECASE,
)
_CHINESE_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_CHINESE_PLUS_NOISE = re.compile(r"^([\u4e00-\u9fff]{2,})\d+$")


@dataclass
class SearchIntent:
    raw: str
    cleaned: str
    std_ids: list[str] = field(default_factory=list)
    text_keywords: list[str] = field(default_factory=list)

    @property
    def primary(self) -> str:
        if self.std_ids:
            return self.std_ids[0]
        if self.text_keywords:
            return self.text_keywords[0]
        return self.cleaned


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def sanitize_std_id_input(q: str) -> str:
    """修正标准号输入中的多余斜杠、空格等。"""
    s = (q or "").strip()
    s = s.replace("／", "/")
    s = re.sub(r"/+", "/", s)
    # GB/T /1.1、GB/T//1.1 -> GB/T 1.1
    s = re.sub(r"(?<=[A-Za-z]/[A-Za-z])\s*/+\s*(?=\d)", " ", s, flags=re.IGNORECASE)
    # 前缀后缺空格：GB/T1.1 -> GB/T 1.1
    s = re.sub(
        r"^([A-Za-z]{1,6}/[A-Za-z])(\d)",
        r"\1 \2",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"^([A-Za-z]{2,5}[TZX])(\d)",
        r"\1 \2",
        s,
        flags=re.IGNORECASE,
    )
    return collapse_whitespace(s)


def chinese_core_text(q: str) -> str:
    """食/品、食 品 -> 食品（仅保留汉字序列）。"""
    chars = re.findall(r"[\u4e00-\u9fff]", q or "")
    if len(chars) >= 2:
        return "".join(chars)
    return ""


def extract_std_id_fragments(q: str) -> list[str]:
    cleaned = sanitize_std_id_input(q)
    found: list[str] = []
    seen: set[str] = set()
    for m in _STD_FRAGMENT.finditer(cleaned):
        frag = collapse_whitespace(m.group(1))
        key = frag.upper()
        if frag and key not in seen:
            seen.add(key)
            found.append(frag)
    if not found and looks_like_std_id(cleaned):
        key = cleaned.upper()
        if key not in seen:
            found.append(cleaned)
    return found


def extract_text_keywords(q: str, *, std_ids: list[str] | None = None) -> list[str]:
    raw = (q or "").strip()
    if not raw:
        return []

    std_ids = std_ids or extract_std_id_fragments(raw)
    remainder = raw
    for frag in std_ids:
        remainder = re.sub(re.escape(frag), " ", remainder, flags=re.IGNORECASE)

    keywords: list[str] = []
    seen: set[str] = set()

    def add(kw: str) -> None:
        kw = collapse_whitespace(kw)
        if len(kw) < 2:
            return
        if looks_like_std_id(kw):
            return
        if re.fullmatch(r"[A-Za-z]{1,3}", kw):
            return
        key = kw.lower()
        if key in seen:
            return
        seen.add(key)
        keywords.append(kw)

    for source in (raw, remainder):
        core = chinese_core_text(source)
        if core:
            add(core)

        m = _CHINESE_PLUS_NOISE.match(source.strip())
        if m:
            add(m.group(1))

        for m in _CHINESE_RUN.finditer(source):
            add(m.group(0))

    rem = collapse_whitespace(remainder)
    if rem:
        for m in re.finditer(r"[\u4e00-\u9fff]{2,}", rem):
            add(m.group(0))
        for m in re.finditer(r"[A-Za-z]{4,}", rem):
            add(m.group(0))

    return keywords


def parse_search_intent(q: str) -> SearchIntent:
    raw = (q or "").strip()
    cleaned = sanitize_std_id_input(collapse_whitespace(raw))
    std_ids = extract_std_id_fragments(raw)
    if not std_ids and looks_like_std_id(cleaned):
        std_ids = [cleaned]

    text_keywords = extract_text_keywords(raw, std_ids=std_ids)

    return SearchIntent(
        raw=raw,
        cleaned=cleaned,
        std_ids=std_ids,
        text_keywords=text_keywords,
    )


def normalize_search_query(q: str) -> str:
    """检索入口：清洗后返回最适合展示/记录的关键词。"""
    return parse_search_intent(q).primary or collapse_whitespace(q)


def looks_like_std_id(q: str) -> bool:
    collapsed = collapse_whitespace(q)
    if not collapsed:
        return False
    if re.search(r"[\u4e00-\u9fff]", collapsed):
        return False
    return bool(re.search(r"[A-Za-z]", collapsed)) and bool(re.search(r"\d", collapsed))


def flex_std_id_like_pattern(q: str) -> str:
    collapsed = collapse_whitespace(q).upper()
    if not collapsed:
        return "%"
    tokens = collapsed.split()
    if len(tokens) == 1:
        return f"%{tokens[0]}%"
    return "%" + "%".join(tokens) + "%"


def like_pattern(q: str) -> str:
    collapsed = collapse_whitespace(q)
    if looks_like_std_id(collapsed):
        return flex_std_id_like_pattern(collapsed)
    return f"%{collapsed}%"


def _compact_sql_expr(column: str) -> str:
    expr = f"UPPER({column})"
    for ch in (" ", "/", "-", "—", "－", "／"):
        expr = f"REPLACE({expr}, '{ch}', '')"
    return expr


def _append_std_id_match(
    parts: list[str],
    args: list[Any],
    q: str,
    *,
    param: str,
    use_std_id_norm: bool,
) -> None:
    norm_key = std_id_norm_key(q)
    compact_key = std_id_compact_key(q)
    std_compact = _compact_sql_expr("b.std_id")
    file_compact = _compact_sql_expr("f2.file_name")
    like_pat = like_pattern(q)
    flex_pat = flex_std_id_like_pattern(q)

    if use_std_id_norm:
        parts.append(f"b.std_id_norm = {param}")
        args.append(norm_key)
        parts.append(f"b.std_id_norm LIKE {param}")
        args.append(f"{norm_key}%")
        if compact_key != norm_key:
            parts.append(f"b.std_id_norm = {param}")
            args.append(compact_key)
            parts.append(f"b.std_id_norm LIKE {param}")
            args.append(f"{compact_key}%")
        return

    parts.append(f"{std_compact} = {param}")
    args.append(compact_key)
    parts.append(f"{std_compact} LIKE {param}")
    args.append(f"{compact_key}%")


def _append_text_match(parts: list[str], args: list[Any], kw: str, *, param: str) -> None:
    like_pat = like_pattern(kw)
    parts.append(f"b.std_chinesename LIKE {param}")
    args.append(like_pat)
    
    # 仅在关键词包含英文或数字时，才匹配标准号和文件名（避免纯中文关键字触发无谓的全文扫描与子查询）
    if any(c.isalnum() and not '\u4e00' <= c <= '\u9fff' for c in kw):
        parts.append(f"UPPER(b.std_id) LIKE {param}")
        args.append(f"%{kw.upper()}%")
        parts.append(
            f"EXISTS (SELECT 1 FROM std_filepath f2 WHERE f2.base_id = b.id AND UPPER(f2.file_name) LIKE {param})"
        )
        args.append(f"%{kw.upper()}%")


def build_keyword_match_clause(
    q: str,
    *,
    param: str = "?",
    use_std_id_norm: bool = True,
) -> tuple[str, list[Any]]:
    q = (q or "").strip()
    if not q:
        return "", []

    intent = parse_search_intent(q)
    parts: list[str] = []
    args: list[Any] = []

    std_targets = intent.std_ids or ([intent.cleaned] if looks_like_std_id(intent.cleaned) else [])
    for std_q in std_targets[:3]:
        _append_std_id_match(parts, args, std_q, param=param, use_std_id_norm=use_std_id_norm)

    text_targets = intent.text_keywords or (
        [intent.cleaned] if intent.cleaned and not looks_like_std_id(intent.cleaned) else []
    )
    for kw in text_targets[:4]:
        _append_text_match(parts, args, kw, param=param)

    if not parts:
        _append_text_match(parts, args, intent.cleaned or q, param=param)

    return "(" + " OR ".join(parts) + ")", args


def keyword_match_order_by(q: str, *, param: str = "?") -> tuple[str, list[Any]]:
    intent = parse_search_intent(q)
    primary = intent.primary or q
    if not primary:
        return "b.std_id", []

    norm_key = std_id_norm_key(primary)
    compact_key = std_id_compact_key(primary)
    std_compact = _compact_sql_expr("b.std_id")
    like_pat = like_pattern(primary)
    flex_pat = flex_std_id_like_pattern(primary) if looks_like_std_id(primary) else like_pat
    text_like = f"%{primary}%"

    order = (
        f"CASE "
        f"WHEN b.std_id_norm = {param} THEN 0 "
        f"WHEN b.std_id_norm LIKE {param} THEN 1 "
        f"WHEN {std_compact} = {param} THEN 2 "
        f"WHEN {std_compact} LIKE {param} THEN 3 "
        f"WHEN REPLACE(UPPER(b.std_id), ' ', '') = {param} THEN 4 "
        f"WHEN UPPER(b.std_id) = {param} THEN 5 "
        f"WHEN UPPER(b.std_id) LIKE {param} THEN 6 "
        f"WHEN UPPER(b.std_id) LIKE {param} THEN 7 "
        f"WHEN b.std_chinesename LIKE {param} THEN 8 "
        f"ELSE 9 END, b.std_id"
    )
    return order, [
        norm_key,
        f"{norm_key}%",
        compact_key,
        f"{compact_key}%",
        norm_key,
        primary.upper(),
        like_pat,
        flex_pat,
        text_like,
    ]


def mysql_keyword_match_order_by(q: str) -> tuple[str, list[Any]]:
    intent = parse_search_intent(q)
    primary = intent.primary or q
    if not primary:
        return "b.std_id", []

    norm_key = std_id_norm_key(primary)
    compact_key = std_id_compact_key(primary)
    std_compact = _compact_sql_expr("b.std_id")
    like_pat = like_pattern(primary)
    flex_pat = flex_std_id_like_pattern(primary) if looks_like_std_id(primary) else like_pat
    text_like = f"%{primary}%"

    order = (
        f"CASE "
        f"WHEN REPLACE(UPPER(b.std_id), ' ', '') = %s THEN 0 "
        f"WHEN REPLACE(UPPER(b.std_id), ' ', '') LIKE %s THEN 1 "
        f"WHEN {std_compact} = %s THEN 2 "
        f"WHEN {std_compact} LIKE %s THEN 3 "
        f"WHEN UPPER(b.std_id) = %s THEN 4 "
        f"WHEN UPPER(b.std_id) LIKE %s THEN 5 "
        f"WHEN UPPER(b.std_id) LIKE %s THEN 6 "
        f"WHEN b.std_chinesename LIKE %s THEN 7 "
        f"ELSE 8 END, b.std_id"
    )
    return order, [
        norm_key,
        f"{norm_key}%",
        compact_key,
        f"{compact_key}%",
        primary.upper(),
        like_pat,
        flex_pat,
        text_like,
    ]
