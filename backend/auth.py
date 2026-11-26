"""Authentication for BlackSignal.

Cookie sessions for the browser (login screen) plus HTTP Basic as an
alternate mechanism for API clients (e.g. ``curl -u user:pass``).

Credentials are generated on first boot by ``docker-entrypoint.sh`` and stored
in ``data/.credentials`` (plaintext, for the operator). The backend derives a
PBKDF2 hash from them into ``data/.auth.json`` and keeps a signing secret in
``data/.auth_secret``. Neither is ever exposed to the browser.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger("blacksignal")

SESSION_COOKIE = "bs_session"
PBKDF2_ITERATIONS = 200_000

# Login brute-force throttling (in-memory, per client IP)
_MAX_FAILURES = 10
_FAILURE_WINDOW = 300  # seconds

_rate_lock = threading.Lock()
_failures: dict[str, list] = {}  # ip -> [count, first_ts]


# ── configuration ────────────────────────────────────────────────────────────

def session_days() -> int:
    try:
        return max(1, int(os.environ.get("AUTH_SESSION_DAYS", "7")))
    except ValueError:
        return 7


def cookie_secure() -> bool:
    return os.environ.get("AUTH_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")


def data_dir() -> str:
    """Resolve the directory holding credentials and auth state."""
    env = os.environ.get("AUTH_DIR")
    if env:
        return env
    env = os.environ.get("DATA_DIR")
    if env:
        return env
    db = os.environ.get("DB_PATH")
    if db and db not in (":memory:",):
        parent = os.path.dirname(os.path.abspath(db))
        if parent:
            return parent
    dev = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    dev = os.path.abspath(dev)
    if os.path.isdir(dev):
        return dev
    return "/app/data"


def _path(name: str) -> str:
    return os.path.join(data_dir(), name)


# ── file helpers ─────────────────────────────────────────────────────────────

def _write_secure(path: str, data: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_credentials_file() -> tuple[str, str] | None:
    """Parse ``data/.credentials`` (URL/Username/Password lines)."""
    try:
        with open(_path(".credentials"), encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None
    username = password = None
    for line in content.splitlines():
        if line.startswith("Username:"):
            username = line.split(":", 1)[1].strip()
        elif line.startswith("Password:"):
            password = line.split(":", 1)[1].strip()
    if username and password:
        return username, password
    return None


def _write_credentials_file(username: str, password: str) -> None:
    content = (
        "URL:     http://localhost\n"
        f"Username: {username}\n"
        f"Password: {password}\n"
    )
    _write_secure(_path(".credentials"), content)


def _derive(password: str, salt: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    ).hex()


def _load_auth() -> dict | None:
    try:
        with open(_path(".auth.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _secret_bytes() -> bytes:
    try:
        with open(_path(".auth_secret"), "rb") as f:
            return f.read().strip()
    except OSError:
        return b""


def ensure_auth_files() -> None:
    """Create auth state on first start (idempotent)."""
    d = data_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        logger.exception("Cannot create auth directory %s", d)
        return

    secret_path = _path(".auth_secret")
    if not os.path.exists(secret_path):
        _write_secure(secret_path, secrets.token_hex(32))
        logger.info("Generated auth signing secret")

    # Tighten permissions on an existing credentials file (older installs
    # may have created it world-readable).
    creds_path = _path(".credentials")
    if os.path.exists(creds_path):
        try:
            os.chmod(creds_path, 0o600)
        except OSError:
            pass

    auth_path = _path(".auth.json")
    if os.path.exists(auth_path):
        return
    creds = read_credentials_file()
    if creds:
        username, password = creds
    else:
        # Defensive fallback: generate credentials if the entrypoint did not.
        username = os.environ.get("AUTH_USER", "admin")
        password = secrets.token_urlsafe(12)
        _write_credentials_file(username, password)
        logger.warning("No credentials found; generated new ones for user %s", username)

    salt = secrets.token_hex(16)
    payload = {
        "username": username,
        "salt": salt,
        "hash": _derive(password, salt),
        "iterations": PBKDF2_ITERATIONS,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    _write_secure(auth_path, json.dumps(payload, indent=2))
    logger.info("Auth credentials hash stored (user %s)", username)


# ── credential / session verification ───────────────────────────────────────

def verify_credentials(username: str, password: str) -> str | None:
    """Return the username on success, else None."""
    cfg = _load_auth()
    if not cfg:
        return None
    if not hmac.compare_digest(str(cfg.get("username", "")), username or ""):
        return None
    try:
        digest = _derive(password or "", cfg["salt"], int(cfg.get("iterations", PBKDF2_ITERATIONS)))
    except (KeyError, ValueError):
        return None
    if hmac.compare_digest(digest, str(cfg.get("hash", ""))):
        return username
    return None


def create_session_token(username: str, days: int | None = None) -> str:
    """Create an HMAC-signed, expiring session token."""
    days = session_days() if days is None else days
    payload = {"u": username, "exp": int(time.time()) + days * 86400}
    b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    sig = hmac.new(_secret_bytes(), b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def verify_session_token(token: str | None) -> str | None:
    """Return the username for a valid, unexpired token, else None."""
    if not token or "." not in token:
        return None
    b64, sig = token.rsplit(".", 1)
    secret = _secret_bytes()
    if not secret:
        return None
    expected = hmac.new(secret, b64.encode("ascii", "ignore"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = b64 + "=" * (-len(b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload.get("u")
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def verify_basic(authorization: str | None) -> str | None:
    """Verify an ``Authorization: Basic ...`` header. Returns username or None."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(parts[1].strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    username, password = decoded.split(":", 1)
    return verify_credentials(username, password)


# ── login throttling ─────────────────────────────────────────────────────────

def is_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    with _rate_lock:
        entry = _failures.get(ip)
        if not entry:
            return False
        count, first = entry
        if now - first > _FAILURE_WINDOW:
            _failures.pop(ip, None)
            return False
        return count >= _MAX_FAILURES


def register_failure(ip: str) -> None:
    now = time.monotonic()
    with _rate_lock:
        entry = _failures.get(ip)
        if not entry or now - entry[1] > _FAILURE_WINDOW:
            _failures[ip] = [1, now]
        else:
            entry[0] += 1


def reset_failures(ip: str) -> None:
    with _rate_lock:
        _failures.pop(ip, None)


def reset_rate_limits() -> None:
    with _rate_lock:
        _failures.clear()
