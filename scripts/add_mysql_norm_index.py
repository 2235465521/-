"""MySQL 数据库升级脚本：为 std_base 添加 std_id_norm 列并创建索引，极大提升检索速度。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pymysql
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "mydate")


def migrate() -> None:
    print(f"正在连接 MySQL 数据库 {MYSQL_DATABASE} @ {MYSQL_HOST}:{MYSQL_PORT}...")
    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
    )
    cur = conn.cursor()

    # 1. 检查 std_id_norm 列是否已存在
    cur.execute("SHOW COLUMNS FROM std_base LIKE 'std_id_norm'")
    has_column = cur.fetchone() is not None

    if not has_column:
        print("1. 正在添加 std_id_norm 列...")
        t0 = time.time()
        cur.execute(
            "ALTER TABLE std_base ADD COLUMN std_id_norm VARCHAR(50) NOT NULL DEFAULT ''"
        )
        conn.commit()
        print(f"   std_id_norm 列添加成功！耗时: {time.time() - t0:.2f}秒")
    else:
        print("1. [跳过] std_id_norm 列已存在。")

    # 2. 填充 std_id_norm 列的值
    print("2. 正在计算并更新 std_id_norm 列数据（可能需要十几秒，请耐心等待）...")
    t0 = time.time()
    # 为保证可靠性，我们在数据库内批量执行更新
    update_sql = """
    UPDATE std_base 
    SET std_id_norm = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(UPPER(std_id), ' ', ''), '/', ''), '-', ''), '—', ''), '－', '')
    WHERE std_id_norm = ''
    """
    affected_rows = cur.execute(update_sql)
    conn.commit()
    print(f"   数据更新成功！影响行数: {affected_rows:,}，耗时: {time.time() - t0:.2f}秒")

    # 3. 检查 idx_std_id_norm 索引是否已存在
    cur.execute(
        "SHOW INDEX FROM std_base WHERE Key_name = 'idx_std_id_norm'"
    )
    has_index = cur.fetchone() is not None

    if not has_index:
        print("3. 正在创建 idx_std_id_norm 索引...")
        t0 = time.time()
        cur.execute("CREATE INDEX idx_std_id_norm ON std_base(std_id_norm)")
        conn.commit()
        print(f"   idx_std_id_norm 索引创建成功！耗时: {time.time() - t0:.2f}秒")
    else:
        print("3. [跳过] idx_std_id_norm 索引已存在。")

    cur.close()
    conn.close()
    print("\n升级完成！MySQL 数据库已准备就绪。")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as exc:
        print(f"\n[错误] 升级失败：{exc}", file=sys.stderr)
        sys.exit(1)
