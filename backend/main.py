import os
import logging
import threading
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from database import init_db, build_filter_conditions, search_pastes, get_paste_by_id, get_sources, \
    get_content_types, get_secret_types, get_stats, get_stats_filtered, clear_all_data
from scheduler import index_all_pastes, start_scheduler, get_index_progress, get_last_reindex_result, set_index_running

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("blacksignal")

STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")
REINDEX_INTERVAL = int(os.environ.get("REINDEX_INTERVAL", "300"))

try:
    # Check multiple locations: repo root (dev) and /app (Docker)
    for p in (os.path.join(os.path.dirname(__file__), "..", "VERSION"),
              os.path.join(os.path.dirname(__file__), "VERSION"),
              "/app/VERSION"):
        if os.path.exists(p):
            with open(p) as f:
                APP_VERSION = f.read().strip()
            break
    else:
        APP_VERSION = "0.0.0"
except Exception:
    APP_VERSION = "0.0.0"


def _parse_bool(v: str | None) -> bool | None:
    """FastAPI's ``bool`` type treats ``'false'`` as ``True`` (non-empty string).
    This helper parses query params correctly."""
    if v is None:
        return None
    return v.lower() in ('1', 'true', 'yes')


def normalize_fts_query(q: str) -> str | None:
    """Strip whitespace; wrap in FTS5 phrase quotes unless the query already
    uses FTS5 operators (*, ", (, )). Returns None for empty input."""
    query = q.strip()
    if not query:
        return None
    if not any(c in query for c in ('*', '"', '(', ')')):
        query = f'"{query}"'
    return query


# --- Cached data accessors -------------------------------------------------
# Data only changes when the indexer runs (which calls clear_cache), so
# lru_cache bounded by the number of distinct filter combinations is safe.

@lru_cache(maxsize=256)
def _get_stats_cached(query, source, content_type, has_secrets, secret_types):
    conditions, params = build_filter_conditions(
        query=query,
        source=source,
        content_type=content_type,
        has_secrets=has_secrets,
        secret_types=secret_types,
    )
    if conditions:
        return get_stats_filtered(conditions, params)
    return get_stats()


@lru_cache(maxsize=1)
def _get_sources_cached():
    return get_sources()


@lru_cache(maxsize=1)
def _get_types_cached():
    return get_content_types()


@lru_cache(maxsize=1)
def _get_secret_types_cached():
    return get_secret_types()


def clear_cache():
    """Invalidate all cached API responses (called after re-indexing)."""
    for fn in (_get_stats_cached, _get_sources_cached, _get_types_cached, _get_secret_types_cached):
        fn.cache_clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Pre-compute unfiltered stats so the first user never hits the cold path
    _get_stats_cached(None, None, None, None, ())

    threading.Thread(target=index_all_pastes, daemon=True).start()
    start_scheduler(REINDEX_INTERVAL)
    yield


app = FastAPI(title="BlackSignal", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/stats")
def api_stats(
    q: str = Query("", description="Search query"),
    source: str = Query(None, description="Source filter"),
    content_type: str = Query(None, description="Content type filter"),
    has_secrets: str = Query(None, description="Only pastes with secrets ('true' or 'false')"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
):
    return _get_stats_cached(
        normalize_fts_query(q),
        source,
        content_type,
        _parse_bool(has_secrets),
        tuple(secret_type),
    )


@app.get("/api/sources")
def api_sources():
    return _get_sources_cached()


@app.get("/api/types")
def api_types():
    return _get_types_cached()


@app.get("/api/secret-types")
def api_secret_types():
    return _get_secret_types_cached()


@app.get("/api/pastes")
def api_search(
    q: str = Query("", description="Search query"),
    source: str = Query(None, description="Source filter"),
    content_type: str = Query(None, description="Content type filter"),
    has_secrets: str = Query(None, description="Only pastes with secrets ('true' or 'false')"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    return search_pastes(
        query=normalize_fts_query(q),
        source=source,
        content_type=content_type,
        has_secrets=_parse_bool(has_secrets),
        secret_types=secret_type if secret_type else None,
        page=page,
        per_page=per_page,
    )


@app.get("/api/pastes/{paste_id}")
def api_paste_detail(paste_id: str):
    paste = get_paste_by_id(paste_id)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found")
    return paste


@app.get("/api/version")
def api_version():
    return {"version": APP_VERSION}


@app.get("/api/index-status")
async def api_index_status():
    return get_index_progress()


@app.get("/api/last-reindex")
def api_last_reindex():
    return get_last_reindex_result()


@app.post("/api/reindex")
def api_reindex(mode: str = Query("standard", description="'standard', 'comprehensive', or 'purge'")):
    clear_cache()
    if mode == "purge":
        def _purge():
            set_index_running(True, phase="purging database")
            clear_all_data()
            index_all_pastes(scan_limit=None)
        threading.Thread(target=_purge, daemon=True).start()
    else:
        scan_limit = 0 if mode == "comprehensive" else None
        threading.Thread(target=index_all_pastes, daemon=True, kwargs={"scan_limit": scan_limit}).start()
    return {"status": "started", "mode": mode}


# --- SPA static serving -----------------------------------------------------

if STATIC_DIR and os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        filepath = os.path.join(STATIC_DIR, full_path)
        if os.path.exists(filepath) and os.path.isfile(filepath):
            return FileResponse(filepath)
        spa_html = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(spa_html):
            return FileResponse(spa_html)
        raise HTTPException(status_code=404)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info")