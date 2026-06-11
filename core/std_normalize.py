"""标准编号与 PDF 文件名的规范化与互转（如 YD/T ↔ YDT、GB/T ↔ GBT）。"""

from __future__ import annotations

import re
from pathlib import Path

# 匹配标准号主体：前缀 + 编号 + 年份，如 YD/T 1234.1-2020
_STD_CORE = re.compile(
    r"^([A-Z]{1,6}(?:/[A-Z])?)\s*([\d]+(?:\.\d+)*)\s*[-－—]?\s*(\d{2,4})?\s*$",
    re.IGNORECASE,
)
# 紧凑写法：YDT1234-2020、GBT1002-2024
_STD_COMPACT = re.compile(
    r"^([A-Z]{2,5})([TZX])([\d]+(?:\.\d+)*)(?:[-－—](\d{2,4}))?$",
    re.IGNORECASE,
)


def normalize_std_id(std_id: str) -> str:
    """紧凑等价键：忽略空格、斜杠、连字符与大小写（用于文件名/模糊等价）。"""
    s = std_id.strip().upper()
    s = s.replace("／", "/")
    s = re.sub(r"\s+", "", s)
    s = s.replace("/", "")
    s = re.sub(r"[-－—]+", "", s)
    return s


def std_id_norm_key(std_id: str) -> str:
    """与 SQLite std_id_norm 列、build_index 一致（去空白、保留斜杠）。"""
    return "".join(std_id.strip().upper().split())


def std_id_compact_key(std_id: str) -> str:
    """同 normalize_std_id。"""
    return normalize_std_id(std_id)


def _dash_variants(s: str) -> set[str]:
    out = {s}
    if "-" in s:
        out.add(s.replace("-", "—"))
        out.add(s.replace("-", "－"))
        out.add(re.sub(r"-+", "", s))
    return out


def std_id_lookup_variants(query: str) -> list[str]:
    """生成用于数据库精确匹配的多种写法。"""
    raw = query.strip()
    if not raw:
        return []
    variants: set[str] = set()
    variants.add(raw)
    upper = raw.upper()
    variants.add(upper)
    collapsed = re.sub(r"\s+", " ", upper).strip()
    variants.add(collapsed)

    no_space = re.sub(r"\s+", "", upper)
    variants.add(no_space)
    variants.update(_dash_variants(no_space))

    no_slash = no_space.replace("/", "")
    variants.add(no_slash)
    variants.update(_dash_variants(no_slash))

    # YDT1234 -> YD/T 1234（补斜杠，便于命中库中带 / 的编号）
    m = _STD_CORE.match(no_slash.replace("-", " "))
    if not m:
        m = _STD_CORE.match(no_space)
    if m:
        prefix, num, year = m.group(1), m.group(2), m.group(3) or ""
        if "/" not in prefix and len(prefix) >= 3 and prefix[-1] in "TZX":
            slash_prefix = prefix[:-1] + "/" + prefix[-1]
            body = f"{slash_prefix} {num}"
            if year:
                body += f"-{year}"
            variants.add(body)
            variants.add(body.replace(" ", ""))
            variants.add(re.sub(r"\s+", "", body.upper()))

    # 去重并保持顺序
    ordered: list[str] = []
    for v in variants:
        v = v.strip()
        if v and v not in ordered:
            ordered.append(v)
    return ordered


def pdf_basename_variants(file_name: str, std_id: str | None = None) -> list[str]:
    """生成可能在磁盘上出现的 PDF 文件名（含 / 与不含 /）。"""
    names: list[str] = []

    def add(name: str) -> None:
        name = name.strip()
        if not name:
            return
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        if name not in names:
            names.append(name)

    for src in (file_name, std_id):
        if not src:
            continue
        base = Path(src.replace("\\", "/")).name
        add(base)
        add(base.replace("/", ""))
        add(re.sub(r"\s+", "", base))
        add(re.sub(r"\s+", " ", base.replace("/", " ")).strip())

        # 将 XXX/T 转为 XXXT（PDF 常见写法）
        compact = re.sub(r"\s+", "", base.upper())
        no_slash = compact.replace("/", "")
        add(no_slash)
        m = _STD_CORE.match(no_slash.replace("-", " "))
        if m and "/" not in m.group(1):
            p = m.group(1)
            if len(p) >= 3 and p[-1] in "TZX":
                add(base.replace(p, p[:-1] + "/" + p[-1], 1))

    if std_id:
        norm = normalize_std_id(std_id)
        # 用标准号核心在磁盘中模糊匹配：*YDT1234*2020*.pdf
        core = re.sub(r"^([A-Z]+)", r"\1", norm)  # already normalized
        if len(core) >= 4:
            add(f"{core}.pdf")

    return names


def pdf_path_variants(rel_path: str, file_name: str, std_id: str | None = None) -> list[str]:
    """生成待尝试的相对路径列表。"""
    paths: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        p = p.replace("\\", "/").lstrip("/")
        if p and p not in seen:
            seen.add(p)
            paths.append(p)

    add(rel_path)
    add(rel_path.replace("/", ""))

    dir_part = str(Path(rel_path.replace("\\", "/")).parent)
    if dir_part and dir_part != ".":
        for bn in pdf_basename_variants(file_name, std_id):
            add(f"{dir_part}/{bn}")
    else:
        for bn in pdf_basename_variants(file_name, std_id):
            add(bn)

    return paths


def filename_contains_std_id(filename: str, std_id: str) -> bool:
    """判断文件名是否包含与标准号等价的编号（忽略 /、空格及 _F_ 等后缀）。"""
    stem = Path(filename).stem.upper()
    stem = re.sub(r"_[FTZX]_", "_", stem)
    fn_norm = normalize_std_id(stem)
    sid_norm = normalize_std_id(std_id)
    if not sid_norm or len(sid_norm) < 4:
        return False
    return sid_norm in fn_norm


def std_id_glob_patterns(std_id: str) -> list[str]:
    """生成磁盘搜索用的通配符（如 JBT 11509 与 JBT11509 两种写法）。"""
    norm = normalize_std_id(std_id)
    patterns: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        if p not in seen:
            seen.add(p)
            patterns.append(p)

    add(f"*{norm}*.pdf")
    compact = norm.replace("—", "-").replace("－", "-")
    m = _STD_COMPACT.match(compact)
    if m:
        p1, p2, num, year = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        add(f"*{p1}{p2}*{num}*.pdf")
        add(f"*{p1}{p2} {num}*.pdf")
        if year:
            add(f"*{p1}{p2}*{num}*{year}*.pdf")
            add(f"*{p1}{p2} {num}*{year}*.pdf")
            add(f"*{num}*{year}*.pdf")
    return patterns
