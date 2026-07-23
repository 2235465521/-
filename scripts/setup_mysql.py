# -*- coding: utf-8 -*-
"""
一键准备 MySQL 标准库：
1. 若无 .env，从 .env.example 生成
2. 探测 mysql 客户端
3. 若目标库缺少 std_base，则从 data/db_dump/*.sql.gz 自动导入
"""
from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DUMP_DIR = ROOT / "data" / "db_dump"
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
DEFAULT_DB = "STSC_standard_database"

# 常见 Windows 安装路径
_MYSQL_CANDIDATES = [
    Path(r"C:\Program Files\MySQL\MySQL Server 9.7\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 9.6\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 9.5\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 9.4\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 9.3\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 9.2\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 9.1\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 9.0\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 8.3\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 8.2\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 8.1\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"),
    Path(r"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysql.exe"),
    Path(r"C:\xampp\mysql\bin\mysql.exe"),
    Path(r"C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysql.exe"),
]


def _log(msg: str) -> None:
    print(msg, flush=True)


def ensure_env_file() -> None:
    if ENV_PATH.is_file():
        return
    if ENV_EXAMPLE.is_file():
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        # 示例里的中文占位改为空密码，便于本机默认 root 无密码场景；有密码用户自行改
        text = text.replace("MYSQL_PASSWORD=你的密码", "MYSQL_PASSWORD=")
        ENV_PATH.write_text(text, encoding="utf-8")
        _log(f"[setup] 已从 .env.example 生成 {ENV_PATH.name}，请按需修改密码")
    else:
        ENV_PATH.write_text(
            "\n".join(
                [
                    "HOST=0.0.0.0",
                    "PORT=5000",
                    "OPEN_BROWSER=true",
                    "MYSQL_HOST=127.0.0.1",
                    "MYSQL_PORT=3306",
                    "MYSQL_USER=root",
                    "MYSQL_PASSWORD=",
                    f"MYSQL_DATABASE={DEFAULT_DB}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        _log(f"[setup] 已创建默认 {ENV_PATH.name}")


def find_mysql_exe() -> Path | None:
    env_exe = (os.getenv("MYSQL_EXE") or "").strip()
    if env_exe:
        p = Path(env_exe)
        if p.is_file():
            return p
    which = shutil.which("mysql")
    if which:
        return Path(which)
    for p in _MYSQL_CANDIDATES:
        if p.is_file():
            return p
    # 模糊扫描 Program Files\MySQL
    root = Path(r"C:\Program Files\MySQL")
    if root.is_dir():
        hits = sorted(root.glob("MySQL Server */bin/mysql.exe"), reverse=True)
        if hits:
            return hits[0]
    return None


def find_dump() -> Path | None:
    preferred = DUMP_DIR / "STSC_standard_database.sql.gz"
    if preferred.is_file():
        return preferred
    if not DUMP_DIR.is_dir():
        return None
    gz = sorted(DUMP_DIR.glob("*.sql.gz"))
    if gz:
        return gz[0]
    sql = sorted(DUMP_DIR.glob("*.sql"))
    return sql[0] if sql else None


def mysql_env(password: str) -> dict[str, str]:
    env = os.environ.copy()
    if password:
        env["MYSQL_PWD"] = password
    elif "MYSQL_PWD" in env:
        del env["MYSQL_PWD"]
    return env


def run_mysql(
    mysql: Path,
    *,
    host: str,
    port: str,
    user: str,
    password: str,
    args: list[str],
    stdin_bytes: bytes | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[bytes]:
    cmd = [
        str(mysql),
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        "--default-character-set=utf8mb4",
        *args,
    ]
    return subprocess.run(
        cmd,
        input=stdin_bytes,
        capture_output=True,
        env=mysql_env(password),
        timeout=timeout,
    )


def db_has_std_base(
    mysql: Path, *, host: str, port: str, user: str, password: str, database: str
) -> bool:
    sql = (
        "SELECT COUNT(*) FROM information_schema.tables "
        f"WHERE table_schema='{database}' AND table_name='std_base';"
    )
    proc = run_mysql(
        mysql,
        host=host,
        port=port,
        user=user,
        password=password,
        args=["-N", "-e", sql],
        timeout=15,
    )
    if proc.returncode != 0:
        return False
    out = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    return out.isdigit() and int(out) > 0


def count_std_base(
    mysql: Path, *, host: str, port: str, user: str, password: str, database: str
) -> int | None:
    proc = run_mysql(
        mysql,
        host=host,
        port=port,
        user=user,
        password=password,
        args=["-N", "-e", f"SELECT COUNT(*) FROM `{database}`.std_base;"],
        timeout=60,
    )
    if proc.returncode != 0:
        return None
    out = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    return int(out) if out.isdigit() else None


def ensure_database(
    mysql: Path, *, host: str, port: str, user: str, password: str, database: str
) -> bool:
    sql = (
        f"CREATE DATABASE IF NOT EXISTS `{database}` "
        "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )
    proc = run_mysql(
        mysql,
        host=host,
        port=port,
        user=user,
        password=password,
        args=["-e", sql],
        timeout=30,
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")
        _log(f"[setup] 创建数据库失败: {err[-500:]}")
        return False
    return True


def import_dump(
    mysql: Path,
    dump: Path,
    *,
    host: str,
    port: str,
    user: str,
    password: str,
    database: str,
) -> bool:
    _log(f"[setup] 正在导入 {dump.name} -> {database}（约数分钟，请勿关闭）…")
    if not ensure_database(
        mysql, host=host, port=port, user=user, password=password, database=database
    ):
        return False

    cmd = [
        str(mysql),
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        "--default-character-set=utf8mb4",
        "--binary-mode",
        "--force",
        database,
    ]
    try:
        if dump.suffix.lower() == ".gz":
            with gzip.open(dump, "rb") as gz:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=mysql_env(password),
                )
                assert proc.stdin is not None
                shutil.copyfileobj(gz, proc.stdin, length=1024 * 1024)
                proc.stdin.close()
                out, err = proc.communicate()
        else:
            with dump.open("rb") as f:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=mysql_env(password),
                )
                assert proc.stdin is not None
                shutil.copyfileobj(f, proc.stdin, length=1024 * 1024)
                proc.stdin.close()
                out, err = proc.communicate()
    except Exception as exc:
        _log(f"[setup] 导入异常: {exc}")
        return False

    if proc.returncode != 0:
        _log("[setup] 导入失败:")
        if err:
            sys.stderr.buffer.write(err[-4000:])
            sys.stderr.write("\n")
        return False

    n = count_std_base(
        mysql, host=host, port=port, user=user, password=password, database=database
    )
    if n is None or n < 1:
        _log("[setup] 导入后未检测到 std_base 数据")
        return False
    _log(f"[setup] 导入完成，std_base 约 {n:,} 条")
    return True


def update_env_database(database: str) -> None:
    if not ENV_PATH.is_file():
        return
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    found = False
    for line in lines:
        if line.startswith("MYSQL_DATABASE="):
            out.append(f"MYSQL_DATABASE={database}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"MYSQL_DATABASE={database}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def can_connect(
    mysql: Path, *, host: str, port: str, user: str, password: str
) -> tuple[bool, str]:
    proc = run_mysql(
        mysql,
        host=host,
        port=port,
        user=user,
        password=password,
        args=["-N", "-e", "SELECT 1;"],
        timeout=10,
    )
    if proc.returncode == 0:
        return True, ""
    err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
    return False, err[-400:]


def main() -> int:
    ensure_env_file()
    load_dotenv(ENV_PATH, override=True)

    host = os.getenv("MYSQL_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.getenv("MYSQL_PORT", "3306").strip() or "3306"
    user = os.getenv("MYSQL_USER", "root").strip() or "root"
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", DEFAULT_DB).strip() or DEFAULT_DB

    mysql = find_mysql_exe()
    if not mysql:
        _log("[setup] 未找到 mysql 客户端。请先安装 MySQL，或设置环境变量 MYSQL_EXE=mysql.exe 完整路径")
        _log("        也可使用 Docker：docker compose up -d mysql")
        return 2

    ok, err = can_connect(mysql, host=host, port=port, user=user, password=password)
    if not ok:
        _log(f"[setup] 无法连接 MySQL {user}@{host}:{port}")
        if err:
            _log(f"        {err}")
        _log("        请确认 MySQL 服务已启动，并检查 .env 中的账号密码")
        return 3

    _log(f"[setup] MySQL 已连接（{mysql}）")

    if db_has_std_base(
        mysql, host=host, port=port, user=user, password=password, database=database
    ):
        n = count_std_base(
            mysql, host=host, port=port, user=user, password=password, database=database
        )
        _log(f"[setup] 标准库已就绪：{database}（std_base≈{n or '?'}）")
        update_env_database(database)
        return 0

    dump = find_dump()
    if not dump:
        _log(f"[setup] 未找到库备份，请将 *.sql.gz 放到 {DUMP_DIR}")
        return 4

    if not import_dump(
        mysql,
        dump,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    ):
        return 5

    update_env_database(database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
