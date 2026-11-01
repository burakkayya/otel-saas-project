"""Parola özetleme, CSRF ve basit giriş denemesi sınırlaması."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from app.config import settings

_ALGO = "pbkdf2_sha256"


def hash_password(password: str, iterations: int | None = None) -> str:
    iterations = iterations or settings.password_iterations
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGO}${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 8:
        problems.append("Parola en az 8 karakter olmalı.")
    if not any(c.isdigit() for c in password):
        problems.append("Parola en az bir rakam içermeli.")
    if not any(c.isalpha() for c in password):
        problems.append("Parola en az bir harf içermeli.")
    return problems


# ----------------------------------------------------------------------------- CSRF
def get_csrf_token(session: dict) -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_valid(session: dict, submitted: str | None) -> bool:
    expected = session.get("csrf_token")
    return bool(expected and submitted and hmac.compare_digest(expected, submitted))


# ------------------------------------------------------------- Giriş denemesi limiti
class LoginRateLimiter:
    """Aynı IP + e-posta için pencere içinde en fazla N başarısız deneme."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        q = self._fails[key]
        now = time.monotonic()
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def is_blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.max_attempts

    def register_failure(self, key: str) -> None:
        self._prune(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


login_limiter = LoginRateLimiter()
