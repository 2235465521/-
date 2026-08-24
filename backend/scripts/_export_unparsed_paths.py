"""Export unparsed file paths grouped by reason tag."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import scripts._bootstrap  # noqa: F401

from config import CACHE_FILE, OUTPUT_DIR
from scripts._report_unparsed import region, tag_empty, tag_failed


def main() -> None:
    with open(CACHE_FILE, encoding="utf-8") as f:
        cached = json.load(f)
    scan = cached.get("scan_info", {})
    stats = cached.get("stats", {})
    failed = scan.get("failed_file_paths", []) or []
    empty = scan.get("empty_file_paths", []) or []

    seen: set[str] = set()
    empty_u: list[str] = []
    for p in empty:
        n = os.path.normcase(p)
        if n not in seen:
            seen.add(n)
            empty_u.append(p)

    groups: dict[str, list[str]] = defaultdict(list)
    for p in failed:
        groups[f"failed:{tag_failed(p)}"].append(p)
    for p in empty_u:
        groups[f"empty:{tag_empty(p)}"].append(p)

    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    index_lines = [
        f"failed={len(failed)} empty_paths={len(empty_u)} "
        f"stats_empty={stats.get('empty_files')} "
        f"parsed={stats.get('parsed_files')}/{stats.get('total_files')}",
        "",
    ]
    for key in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        paths = groups[key]
        fname = key.replace(":", "-").replace("/", "-") + ".txt"
        (out_dir / fname).write_text("\n".join(paths) + "\n", encoding="utf-8")
        top_reg = Counter(region(p) for p in paths).most_common(3)
        reg_str = " / ".join(f"{r}:{c}" for r, c in top_reg)
        index_lines.append(f"{len(paths):4d}  {key}  |  {reg_str}  -> {fname}")

    (out_dir / "未解析-按原因路径索引.txt").write_text(
        "\n".join(index_lines) + "\n", encoding="utf-8"
    )
    print("\n".join(index_lines))


if __name__ == "__main__":
    main()
