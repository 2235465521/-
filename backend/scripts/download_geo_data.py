#!/usr/bin/env python3
"""下载各省地图 GeoJSON 到 backend/geo_data（CDN 不可用时预先缓存）。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEO_DIR = ROOT / "geo_data"
CDN_BASE = "https://geo.datav.aliyun.com/areas_v3/bound"

ADCODES = [
    "100000",
    "110000",
    "120000",
    "130000",
    "140000",
    "150000",
    "210000",
    "220000",
    "230000",
    "310000",
    "320000",
    "330000",
    "340000",
    "350000",
    "360000",
    "370000",
    "410000",
    "420000",
    "430000",
    "440000",
    "450000",
    "460000",
    "500000",
    "510000",
    "520000",
    "530000",
    "540000",
    "610000",
    "620000",
    "630000",
    "640000",
    "650000",
]


def download_one(adcode: str) -> bool:
    target = GEO_DIR / f"{adcode}_full.json"
    if target.is_file() and target.stat().st_size > 1000:
        print(f"  跳过 {adcode}（已存在）")
        return True
    url = f"{CDN_BASE}/{adcode}_full.json"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"  失败 {adcode}: {exc}")
        return False
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    print(f"  已保存 {adcode} ({target.stat().st_size // 1024} KB)")
    return True


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    for adcode in ADCODES:
        if download_one(adcode):
            ok += 1
    print(f"\n完成：{ok}/{len(ADCODES)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
