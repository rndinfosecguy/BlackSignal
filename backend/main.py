import os
import time
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from database import init_db, build_filter_conditions, search_pastes, get_paste_by_id, get_sources, \
    get_content_types, get_secret_types, get_stats, get_stats_filtered, backfill_snippets
from scheduler import index_all_pastes, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("blacksignal")

STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")
REINDEX_INTERVAL = int(os.environ.get("REINDEX_INTERVAL", "300"))

_cache = {}
_CACHE_TTL = 60


def cached(key):
    now = time.time()
    entry = _cache.get(key)
    if entry and now - entry[0] < _CACHE_TTL:
        return entry[1]
    return None


def set_cache(key, value):
    _cache[key] = (time.time(), value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    def cache_cleaner():
        while True:
            time.sleep(300)
            _cache.clear()

    threading.Thread(target=cache_cleaner, daemon=True).start()
    threading.Thread(target=index_all_pastes, daemon=True).start()
    threading.Thread(target=backfill_snippets, daemon=True).start()
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
    has_secrets: bool = Query(None, description="Only pastes with secrets"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
):
    query = q.strip() if q.strip() else None
    if query and not any(c in query for c in ("*", "\"", "(", ")")):
        query = f'"{query}"'

    key = ("stats", query, source, content_type, has_secrets, tuple(secret_type))
    result = cached(key)
    if result is not None:
        return result

    conditions, params = build_filter_conditions(
        query=query,
        source=source,
        content_type=content_type,
        has_secrets=has_secrets,
        secret_types=secret_type if secret_type else None,
    )
    if conditions:
        result = get_stats_filtered(conditions, params)
    else:
        result = get_stats()
    set_cache(key, result)
    return result


@app.get("/api/sources")
def api_sources():
    result = cached("sources")
    if result is None:
        result = get_sources()
        set_cache("sources", result)
    return result


@app.get("/api/types")
def api_types():
    result = cached("types")
    if result is None:
        result = get_content_types()
        set_cache("types", result)
    return result


@app.get("/api/secret-types")
def api_secret_types():
    result = cached("secret-types")
    if result is None:
        result = get_secret_types()
        set_cache("secret-types", result)
    return result


@app.get("/api/pastes")
def api_search(
    q: str = Query("", description="Search query"),
    source: str = Query(None, description="Source filter"),
    content_type: str = Query(None, description="Content type filter"),
    has_secrets: bool = Query(None, description="Only pastes with secrets"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    query = q.strip() if q.strip() else None
    if query and not any(c in query for c in ("*", "\"", "(", ")")):
        query = f'"{query}"'
    return search_pastes(
        query=query,
        source=source,
        content_type=content_type,
        has_secrets=has_secrets,
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


@app.post("/api/reindex")
def api_reindex():
    _cache.clear()
    return index_all_pastes()


SPA_HTML = os.path.join(STATIC_DIR, "index.html") if os.path.exists(os.path.join(STATIC_DIR, "index.html")) else None

if STATIC_DIR and os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        filepath = os.path.join(STATIC_DIR, full_path)
        if os.path.exists(filepath) and os.path.isfile(filepath):
            return FileResponse(filepath)
        if SPA_HTML:
            return FileResponse(SPA_HTML)
        raise HTTPException(status_code=404)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info")