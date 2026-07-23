"""应用用户鉴权：登录会话、角色权限、用户表（MySQL）。"""
from __future__ import annotations

import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any, Callable

import pymysql
from flask import jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from settings import (
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)

ROLE_USER = "user"
ROLE_ADMIN = "admin"
VALID_ROLES = frozenset({ROLE_USER, ROLE_ADMIN})

DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "Admin@123"
DEFAULT_USER_USER = "user"
DEFAULT_USER_PASS = "user123"


@dataclass
class AppUser:
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: str | None = None
    last_login_at: str | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
            "is_admin": self.role == ROLE_ADMIN,
        }


@contextmanager
def _conn():
    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_user(row: dict | None) -> AppUser | None:
    if not row:
        return None
    return AppUser(
        id=int(row["id"]),
        username=row["username"],
        display_name=(row.get("display_name") or row["username"]) or "",
        role=row.get("role") or ROLE_USER,
        is_active=bool(row.get("is_active", 1)),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        last_login_at=str(row["last_login_at"]) if row.get("last_login_at") else None,
    )


def ensure_auth_schema() -> None:
    """创建 app_user 表并写入默认管理员/普通用户（仅首次）。"""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_user (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
              username VARCHAR(64) NOT NULL,
              password_hash VARCHAR(255) NOT NULL,
              display_name VARCHAR(128) NOT NULL DEFAULT '',
              role VARCHAR(16) NOT NULL DEFAULT 'user',
              is_active TINYINT(1) NOT NULL DEFAULT 1,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
              last_login_at DATETIME NULL,
              UNIQUE KEY uk_app_user_username (username),
              KEY idx_app_user_role (role)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute("SELECT COUNT(*) AS c FROM app_user")
        count = int(cur.fetchone()["c"])
        if count == 0:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            seeds = [
                (
                    DEFAULT_ADMIN_USER,
                    generate_password_hash(DEFAULT_ADMIN_PASS),
                    "系统管理员",
                    ROLE_ADMIN,
                    now,
                ),
                (
                    DEFAULT_USER_USER,
                    generate_password_hash(DEFAULT_USER_PASS),
                    "普通用户",
                    ROLE_USER,
                    now,
                ),
            ]
            cur.executemany(
                """
                INSERT INTO app_user
                  (username, password_hash, display_name, role, is_active, created_at)
                VALUES (%s, %s, %s, %s, 1, %s)
                """,
                seeds,
            )


def get_user_by_username(username: str) -> dict | None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM app_user WHERE username = %s LIMIT 1",
            (username.strip(),),
        )
        return cur.fetchone()


def get_user_by_id(user_id: int) -> AppUser | None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM app_user WHERE id = %s LIMIT 1", (user_id,))
        return _row_to_user(cur.fetchone())


def authenticate(username: str, password: str) -> AppUser | None:
    row = get_user_by_username(username)
    if not row:
        return None
    if not bool(row.get("is_active", 1)):
        return None
    if not check_password_hash(row["password_hash"], password or ""):
        return None
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE app_user SET last_login_at = %s WHERE id = %s",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row["id"]),
        )
    return _row_to_user(row)


def login_user(user: AppUser) -> None:
    session.clear()
    session["user_id"] = user.id
    session["username"] = user.username
    session["role"] = user.role
    session.permanent = True


def logout_user() -> None:
    session.clear()


def current_user() -> AppUser | None:
    uid = session.get("user_id")
    if not uid:
        return None
    user = get_user_by_id(int(uid))
    if not user or not user.is_active:
        session.clear()
        return None
    return user


def list_users(*, q: str = "", page: int = 1, per_page: int = 20) -> dict:
    page = max(1, page)
    per_page = min(max(per_page, 1), 100)
    offset = (page - 1) * per_page
    where = "1=1"
    args: list[Any] = []
    qq = (q or "").strip()
    if qq:
        where += " AND (username LIKE %s OR display_name LIKE %s)"
        args.extend([f"%{qq}%", f"%{qq}%"])
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) AS c FROM app_user WHERE {where}", args)
        total = int(cur.fetchone()["c"])
        cur.execute(
            f"""
            SELECT id, username, display_name, role, is_active, created_at, last_login_at
            FROM app_user
            WHERE {where}
            ORDER BY id ASC
            LIMIT %s OFFSET %s
            """,
            (*args, per_page, offset),
        )
        rows = cur.fetchall() or []
    items = [_row_to_user(r).to_public() for r in rows if _row_to_user(r)]
    pages = (total + per_page - 1) // per_page if total else 0
    return {
        "ok": True,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": pages,
        "items": items,
    }


def create_user(
    *,
    username: str,
    password: str,
    display_name: str = "",
    role: str = ROLE_USER,
) -> tuple[AppUser | None, str | None]:
    uname = (username or "").strip()
    if len(uname) < 3 or len(uname) > 64:
        return None, "用户名长度需为 3–64"
    if not password or len(password) < 6:
        return None, "密码至少 6 位"
    role = (role or ROLE_USER).strip().lower()
    if role not in VALID_ROLES:
        return None, "角色无效"
    if get_user_by_username(uname):
        return None, "用户名已存在"
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO app_user (username, password_hash, display_name, role, is_active)
            VALUES (%s, %s, %s, %s, 1)
            """,
            (
                uname,
                generate_password_hash(password),
                (display_name or uname).strip()[:128],
                role,
            ),
        )
        uid = int(cur.lastrowid)
    return get_user_by_id(uid), None


def update_user(
    user_id: int,
    *,
    display_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
    actor_id: int | None = None,
) -> tuple[AppUser | None, str | None]:
    user = get_user_by_id(user_id)
    if not user:
        return None, "用户不存在"

    new_role = user.role
    if role is not None:
        role = role.strip().lower()
        if role not in VALID_ROLES:
            return None, "角色无效"
        new_role = role

    new_active = user.is_active if is_active is None else bool(is_active)

    # 禁止停用/降级最后一个管理员
    if user.role == ROLE_ADMIN and (new_role != ROLE_ADMIN or not new_active):
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) AS c FROM app_user WHERE role=%s AND is_active=1",
                (ROLE_ADMIN,),
            )
            admin_count = int(cur.fetchone()["c"])
        if admin_count <= 1:
            return None, "不能停用或降级唯一的管理员"

    if actor_id is not None and actor_id == user_id and not new_active:
        return None, "不能停用当前登录账号"

    fields: list[str] = []
    args: list[Any] = []
    if display_name is not None:
        fields.append("display_name = %s")
        args.append(display_name.strip()[:128] or user.username)
    if role is not None:
        fields.append("role = %s")
        args.append(new_role)
    if is_active is not None:
        fields.append("is_active = %s")
        args.append(1 if new_active else 0)
    if password is not None and password != "":
        if len(password) < 6:
            return None, "密码至少 6 位"
        fields.append("password_hash = %s")
        args.append(generate_password_hash(password))
    if not fields:
        return user, None
    args.append(user_id)
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE app_user SET {', '.join(fields)} WHERE id = %s",
            args,
        )
    return get_user_by_id(user_id), None


def require_login(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"ok": False, "error": "请先登录", "code": "auth_required"}), 401
        return view(*args, **kwargs)

    return wrapped


def require_admin(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"ok": False, "error": "请先登录", "code": "auth_required"}), 401
        if user.role != ROLE_ADMIN:
            return jsonify({"ok": False, "error": "需要管理员权限", "code": "forbidden"}), 403
        return view(*args, **kwargs)

    return wrapped


def generate_secret_key() -> str:
    return secrets.token_hex(32)
