"""Filesystem path helpers shared by auth, settings and the report archive."""

import os


def data_dir() -> str:
    """Resolve the persistent data directory.

    Precedence: ``AUTH_DIR`` (tests) -> ``DATA_DIR`` -> directory of
    ``DB_PATH`` -> repository ``data/`` (dev) -> ``/app/data`` (container).
    """
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
    dev = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
    if os.path.isdir(dev):
        return dev
    return "/app/data"