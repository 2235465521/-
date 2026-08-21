"""
修复 stsc_standard_database 中 std_filepath 错挂 base_id。

策略：
1. 从 file_name 解析标准号（含年份）
2. 在 std_base 中按 std_id_norm / 紧凑键匹配正确标准
3. 若当前 base_id 对应标准号与文件名不一致 → 改挂到正确 base_id
4. 默认 dry-run；加 --apply 才写库（会先建备份表）

用法：
  python scripts/repair_filepath_base_id.py
  python scripts/repair_filepath_base_id.py --apply
  python scripts/repair_filepath_base_id.py --host 127.0.0.1 --user root --password 2048 --database stsc_standard_database
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pymysql

# 项目根
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.std_normalize import normalize_std_id, std_id_norm_key  # noqa: E402

# 从文件名提取标准号：支持 GBT / GB/T / GB_T / DB12/T / DB 1401T / HJ/T 等
_FILE_STD = re.compile(
    r"""
    ^\s*
    (?:[\(（][^)）]*[\)）])?          # 可选前缀如 (废止)
    \s*
    (
      [A-Za-z]{1,10}                 # 前缀字母
      (?:\s*[/_]?\s*[A-Za-z])?       # 可选 /T 或 _T
      (?:\s*\d{0,2})?                # 可选地区码 DB12 / DB1401
      (?:\s*[/_]?\s*[A-Za-z])?       # 再可选 T
      \s*
      \d+(?:\.\d+)*                  # 标准序号
      \s*[-－—/]?\s*
      (?:19|20)\d{2}                 # 年份
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def extract_std_from_filename(file_name: str) -> str | None:
    stem = Path(file_name or "").stem
    # 去掉 _F_ / _T_ 后的中文题名
    head = re.split(r"_[FTZX]_", stem, maxsplit=1, flags=re.IGNORECASE)[0]
    m = _FILE_STD.match(head)
    if not m:
        # 再试：允许无空格的 GBT19630-2019
        m = re.match(
            r"^\s*(?:[\(（][^)）]*[\)）])?\s*"
            r"([A-Za-z]{1,10}(?:[/_]?[A-Za-z])?(?:\d{0,2})?(?:[/_]?[A-Za-z])?"
            r"\d+(?:\.\d+)*[-－—]?(?:19|20)\d{2})",
            head,
            re.IGNORECASE,
        )
    if not m:
        return None
    raw = m.group(1)
    # 规范化可读形式：DB1401T9-2020 -> DB1401/T 9-2020（尽力）
    return canonicalize_std_id(raw)


def canonicalize_std_id(raw: str) -> str:
    s = raw.strip().upper().replace("／", "/").replace("_", "/")
    s = re.sub(r"\s+", "", s)
    # 统一破折号
    s = s.replace("—", "-").replace("－", "-").replace("/", "/")
    # 插入常见斜杠：GBT -> GB/T，HJT -> HJ/T，DB12T -> DB12/T，DB1401T -> DB1401/T
    s = re.sub(r"^([A-Z]{1,6})(T|Z|X)(\d)", r"\1/\2 \3", s)
    s = re.sub(r"^(DB\d{1,2})(T|Z|X)(\d)", r"\1/\2 \3", s)
    s = re.sub(r"^(DB\d{4})(T|Z|X)(\d)", r"\1/\2 \3", s)
    # YYYY 前补连字符
    s = re.sub(r"(\d)((?:19|20)\d{2})$", r"\1-\2", s)
    # 清理重复空格
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_base_indexes(cur):
    """返回 (by_compact, by_noyear, id_to_std)。"""
    cur.execute("SELECT id, std_id, std_id_norm FROM std_base")
    by_compact: dict[str, int] = {}
    by_noyear: dict[str, list[int]] = defaultdict(list)
    id_to_std: dict[int, str] = {}
    for row in cur.fetchall():
        bid = row["id"]
        sid = row["std_id"] or ""
        id_to_std[bid] = sid
        keys = {
            normalize_std_id(sid),
            std_id_norm_key(sid),
            normalize_std_id(row.get("std_id_norm") or sid),
        }
        for k in keys:
            if k and k not in by_compact:
                by_compact[k] = bid
        # 去年份键
        noyear = re.sub(r"(19|20)\d{2}$", "", normalize_std_id(sid))
        if noyear:
            by_noyear[noyear].append(bid)
    return by_compact, by_noyear, id_to_std


def resolve_base_id(
    parsed: str,
    by_compact: dict[str, int],
    by_noyear: dict[str, list[int]],
    id_to_std: dict[int, str],
) -> int | None:
    for k in (
        normalize_std_id(parsed),
        std_id_norm_key(parsed),
        normalize_std_id(canonicalize_std_id(parsed)),
    ):
        if k in by_compact:
            return by_compact[k]
    # 仅编号匹配且唯一时采用（慎用）
    noyear = re.sub(r"(19|20)\d{2}$", "", normalize_std_id(parsed))
    cands = by_noyear.get(noyear) or []
    if len(cands) == 1:
        return cands[0]
    # 多个候选时优先年份文件年份
    y = re.search(r"(19|20)\d{2}$", normalize_std_id(parsed))
    if y:
        year = y.group(0)
        hit = [b for b in cands if year in normalize_std_id(id_to_std.get(b, ""))]
        if len(hit) == 1:
            return hit[0]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="修复 std_filepath.base_id 错挂")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3306)
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="")
    ap.add_argument("--database", default="stsc_standard_database")
    ap.add_argument("--apply", action="store_true", help="实际写库；默认只演练")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 条（0=全部）")
    args = ap.parse_args()
    if not args.password:
        print("请通过 --password 提供数据库密码")
        raise SystemExit(2)

    conn = pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    cur = conn.cursor()
    print(f"连接 {args.user}@{args.host}/{args.database}  mode={'APPLY' if args.apply else 'DRY-RUN'}")

    print("加载 std_base 索引...")
    by_compact, by_noyear, id_to_std = build_base_indexes(cur)
    print(f"  标准 {len(id_to_std):,} 条, compact键 {len(by_compact):,}")

    cur.execute(
        "SELECT id, base_id, file_name, file_path FROM std_filepath"
        + (" LIMIT %d" % args.limit if args.limit else "")
    )

    stats = Counter()
    changes: list[tuple[int, int, int, str, str, str]] = []
    # (file_id, old_base, new_base, file_name, old_std, new_std)

    while True:
        rows = cur.fetchmany(5000)
        if not rows:
            break
        for r in rows:
            stats["scanned"] += 1
            fname = (r["file_name"] or "").strip()
            old_base = r["base_id"]
            old_std = id_to_std.get(old_base, "")
            parsed = extract_std_from_filename(fname)
            if not parsed:
                stats["unparseable"] += 1
                continue

            # 当前挂靠是否已正确（文件名含当前标准号）
            if old_std and normalize_std_id(old_std) in normalize_std_id(fname):
                # 年份也在文件名中
                stats["already_ok"] += 1
                continue

            new_base = resolve_base_id(parsed, by_compact, by_noyear, id_to_std)
            if not new_base:
                stats["no_match_in_base"] += 1
                continue
            if new_base == old_base:
                stats["already_ok"] += 1
                continue

            new_std = id_to_std.get(new_base, "")
            stats["need_fix"] += 1
            if len(changes) < 50000:
                changes.append((r["id"], old_base, new_base, fname, old_std, new_std))

    print("\n===== 统计 =====")
    for k in (
        "scanned",
        "already_ok",
        "need_fix",
        "unparseable",
        "no_match_in_base",
    ):
        print(f"  {k}: {stats[k]:,}")

    report = ROOT / "data" / "repair_filepath_base_id_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", encoding="utf-8") as f:
        f.write(f"mode={'APPLY' if args.apply else 'DRY-RUN'}\n")
        f.write(f"time={datetime.now().isoformat(timespec='seconds')}\n")
        for k, v in stats.items():
            f.write(f"{k}={v}\n")
        f.write("\n# file_id\told_base\tnew_base\told_std\tnew_std\tfile_name\n")
        for fid, ob, nb, fn, os_, ns in changes:
            f.write(f"{fid}\t{ob}\t{nb}\t{os_}\t{ns}\t{fn}\n")
    print(f"样例/变更清单: {report} （最多记录 50000 条变更）")

    print("\n变更样例（前 20）:")
    for fid, ob, nb, fn, os_, ns in changes[:20]:
        print(f"  file#{fid}: {os_!r} -> {ns!r}")
        print(f"    {fn}")

    if not args.apply:
        print("\n这是演练结果，未改库。确认无误后执行：")
        print(
            f"  python scripts/repair_filepath_base_id.py --apply "
            f"--password *** --database {args.database}"
        )
        conn.close()
        return

    if not changes and stats["need_fix"] == 0:
        print("无需修复")
        conn.close()
        return

    # 备份 + 批量更新（使用独立读/写游标，避免 fetch 被 INSERT 打断）
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"std_filepath_baseid_bak_{stamp}"
    map_table = f"_repair_ids_{stamp}"
    print(f"\n创建备份表 {bak} ...")
    cur.execute(
        f"CREATE TABLE `{bak}` AS "
        "SELECT id, base_id, file_name, file_path FROM std_filepath WHERE 1=0"
    )
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS `{map_table}` "
        "(file_id BIGINT PRIMARY KEY, new_base_id BIGINT NOT NULL)"
    )
    conn.commit()

    print("生成完整修复映射...")
    read_cur = conn.cursor()
    read_cur.execute(
        "SELECT id, base_id, file_name, file_path FROM std_filepath"
    )
    batch_bak: list[tuple] = []
    batch_map: list[tuple] = []
    fixed = 0
    while True:
        rows = read_cur.fetchmany(5000)
        if not rows:
            break
        for r in rows:
            fname = (r["file_name"] or "").strip()
            old_base = r["base_id"]
            old_std = id_to_std.get(old_base, "")
            if old_std and normalize_std_id(old_std) in normalize_std_id(fname):
                continue
            parsed = extract_std_from_filename(fname)
            if not parsed:
                continue
            new_base = resolve_base_id(parsed, by_compact, by_noyear, id_to_std)
            if not new_base or new_base == old_base:
                continue
            batch_bak.append((r["id"], old_base, fname, r.get("file_path") or ""))
            batch_map.append((r["id"], new_base))
            fixed += 1
            if len(batch_map) >= 2000:
                cur.executemany(
                    f"INSERT INTO `{bak}` (id, base_id, file_name, file_path) VALUES (%s,%s,%s,%s)",
                    batch_bak,
                )
                cur.executemany(
                    f"INSERT INTO `{map_table}` (file_id, new_base_id) VALUES (%s,%s)",
                    batch_map,
                )
                conn.commit()
                batch_bak.clear()
                batch_map.clear()
                if fixed % 20000 == 0:
                    print(f"  已收集 {fixed:,} ...")
    read_cur.close()
    if batch_map:
        cur.executemany(
            f"INSERT INTO `{bak}` (id, base_id, file_name, file_path) VALUES (%s,%s,%s,%s)",
            batch_bak,
        )
        cur.executemany(
            f"INSERT INTO `{map_table}` (file_id, new_base_id) VALUES (%s,%s)",
            batch_map,
        )
        conn.commit()

    print(f"将更新 {fixed:,} 行 base_id ...")
    cur.execute(
        f"""
        UPDATE std_filepath f
        INNER JOIN `{map_table}` m ON m.file_id = f.id
        SET f.base_id = m.new_base_id
        """
    )
    affected = cur.rowcount
    conn.commit()
    print(f"完成。实际更新 {affected:,} 行。备份表: {bak} ；映射表: {map_table}")
    print("如需回滚:")
    print(
        f"  UPDATE std_filepath f INNER JOIN `{bak}` b ON b.id=f.id SET f.base_id=b.base_id;"
    )
    conn.close()
if __name__ == "__main__":
    main()
