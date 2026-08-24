"""核查处置/风险控制正文：期号校验与正文 hash 去重。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path

from config import ROOT_DIR
from food_inspection.parser.fields import source_relative_key

_DISPOSAL_PERIOD_RE = re.compile(r"(\d{4})年\s*第(\d+)期")
_ANNOUNCEMENT_PERIOD_PATTERNS = (
    re.compile(
        r"关于不合格(?:食品|产品)?[^（(]{0,40}?(?:核查处置|风险控制)[^（(]{0,40}?通告"
        r"[（(](\d{4})年\s*第(\d+)期[）)]"
    ),
    re.compile(
        r"(?:核查处置|风险控制)情况的通告[（(](\d{4})年\s*第(\d+)期[）)]"
    ),
    re.compile(
        r"市场监督管理局关于[^（(]{0,80}?通告[（(](\d{4})年\s*第(\d+)期[）)]"
    ),
)
_HASH_FILE = Path(ROOT_DIR) / "data" / "disposal_body_hashes.json"
_HASH_LOCK = threading.Lock()
_MIN_BODY_CHARS = 120


def _period_token(year: str, issue: str) -> str:
    return f"{year}年第{issue}期"


def _compact_disposal_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _disposal_core_text(text: str) -> str:
    """去掉政府网站导航壳，保留通告正文主体。"""
    compact = _compact_disposal_text(text)
    for marker in (
        "现将不合格食品核查处置情况通告如下",
        "不合格食品核查处置情况通告如下",
        "核查处置情况通告如下",
        "风险控制情况通告如下",
        "通告如下",
    ):
        if marker in compact:
            return compact[compact.index(marker) :]
    match = re.search(r"[一二三四五六七八九十百]+、.{8,}", compact)
    if match:
        return compact[match.start() :]
    return compact


def extract_disposal_path_period(filepath: str) -> str | None:
    """从文件夹/文件名提取期号（优先父目录）。"""
    for part in (
        os.path.basename(os.path.dirname(filepath)),
        os.path.basename(filepath),
    ):
        match = _DISPOSAL_PERIOD_RE.search(part)
        if match:
            return _period_token(match.group(1), match.group(2))
    return None


def extract_disposal_announcement_period(text: str) -> str | None:
    """从正文标题提取通告期号。"""
    compact = _compact_disposal_text(text)
    for pattern in _ANNOUNCEMENT_PERIOD_PATTERNS:
        match = pattern.search(compact)
        if match:
            return _period_token(match.group(1), match.group(2))
    return None


def is_disposal_period_mismatch(filepath: str, text: str) -> bool:
    """正文标题期号与文件夹期号不一致时视为脏数据。"""
    path_period = extract_disposal_path_period(filepath)
    body_period = extract_disposal_announcement_period(text)
    if not path_period or not body_period:
        return False
    return path_period != body_period


def disposal_body_fingerprint(text: str) -> str | None:
    """正文核心内容 hash（去掉网站导航壳）。"""
    core = _disposal_core_text(text)
    if len(core) < _MIN_BODY_CHARS:
        return None
    return hashlib.sha256(core.encode("utf-8")).hexdigest()


def _load_hash_index() -> dict[str, str]:
    if not _HASH_FILE.is_file():
        return {}
    try:
        payload = json.loads(_HASH_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return {str(k): str(v) for k, v in payload.items()}
    except Exception:
        pass
    return {}


def _save_hash_index(data: dict[str, str]) -> None:
    _HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HASH_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


def is_duplicate_disposal_body(filepath: str, text: str) -> bool:
    """相同正文已在其他源文件中入库/登记。"""
    digest = disposal_body_fingerprint(text)
    if not digest:
        return False
    rel = source_relative_key(filepath) or filepath.replace("\\", "/")
    with _HASH_LOCK:
        index = _load_hash_index()
        owner = index.get(digest)
        return bool(owner and owner != rel)


def claim_disposal_body(filepath: str, text: str) -> bool:
    """登记正文 hash；若已被其他文件占用则返回 False。"""
    digest = disposal_body_fingerprint(text)
    if not digest:
        return True
    rel = source_relative_key(filepath) or filepath.replace("\\", "/")
    with _HASH_LOCK:
        index = _load_hash_index()
        owner = index.get(digest)
        if owner and owner != rel:
            return False
        index[digest] = rel
        _save_hash_index(index)
        return True


def should_skip_disposal_narrative(filepath: str, text: str) -> str | None:
    """返回跳过原因：period_mismatch / duplicate_body；None 表示可解析。"""
    if is_disposal_period_mismatch(filepath, text):
        return "period_mismatch"
    if is_duplicate_disposal_body(filepath, text):
        return "duplicate_body"
    return None


def rebuild_disposal_body_hash_index(filepaths: list[str]) -> int:
    """从磁盘重建正文 hash 索引（仅保留期号一致且无重复的首个文件）。"""
    from food_inspection.parser.disposal_narrative import extract_disposal_narrative_text

    index: dict[str, str] = {}
    for filepath in sorted(filepaths):
        if not os.path.isfile(filepath):
            continue
        text = extract_disposal_narrative_text(filepath)
        if not text or is_disposal_period_mismatch(filepath, text):
            continue
        digest = disposal_body_fingerprint(text)
        if not digest or digest in index:
            continue
        rel = source_relative_key(filepath) or filepath.replace("\\", "/")
        index[digest] = rel
    with _HASH_LOCK:
        _save_hash_index(index)
    return len(index)
