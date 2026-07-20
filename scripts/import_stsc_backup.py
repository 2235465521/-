# -*- coding: utf-8 -*-
"""Import gzipped MySQL dump and point app .env at that database."""
from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DUMP = Path(r"d:\ZKBZ\202607\std_download_database\STSC_standard_database_backup_2026-07-19_000001.sql.gz")
TARGET_DB = "STSC_standard_database"
MYSQL_EXE = Path(r"C:\Program Files\MySQL\MySQL Server 9.7\bin\mysql.exe")


def main() -> int:
    load_dotenv(ROOT / ".env")
    if not DUMP.is_file():
        print(f"dump not found: {DUMP}", file=sys.stderr)
        return 1
    if not MYSQL_EXE.is_file():
        print(f"mysql not found: {MYSQL_EXE}", file=sys.stderr)
        return 1

    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD") or ""

    env = os.environ.copy()
    if password:
        env["MYSQL_PWD"] = password

    print(f"importing {DUMP.name} -> {TARGET_DB} @ {host}:{port} ...", flush=True)
    cmd = [
        str(MYSQL_EXE),
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        "--default-character-set=utf8mb4",
        "--binary-mode",
        "--force",
    ]
    with gzip.open(DUMP, "rb") as gz:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert proc.stdin is not None
        shutil.copyfileobj(gz, proc.stdin, length=1024 * 1024)
        proc.stdin.close()
        out, err = proc.communicate()
    if out:
        sys.stdout.buffer.write(out[-2000:])
    if err:
        sys.stderr.buffer.write(err[-4000:])
    if proc.returncode != 0:
        print(f"\nmysql exit {proc.returncode}", file=sys.stderr)
        return proc.returncode

    # Point .env at the restored database name
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.startswith("MYSQL_DATABASE="):
            new_lines.append(f"MYSQL_DATABASE={TARGET_DB}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"MYSQL_DATABASE={TARGET_DB}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"updated .env MYSQL_DATABASE={TARGET_DB}", flush=True)

    # Verify
    verify = subprocess.run(
        [
            str(MYSQL_EXE),
            f"--host={host}",
            f"--port={port}",
            f"--user={user}",
            "-N",
            "-e",
            f"SELECT COUNT(*) FROM `{TARGET_DB}`.std_base;",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    if verify.returncode == 0:
        print(f"std_base rows: {verify.stdout.strip()}", flush=True)
    else:
        print("verify warning:", verify.stderr[-500:], file=sys.stderr)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
