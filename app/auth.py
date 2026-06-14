from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import shutil
from typing import Any

from fastapi import Cookie, Depends, Header, HTTPException, Response, status

from .config import BASE_DIR, load_config
from .database import dict_from_row, get_db, now_ts


SESSION_COOKIE = "ai_chat_session"
SESSION_SECONDS = 60 * 60 * 24 * 30
GUEST_SECONDS = 60 * 60 * 24 * 3
SESSION_REFRESH_SECONDS = 60 * 60 * 24 * 7
PASSWORD_ITERATIONS = 240_000
UPLOAD_ROOT = BASE_DIR / "data" / "uploads"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    guest_expires_at = int(user.get("guest_expires_at") or 0)
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user.get("role", "user"),
        "status": user["status"],
        "is_guest": bool(user.get("is_guest")),
        "guest_expires_at": guest_expires_at,
        "guest_remaining_seconds": max(0, guest_expires_at - now_ts()) if guest_expires_at else 0,
        "created_at": user["created_at"],
    }


def create_user(username: str, password: str, nickname: str | None = None) -> dict[str, Any]:
    username = username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="username must be at least 3 characters")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")

    ts = now_ts()
    try:
        with get_db() as db:
            user_count = int(db.execute("SELECT COUNT(*) FROM users WHERE is_guest = 0").fetchone()[0])
            role = "admin" if user_count == 0 else "user"
            cursor = db.execute(
                """
                INSERT INTO users (username, password_hash, role, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, hash_password(password), role, ts, ts),
            )
            user_id = int(cursor.lastrowid)
            db.execute(
                """
                INSERT INTO user_profiles (user_id, nickname, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, nickname or username, ts, ts),
            )
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict_from_row(user) or {}
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="username already exists") from exc


def get_or_create_local_user(username: str, nickname: str | None = None) -> dict[str, Any]:
    username = (username or "").strip() or "mio_owner"
    if len(username) < 3:
        username = "mio_owner"
    display_name = (nickname or "").strip() or username
    ts = now_ts()

    try:
        with get_db() as db:
            existing = dict_from_row(db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())
            if existing:
                db.execute(
                    """
                    UPDATE users
                    SET role = 'admin', status = 'active', is_guest = 0, guest_expires_at = 0, updated_at = ?
                    WHERE id = ?
                    """,
                    (ts, existing["id"]),
                )
                profile = db.execute("SELECT user_id FROM user_profiles WHERE user_id = ?", (existing["id"],)).fetchone()
                if profile:
                    db.execute(
                        "UPDATE user_profiles SET nickname = ?, updated_at = ? WHERE user_id = ?",
                        (display_name, ts, existing["id"]),
                    )
                else:
                    db.execute(
                        "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (existing["id"], display_name, ts, ts),
                    )
                user = db.execute("SELECT * FROM users WHERE id = ?", (existing["id"],)).fetchone()
                return dict_from_row(user) or {}

            cursor = db.execute(
                """
                INSERT INTO users (username, password_hash, role, status, is_guest, guest_expires_at, created_at, updated_at)
                VALUES (?, ?, 'admin', 'active', 0, 0, ?, ?)
                """,
                (username, hash_password(secrets.token_urlsafe(32)), ts, ts),
            )
            user_id = int(cursor.lastrowid)
            db.execute(
                """
                INSERT INTO user_profiles (user_id, nickname, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, display_name, ts, ts),
            )
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict_from_row(user) or {}
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="local user already exists") from exc


def create_guest_user() -> dict[str, Any]:
    ts = now_ts()
    expires_at = ts + GUEST_SECONDS
    for _ in range(5):
        username = f"guest_{secrets.token_hex(5)}"
        password = secrets.token_urlsafe(24)
        try:
            with get_db() as db:
                cursor = db.execute(
                    """
                    INSERT INTO users (
                        username, password_hash, role, status,
                        is_guest, guest_expires_at, created_at, updated_at
                    )
                    VALUES (?, ?, 'user', 'active', 1, ?, ?, ?)
                    """,
                    (username, hash_password(password), expires_at, ts, ts),
                )
                user_id = int(cursor.lastrowid)
                db.execute(
                    """
                    INSERT INTO user_profiles (user_id, nickname, signature, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, "游客", "游客模式，三天后自动清除数据", ts, ts),
                )
                user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                return dict_from_row(user) or {}
        except sqlite3.IntegrityError:
            continue
    raise HTTPException(status_code=500, detail="guest account creation failed")


def cleanup_expired_guest_users(ts: int | None = None) -> int:
    ts = ts or now_ts()
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, username, guest_expires_at
            FROM users
            WHERE is_guest = 1
              AND guest_expires_at > 0
              AND guest_expires_at <= ?
            """,
            (ts,),
        ).fetchall()
        user_ids = [int(row["id"]) for row in rows]
        if user_ids:
            for row in rows:
                db.execute(
                    """
                    INSERT INTO guest_cleanup_logs (user_id, username, guest_expires_at, deleted_at, reason)
                    VALUES (?, ?, ?, ?, 'expired')
                    """,
                    (int(row["id"]), str(row["username"]), int(row["guest_expires_at"] or 0), ts),
                )
            placeholders = ",".join("?" for _ in user_ids)
            db.execute(f"DELETE FROM users WHERE id IN ({placeholders})", user_ids)

    for user_id in user_ids:
        shutil.rmtree(UPLOAD_ROOT / str(user_id), ignore_errors=True)
    return len(user_ids)


def convert_guest_user(
    *,
    user_id: int,
    username: str,
    password: str,
    nickname: str | None = None,
) -> dict[str, Any]:
    username = username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="username must be at least 3 characters")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")

    ts = now_ts()
    try:
        with get_db() as db:
            current = dict_from_row(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
            if not current or not current.get("is_guest"):
                raise HTTPException(status_code=400, detail="current account is not a guest")

            formal_count = int(
                db.execute(
                    "SELECT COUNT(*) FROM users WHERE is_guest = 0 AND id <> ?",
                    (user_id,),
                ).fetchone()[0]
            )
            role = "admin" if formal_count == 0 else "user"
            db.execute(
                """
                UPDATE users
                SET username = ?, password_hash = ?, role = ?,
                    is_guest = 0, guest_expires_at = 0, updated_at = ?
                WHERE id = ? AND is_guest = 1
                """,
                (username, hash_password(password), role, ts, user_id),
            )
            if nickname is not None and nickname.strip():
                db.execute(
                    """
                    UPDATE user_profiles
                    SET nickname = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (nickname.strip(), ts, user_id),
                )
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict_from_row(user) or {}
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="username already exists") from exc


def delete_user_account(*, user_id: int, confirm_username: str, password: str | None = None) -> dict[str, Any]:
    with get_db() as db:
        user = dict_from_row(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        if str(confirm_username or "").strip() != str(user.get("username") or "").strip():
            raise HTTPException(status_code=400, detail="请输入完整账号名以确认删除")
        if not user.get("is_guest"):
            if not password or not verify_password(password, str(user.get("password_hash") or "")):
                raise HTTPException(status_code=401, detail="password confirmation failed")
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))

    shutil.rmtree(UPLOAD_ROOT / str(user_id), ignore_errors=True)
    return {"ok": True, "user_id": user_id, "status": "deleted"}


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    cleanup_expired_guest_users()
    with get_db() as db:
        user = dict_from_row(db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())
    if not user or user.get("status") != "active":
        return None
    if not verify_password(password, str(user["password_hash"])):
        return None
    return user


def create_session(user_id: int, max_age: int = SESSION_SECONDS) -> str:
    token = secrets.token_urlsafe(32)
    ts = now_ts()
    with get_db() as db:
        db.execute(
            """
            INSERT INTO sessions (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, ts, ts + max_age),
        )
    return token


def set_session_cookie(response: Response, token: str, max_age: int = SESSION_SECONDS) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure_session_cookies(),
    )


def clear_session(response: Response, token: str | None = None) -> None:
    if token:
        with get_db() as db:
            db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax", secure=secure_session_cookies())


def secure_session_cookies() -> bool:
    security = load_config().get("security", {})
    if not isinstance(security, dict):
        return False
    return bool(security.get("secure_cookies", False))


def _token_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def request_session_token(session_token: str | None, authorization: str | None) -> str | None:
    return _token_from_header(authorization) or session_token


def current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = request_session_token(session_token, authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    ts = now_ts()
    cleanup_expired_guest_users(ts)
    with get_db() as db:
        row = db.execute(
            """
            SELECT users.*, sessions.expires_at AS session_expires_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ? AND users.status = 'active'
              AND (
                  users.is_guest = 0
                  OR users.guest_expires_at = 0
                  OR users.guest_expires_at > ?
              )
            """,
            (token, ts, ts),
        ).fetchone()

    user = dict_from_row(row)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    if user.get("is_guest"):
        return user
    if int(user.get("session_expires_at") or 0) < ts + SESSION_REFRESH_SECONDS:
        with get_db() as db:
            db.execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (ts + SESSION_SECONDS, token))
    return user


def optional_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | None:
    try:
        return current_user(session_token=session_token, authorization=authorization)
    except HTTPException:
        return None


def current_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return user
