"""Quick batch test: how many previously-empty paths parse now."""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter

import scripts._bootstrap  # noqa: F401

from config import CACHE_FILE
from food_inspection.parser import parse_file


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with open(CACHE_FILE, encoding="utf-8") as f:
        cached = json.load(f)
    scan = cached.get("scan_info", {})
    paths = list(dict.fromkeys(scan.get("empty_file_paths", []) + scan.get("failed_file_paths", [])))
    print(f"testing {len(paths)} paths from cache...", flush=True)

    results: Counter[str] = Counter()
    recovered = 0
    t0 = time.time()
    for i, path in enumerate(paths, 1):
        if not os.path.isfile(path):
            results["missing"] += 1
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            results["skip_pdf_slow"] += 1
            continue
        try:
            n = len(parse_file(path))
            if n:
                recovered += 1
                results["ok"] += 1
            else:
                results["still_empty"] += 1
        except Exception as exc:
            results[f"error:{type(exc).__name__}"] += 1
        if i % 50 == 0:
            print(f"  {i}/{len(paths)} recovered={recovered}", flush=True)

    print(f"\ndone in {time.time()-t0:.1f}s")
    print(f"recovered (non-pdf): {recovered}")
    for k, v in results.most_common():
        print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()
