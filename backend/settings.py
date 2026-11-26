"""Persistent application settings (``data/settings.json``).

Single store for runtime configuration, including the OpenRouter API key:

    {
      "reindex_interval": 86400,
      "openrouter_key": "sk-or-v1-..."
    }

Writes are atomic (temp file + ``os.replace``) and the file is ``0600`` because
it may contain a secret. A lock serialises read-modify-write updates so
concurrent changes (e.g. interval + key) can't clobber each other.
"""

import json
import logging
import os
import threading

from paths import data_dir

logger = logging.getLogger("blacksignal")

MIN_INTERVAL = 3600

_lock = threading.Lock()


def _path() -> str:
    return os.path.join(data_dir(), "settings.json")


def load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _update(mutator) -> None:
    """Serialise a read-modify-write cycle on the settings file."""
    with _lock:
        data = load()
        mutator(data)
        _save(data)


# ── auto-index interval ──────────────────────────────────────────────────────

def get_interval(default: int) -> int:
    """Return the persisted auto-index interval, or ``default``."""
    value = load().get("reindex_interval")
    if isinstance(value, int) and value >= MIN_INTERVAL:
        return value
    return default


def set_interval(seconds: int) -> None:
    if not isinstance(seconds, int) or seconds < MIN_INTERVAL:
        raise ValueError(f"Interval must be at least {MIN_INTERVAL} seconds")

    def _apply(data: dict) -> None:
        data["reindex_interval"] = seconds

    _update(_apply)


# ── OpenRouter API key ───────────────────────────────────────────────────────

def get_openrouter_key() -> str:
    return str(load().get("openrouter_key") or "").strip()


def set_openrouter_key(key: str) -> None:
    value = (key or "").strip()

    def _apply(data: dict) -> None:
        data["openrouter_key"] = value

    _update(_apply)


def clear_openrouter_key() -> None:
    set_openrouter_key("")


def get_key_preview() -> str:
    key = get_openrouter_key()
    if not key or len(key) < 8:
        return ""
    return f"{key[:8]}...{key[-4:]}"


# ── migration ────────────────────────────────────────────────────────────────

def migrate_legacy_openrouter() -> None:
    """Import a legacy ``data/openrouter.json`` into settings, once.

    Older versions stored the key in its own file. Import it (if settings has
    no key yet) and rename the old file so it isn't read again.
    """
    try:
        if get_openrouter_key():
            return
        candidates = []
        env = os.environ.get("OPENROUTER_CONFIG_PATH")
        if env:
            candidates.append(env)
        candidates.append(os.path.join(data_dir(), "openrouter.json"))
        for legacy in candidates:
            if not os.path.isfile(legacy):
                continue
            try:
                with open(legacy, encoding="utf-8") as f:
                    cfg = json.load(f)
                key = str(cfg.get("openrouter_key") or "").strip() if isinstance(cfg, dict) else ""
            except (OSError, json.JSONDecodeError):
                logger.warning("Ignoring unreadable legacy config %s", legacy)
                continue
            if not key:
                continue
            set_openrouter_key(key)
            try:
                os.replace(legacy, f"{legacy}.migrated")
            except OSError:
                pass
            logger.info("Migrated OpenRouter key from %s into settings.json", legacy)
            return
    except Exception:
        logger.exception("Legacy OpenRouter migration failed (non-fatal)")
