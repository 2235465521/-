#!/usr/bin/env python3
"""清理期号不一致/正文重复的核查处置记录，并重建正文 hash 索引。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import DATA_ROOT
from food_inspection.db import connection
from food_inspection.parser.disposal_dedup import (
    _HASH_FILE,
    rebuild_disposal_body_hash_index,
    should_skip_disposal_narrative,
)
from food_inspection.parser.disposal_narrative import (
    _is_disposal_narrative_file,
    extract_disposal_narrative_text,
    is_skippable_disposal_zhengwen,
)
from food_inspection.parser.fields import source_relative_key
from food_inspection.parser.parse import iter_excel_files
from food_inspection.pipeline.db_store import delete_file_source


def _collect_disposal_files() -> list[str]:
    paths: list[str] = []
    for fp in iter_excel_files(DATA_ROOT):
        if not _is_disposal_narrative_file(fp):
            continue
        if is_skippable_disposal_zhengwen(fp):
            continue
        paths.append(fp)
    return paths


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    files = _collect_disposal_files()
    skip_map: dict[str, str] = {}
    keep_files: list[str] = []

    for fp in files:
        text = extract_disposal_narrative_text(fp)
        if not text:
            continue
        reason = should_skip_disposal_narrative(fp, text)
        rel = source_relative_key(fp) or fp.replace("\\", "/")
        if reason:
            skip_map[rel] = reason
        else:
            keep_files.append(fp)

    deleted_rows = 0
    deleted_files = 0
    with connection() as conn, conn.cursor() as cur:
        for rel in sorted(skip_map):
            n = delete_file_source(cur, rel)
            if n:
                deleted_files += 1
                deleted_rows += n
        conn.commit()

    if _HASH_FILE.is_file():
        _HASH_FILE.unlink()
    indexed = rebuild_disposal_body_hash_index(keep_files)

    print(f"核查处置正文扫描: {len(files)}")
    print(f"跳过入库: {len(skip_map)} (期号不一致/正文重复)")
    print(f"保留正文: {len(keep_files)}")
    print(f"库内删除: {deleted_files} 文件 / {deleted_rows} 条")
    print(f"hash 索引: {indexed} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
