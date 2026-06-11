"""构建团标征求意见稿 FTS 索引。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.tuangbiao_catalog import _parse_tuangbiao, tuangbiao


def _progress(count: int, *, done: bool = False, elapsed: float = 0) -> None:
    if done:
        print(f"完成: {count:,} 份 PDF ({elapsed:.1f}s)", flush=True)
    else:
        print(f"  已索引 {count:,} …", flush=True)


def main() -> None:
    print(f"团标目录: {tuangbiao.root_dir}", flush=True)
    n = tuangbiao.build_index(parse_row=_parse_tuangbiao, progress=_progress)
    print(f"索引已写入 {tuangbiao.db_path}（{n:,} 条）", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
