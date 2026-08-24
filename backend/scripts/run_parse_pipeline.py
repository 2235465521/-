#!/usr/bin/env python3
"""
统一解析管道：校验已入库数据、纠正错误、导入未解析文件。

结合历史修复经验，在入库前统一执行：
- 分类脏值过滤（购进日期等）
- 单位名/地址换行空格修正
- 误标不合格 → 合格
- 核查处置正文误标合格剔除
- 无效单位名、产品名误填检测项目等

用法：
  # 全量：校验已入库 + 导入未解析（推荐）
  python scripts/run_parse_pipeline.py --all

  # 仅校验纠正已入库
  python scripts/run_parse_pipeline.py --repair-only

  # 仅导入新文件
  python scripts/run_parse_pipeline.py --import-only

  # 预览不写库
  python scripts/run_parse_pipeline.py --all --dry-run

  # 指定省份、并行数
  python scripts/run_parse_pipeline.py --all --province 广东省 --workers 6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from food_inspection.pipeline.runner import run_parse_pipeline  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="统一解析校验与纠错管道")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="校验已入库 + 导入未解析（默认）")
    mode.add_argument("--repair-only", action="store_true", help="仅校验/纠正已入库文件")
    mode.add_argument("--import-only", action="store_true", help="仅导入未解析文件")
    parser.add_argument("--dry-run", action="store_true", help="预览，不写数据库")
    parser.add_argument("--workers", type=int, default=4, help="并行解析进程数（默认 4）")
    parser.add_argument("--province", default=None, help="仅处理指定省份目录")
    parser.add_argument("--limit-files", type=int, default=None, help="限制处理文件数（调试用）")
    args = parser.parse_args()

    repair = args.repair_only or args.all or (not args.repair_only and not args.import_only)
    import_new = args.import_only or args.all or (not args.repair_only and not args.import_only)

    run_parse_pipeline(
        repair_imported=repair,
        import_new=import_new,
        dry_run=args.dry_run,
        workers=max(args.workers, 1),
        province=args.province,
        limit_files=args.limit_files,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
