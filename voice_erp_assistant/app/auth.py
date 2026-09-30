"""Optional, environment-configured authentication for the demo server."""

import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException

from app import database

_PBKDF2_ROUNDS = 310_000
_SESSION_TTL = 8 * 60 * 60
_SESSIONS: dict[str, tuple[str | None, str, float]] = {}


def auth_enabled() -> bool:
    return os.environ.get("ERP_AUTH_ENABLED", "").lower() in {"1", "true", "yes"}


def demo_enabled() -> bool:
    configured = os.environ.get("ERP_DEMO_ENABLED", "true").lower() in {"1", "true", "yes"}
    return configured and not auth_enabled()


def password_record(password: str) -> str:
    """Build a salt$hash record for ERP_AUTH_USERS configuration."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ROUNDS
    ).hex()
    return f"{salt}${digest}"


def _configured_users() -> dict[str, str]:
    try:
        users = json.loads(os.environ.get("ERP_AUTH_USERS", "{}"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="ERP_AUTH_USERS must be valid JSON") from exc
    if not isinstance(users, dict):
        raise HTTPException(status_code=500, detail="ERP_AUTH_USERS must be a JSON object")
    return {str(employee_id).upper(): str(record) for employee_id, record in users.items()}


def login(employee_id: str, password: str) -> tuple[str, dict]:
    if not auth_enabled():
        raise HTTPException(status_code=404, detail="Authentication is not enabled")
    record = _configured_users().get(employee_id.strip().upper())
    employee = database.get_employee(employee_id.strip())
    if not record or not employee or "$" not in record:
        raise HTTPException(status_code=401, detail="Invalid employee ID or password")
    salt, expected = record.split("$", 1)
    try:
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ROUNDS
        ).hex()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid password hash configuration") from exc
    if not hmac.compare_digest(actual, expected):
        raise HTTPException(status_code=401, detail="Invalid employee ID or password")

    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = (employee["employee_id"], employee["role"], time.time() + _SESSION_TTL)
    return token, employee


def create_demo_session() -> str:
    if not demo_enabled():
        raise HTTPException(status_code=404, detail="Demo access is disabled")
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = (None, "demo", time.time() + _SESSION_TTL)
    return token


def resolve_user(
    authorization: str | None,
    legacy_employee_id: str | None = None,
    session_cookie: str | None = None,
) -> dict:
    scheme, _, token = (authorization or "").partition(" ")
    token = token if scheme.lower() == "bearer" else session_cookie
    session = _SESSIONS.get(token) if token else None
    if not session or session[2] <= time.time():
        _SESSIONS.pop(token, None)
        raise HTTPException(status_code=401, detail="Sign in to access ERP data")

    employee_id, role, _ = session
    if role == "demo":
        if not demo_enabled():
            _SESSIONS.pop(token, None)
            raise HTTPException(status_code=401, detail="Demo access is disabled")
        employee = database.get_employee(legacy_employee_id) if legacy_employee_id else None
        return {
            "employee_id": employee["employee_id"] if employee else legacy_employee_id,
            "name": employee["name"] if employee else "Demo workspace",
            "role": "demo",
        }
    if not auth_enabled():
        _SESSIONS.pop(token, None)
        raise HTTPException(status_code=401, detail="Employee sign-in is disabled")

    employee = database.get_employee(employee_id)
    if not employee:
        _SESSIONS.pop(token, None)
        raise HTTPException(status_code=401, detail="Employee account is unavailable")
    return employee


def revoke(authorization: str | None, session_cookie: str | None = None) -> None:
    scheme, _, token = (authorization or "").partition(" ")
    token = token if scheme.lower() == "bearer" else session_cookie
    if token:
        _SESSIONS.pop(token, None)