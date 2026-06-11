"""构建制度文件 FTS 索引。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.zhidu_catalog import _parse_zhidu, zhidu


def _progress(count: int, *, done: bool = False, elapsed: float = 0) -> None:
    if done:
        print(f"完成: {count:,} 份文件 ({elapsed:.1f}s)", flush=True)
    else:
        print(f"  已索引 {count:,} …", flush=True)


def main() -> None:
    print(f"制度目录: {zhidu.root_dir}", flush=True)
    n = zhidu.build_index(parse_row=_parse_zhidu, progress=_progress)
    print(f"索引已写入 {zhidu.db_path}（{n:,} 条）", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
