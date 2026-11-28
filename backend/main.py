import os
import csv
import io
import logging
import sys
import threading
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, Query, HTTPException, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, Response, JSONResponse
import uvicorn

from database import init_db, build_filter_conditions, search_pastes, search_pastes_grouped, export_pastes, get_paste_by_id, get_sources, \
    get_content_types, get_secret_types, get_stats, get_stats_filtered, clear_all_data, DB_PATH, count_pastes, \
    QueryError, validate_fts, update_triage, apply_triage_to_identical, backfill_meta, TRIAGE_STATUSES
from scheduler import index_all_pastes, start_scheduler, get_index_progress, get_last_reindex_result, set_index_running, get_scheduler_info, reschedule_interval
import llm
import reports
import auth
import settings
import analysis
import render
import json as _json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("blacksignal")

# Indexing runs CPU-bound detection in threads inside this same process (no
# multiprocessing by design). A shorter GIL switch interval lets the ASGI event
# loop preempt those threads more often, keeping API calls responsive during a
# large index run at a negligible throughput cost.
sys.setswitchinterval(0.001)

STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")
REINDEX_INTERVAL = int(os.environ.get("REINDEX_INTERVAL", "300"))
AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes")

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


_CSV_INJECTION_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in a CSV cell.

    Pastes are attacker-controlled; a cell starting with ``=``/``+``/``-``/``@``
    can execute as a formula when opened in Excel/LibreOffice."""
    if isinstance(value, str) and value.startswith(_CSV_INJECTION_PREFIXES):
        return "'" + value
    return value


def _static_path(root: str, full_path: str) -> str | None:
    """Resolve a static file path, returning None if it escapes ``root``."""
    real_root = os.path.realpath(root)
    # Defensively decode too: some proxies pass percent-encoded segments through.
    target = os.path.realpath(os.path.join(real_root, unquote(full_path)))
    if target != real_root and not target.startswith(real_root + os.sep):
        return None
    return target


# --- Cached data accessors -------------------------------------------------
# Data only changes when the indexer runs (which calls clear_cache), so
# lru_cache bounded by the number of distinct filter combinations is safe.

@lru_cache(maxsize=256)
def _get_stats_cached(query, source, content_type, has_secrets, secret_types, date_from, date_to, triage_status=(), stale=False):
    conditions, params = build_filter_conditions(
        query=query,
        source=source,
        content_type=content_type,
        has_secrets=has_secrets,
        secret_types=secret_types,
        date_from=date_from,
        date_to=date_to,
        triage_status=triage_status,
        stale=stale,
    )
    if conditions:
        return get_stats_filtered(conditions, params)
    return get_stats()


@lru_cache(maxsize=1)
def _get_sources_cached():
    return get_sources()


def _get_sources_filtered(content_type: str):
    return get_sources(content_type=content_type)


@lru_cache(maxsize=1)
def _get_types_cached():
    return get_content_types()


def _get_types_filtered(source: str):
    return get_content_types(source=source)


@lru_cache(maxsize=1)
def _get_secret_types_cached():
    return get_secret_types()


def _get_secret_types_filtered(source: str | None = None, content_type: str | None = None):
    return get_secret_types(source=source, content_type=content_type)


def clear_cache():
    """Invalidate all cached API responses (called after re-indexing)."""
    for fn in (_get_stats_cached, _get_sources_cached, _get_types_cached, _get_secret_types_cached):
        fn.cache_clear()


def clear_stats_cache():
    """Invalidate only the cached stats.

    Triage changes alter the counters but never the source/type/secret-type
    distributions, so the (more expensive) distribution scans are kept."""
    _get_stats_cached.cache_clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if AUTH_DISABLED:
        logger.warning("AUTH_DISABLED is set — API authentication is DISABLED. Do not use in production.")

    # Prepare credential hash + signing secret before serving (idempotent).
    try:
        auth.ensure_auth_files()
    except Exception:
        logger.exception("Failed to initialise authentication files")

    # Import a legacy data/openrouter.json into settings.json (one-time).
    settings.migrate_legacy_openrouter()

    init_db()

    # Warm the stats cache in a background thread. Running this directly here
    # would block ASGI startup and delay the UI. The aggregate is index-backed
    # now, but keeping it off the startup path avoids competing with the initial
    # index run for I/O.
    def _warm_stats():
        try:
            # Wait for the initial index run to finish: it starts immediately at
            # boot and the UI blocks data calls while indexing anyway, so scanning
            # now would only compete with it for CPU/IO.
            while get_index_progress().get("running"):
                time.sleep(2)
            _get_stats_cached(None, None, None, None, (), None, None)
        except Exception:
            logger.exception("Stats warm-up failed (non-fatal)")

    threading.Thread(target=_warm_stats, daemon=True).start()

    # Hash/priority metadata for rows indexed before paste_meta existed. Runs
    # after the initial index pass and in small batches so it never competes
    # with indexing for the write lock.
    def _backfill_meta():
        try:
            while get_index_progress().get("running"):
                time.sleep(2)
            total = 0
            while True:
                n = backfill_meta()
                if not n:
                    break
                total += n
                if total % 5000 < n:
                    logger.info("Metadata backfill: %d pastes processed", total)
                time.sleep(0.05)
            if total:
                logger.info("Metadata backfill complete: %d pastes", total)
        except Exception:
            logger.exception("Metadata backfill failed (non-fatal)")

    threading.Thread(target=_backfill_meta, daemon=True).start()

    threading.Thread(target=index_all_pastes, daemon=True).start()
    start_scheduler(settings.get_interval(REINDEX_INTERVAL))
    yield


app = FastAPI(
    title="BlackSignal",
    description="Self-hosted paste intelligence: browse, search, and analyze paste data with automatic sensitive-info detection.",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


# --- Authentication -----------------------------------------------------------
# Everything under /api/ requires a valid session cookie or HTTP Basic
# credentials, except the auth endpoints and the health probe. Non-/api paths
# (the SPA) stay public so the login screen can load.
#
# There is intentionally no CORS middleware: the SPA and API are same-origin.

_PUBLIC_AUTH_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/session",
    "/api/auth/logout",
    "/api/healthz",
})


def _origin_matches_host(origin: str, host: str) -> bool:
    """Validate a request ``Origin`` against the ``Host`` header.

    Hostnames must match. If both sides carry a port it must match too, which
    rejects same-host/different-port origins. When the ``Host`` header has no
    port (some proxies strip it), we accept on hostname alone so legitimate
    requests still work.
    """
    try:
        origin_parts = urlsplit(origin)
        host_parts = urlsplit("//" + host)
        origin_host = origin_parts.hostname
        host_name = host_parts.hostname
        origin_port = origin_parts.port
        host_port = host_parts.port
    except ValueError:
        return False
    if not origin_host or not host_name:
        return False
    if origin_host.lower() != host_name.lower():
        return False
    if origin_port is not None and host_port is not None and origin_port != host_port:
        return False
    return True


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # CSRF defence: reject mutating API requests whose Origin host doesn't match
    # the request host. Same-origin browser requests and non-browser clients
    # (no Origin header, e.g. curl) are unaffected.
    if path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and not _origin_matches_host(origin, request.headers.get("host", "")):
            return JSONResponse(status_code=403, content={"detail": "Cross-origin request rejected"})

    if AUTH_DISABLED or not path.startswith("/api/") or path in _PUBLIC_AUTH_PATHS:
        return await call_next(request)

    token = request.cookies.get(auth.SESSION_COOKIE)
    user = auth.verify_session_token(token)
    if not user:
        user = auth.verify_basic(request.headers.get("authorization"))
    if not user:
        # JSON 401 without WWW-Authenticate — never trigger a browser popup.
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    request.state.user = user
    return await call_next(request)


@app.get("/api/healthz")
def api_healthz():
    """Liveness probe — public, no database access."""
    return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})


@app.post("/api/auth/login")
def api_auth_login(request: Request, body: dict = Body(...)):
    ip = request.client.host if request.client else "unknown"
    if auth.is_rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too many failed attempts — try again later")

    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    user = auth.verify_credentials(username, password)
    if not user:
        auth.register_failure(ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    auth.reset_failures(ip)

    token = auth.create_session_token(user)
    resp = JSONResponse({"ok": True, "username": user})
    resp.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.session_days() * 86400,
        httponly=True,
        samesite="lax",
        secure=auth.cookie_secure(),
        path="/",
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/auth/session")
def api_auth_session(request: Request):
    token = request.cookies.get(auth.SESSION_COOKIE)
    user = auth.verify_session_token(token)
    if not user:
        user = auth.verify_basic(request.headers.get("authorization"))
    return JSONResponse(
        {"authenticated": bool(user), "username": user},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/auth/logout")
def api_auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.SESSION_COOKIE, path="/")
    return resp


@app.get("/api/stats")
def api_stats(
    q: str = Query("", description="Search query"),
    source: list[str] = Query([], description="Source filter (repeatable)"),
    content_type: list[str] = Query([], description="Content type filter (repeatable)"),
    has_secrets: str = Query(None, description="Only pastes with secrets ('true' or 'false')"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
    triage_status: list[str] = Query([], description="Triage status filter (OR)"),
    stale: bool = Query(False, description="Only pastes changed since they were triaged"),
    date_from: str = Query(None, description="Filter by first_seen >= (YYYY-MM-DD)"),
    date_to: str = Query(None, description="Filter by first_seen <= (YYYY-MM-DD)"),
):
    try:
        return _get_stats_cached(
            normalize_fts_query(q),
            tuple(source) if source else None,
            tuple(content_type) if content_type else None,
            _parse_bool(has_secrets),
            tuple(secret_type),
            date_from,
            date_to,
            tuple(triage_status),
            stale,
        )
    except QueryError:
        raise HTTPException(status_code=400, detail="Invalid search query")


@app.get("/api/sources")
def api_sources(content_type: str = Query(None, description="Filter by content type")):
    if content_type:
        return _get_sources_filtered(content_type)
    return _get_sources_cached()


@app.get("/api/types")
def api_types(source: str = Query(None, description="Filter by source")):
    if source:
        return _get_types_filtered(source)
    return _get_types_cached()


@app.get("/api/secret-types")
def api_secret_types(source: str = Query(None, description="Filter by source"),
                      content_type: str = Query(None, description="Filter by content type")):
    if source or content_type:
        return _get_secret_types_filtered(source=source, content_type=content_type)
    return _get_secret_types_cached()


@app.get("/api/pastes")
def api_search(
    q: str = Query("", description="Search query"),
    source: list[str] = Query([], description="Source filter (repeatable)"),
    content_type: list[str] = Query([], description="Content type filter (repeatable)"),
    has_secrets: str = Query(None, description="Only pastes with secrets ('true' or 'false')"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
    triage_status: list[str] = Query([], description="Triage status filter (OR)"),
    stale: bool = Query(False, description="Only pastes changed since they were triaged"),
    sort: str = Query(None, description="Sort order: 'priority' or default newest"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    group_by: str = Query(None, description="Group results by column (source, content_type)"),
    date_from: str = Query(None, description="Filter by first_seen >= (YYYY-MM-DD)"),
    date_to: str = Query(None, description="Filter by first_seen <= (YYYY-MM-DD)"),
):
    try:
        if group_by:
            return search_pastes_grouped(
                group_by=group_by,
                query=normalize_fts_query(q),
                source=source or None,
                content_type=content_type or None,
                has_secrets=_parse_bool(has_secrets),
                secret_types=secret_type if secret_type else None,
                date_from=date_from,
                date_to=date_to,
                triage_status=triage_status or None,
                stale=stale,
            )
        return search_pastes(
            query=normalize_fts_query(q),
            source=source or None,
            content_type=content_type or None,
            has_secrets=_parse_bool(has_secrets),
            secret_types=secret_type if secret_type else None,
            page=page,
            per_page=per_page,
            date_from=date_from,
            date_to=date_to,
            triage_status=triage_status or None,
            stale=stale,
            sort=sort,
        )
    except QueryError:
        raise HTTPException(status_code=400, detail="Invalid search query")


@app.get("/api/pastes/export")
def api_pastes_export(
    format: str = Query("csv", description="Export format: 'csv' or 'json'"),
    q: str = Query("", description="Search query"),
    source: list[str] = Query([], description="Source filter (repeatable)"),
    content_type: list[str] = Query([], description="Content type filter (repeatable)"),
    has_secrets: str = Query(None, description="Only pastes with secrets ('true' or 'false')"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
    triage_status: list[str] = Query([], description="Triage status filter (OR)"),
    stale: bool = Query(False, description="Only pastes changed since they were triaged"),
    include_content: str = Query("false", description="Include full paste content ('true' or 'false')"),
    date_from: str = Query(None, description="Filter by first_seen >= (YYYY-MM-DD)"),
    date_to: str = Query(None, description="Filter by first_seen <= (YYYY-MM-DD)"),
):
    import json as jsonlib

    query = normalize_fts_query(q)
    has_sec = _parse_bool(has_secrets)
    inc_content = _parse_bool(include_content)
    secret_types = secret_type if secret_type else None

    # Validate the FTS expression up-front so a malformed query returns 400
    # instead of aborting a partially-streamed response.
    if query:
        try:
            validate_fts(query)
        except QueryError:
            raise HTTPException(status_code=400, detail="Invalid search query")

    rows = export_pastes(query=query, source=source or None, content_type=content_type or None,
                         has_secrets=has_sec, secret_types=secret_types,
                         include_content=inc_content,
                         date_from=date_from, date_to=date_to,
                         triage_status=triage_status or None,
                         stale=stale)

    if format == "json":
        def json_stream():
            yield "[\n"
            first = True
            for row in rows:
                if not first:
                    yield ",\n"
                first = False
                row["has_passwords"] = bool(row["has_passwords"])
                row["has_secrets"] = bool(row["has_secrets"])
                # Include full secrets_detail (already parsed as Python list)
                yield jsonlib.dumps(row)
            yield "\n]"

        return StreamingResponse(
            json_stream(),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=\"blacksignal-export.json\""},
        )
    else:
        def _fmt_sd(details):
            """Flatten secrets_detail for CSV: '[type] line L: line_text' per finding."""
            if not details:
                return ""
            parts = []
            for f in details:
                lt = f.get("line_text", "").strip()
                if lt:
                    parts.append(f"[{f['type']}] {lt[:200]}")
            return " | ".join(parts)

        def csv_stream():
            output = io.StringIO()
            writer = csv.writer(output)
            yield output.getvalue()
            # header
            output = io.StringIO()
            writer = csv.writer(output)
            headers = ["id", "filename", "source", "content_type", "size",
                       "has_passwords", "has_secrets", "secret_types",
                       "first_seen", "triage_status", "triage_reviewer",
                       "triage_updated_at", "triage_note", "secrets_detail"]
            if inc_content:
                headers.append("content")
            writer.writerow(headers)
            yield output.getvalue()
            for row in rows:
                output = io.StringIO()
                writer = csv.writer(output)
                vals = [
                    _csv_safe(row["id"]), _csv_safe(row["filename"]),
                    _csv_safe(row["source"]), _csv_safe(row["content_type"]),
                    row["size"], int(row["has_passwords"]), int(row["has_secrets"]),
                    _csv_safe(",".join(row["secret_types"])),
                    _csv_safe(row["first_seen"]),
                    _csv_safe(row.get("triage_status", "new")),
                    _csv_safe(row.get("triage_reviewer", "")),
                    _csv_safe(row.get("triage_updated_at") or ""),
                    _csv_safe(row.get("triage_note", "")),
                    _csv_safe(_fmt_sd(row.get("secrets_detail"))),
                ]
                if inc_content:
                    vals.append(_csv_safe(row.get("content", "")))
                writer.writerow(vals)
                yield output.getvalue()

        return StreamingResponse(
            csv_stream(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=\"blacksignal-export.csv\""},
        )


@app.get("/api/pastes/{paste_id}")
def api_paste_detail(paste_id: str):
    paste = get_paste_by_id(paste_id)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found")
    return paste


@app.patch("/api/pastes/{paste_id}/triage")
def api_paste_triage(paste_id: str, request: Request, body: dict = Body(...)):
    status = body.get("status")
    note = body.get("note")
    if status is None and note is None:
        raise HTTPException(status_code=400, detail="Provide a status and/or note")
    if status is not None and status not in TRIAGE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid triage status")
    if note is not None:
        note = str(note)
        if len(note) > 2000:
            raise HTTPException(status_code=400, detail="Note is too long (max 2000 characters)")

    reviewer = getattr(request.state, "user", None) or "system"
    updated = update_triage(paste_id, status=status, note=note, reviewer=reviewer)
    if updated is None:
        raise HTTPException(status_code=404, detail="Paste not found")
    # Stats (filtered and global, including triage counts) are lru_cached; a
    # triage change must invalidate them or the counters stay stale until the
    # next index run clears the cache. Distributions are unaffected, so only
    # the stats cache is dropped.
    clear_stats_cache()
    return updated


@app.post("/api/pastes/{paste_id}/triage/identical")
def api_paste_triage_identical(paste_id: str, request: Request, body: dict = Body(...)):
    status = body.get("status")
    note = body.get("note", "")
    if status not in TRIAGE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid triage status")
    note = str(note)
    if len(note) > 2000:
        raise HTTPException(status_code=400, detail="Note is too long (max 2000 characters)")

    reviewer = getattr(request.state, "user", None) or "system"
    updated = apply_triage_to_identical(paste_id, status=status, note=note, reviewer=reviewer)
    if updated is None:
        raise HTTPException(status_code=404, detail="Paste or content hash not found")
    clear_stats_cache()
    return {"updated": updated}


@app.get("/api/version")
def api_version():
    return {"version": APP_VERSION}


@app.get("/api/index-status")
async def api_index_status():
    return get_index_progress()


@app.get("/api/last-reindex")
def api_last_reindex():
    return get_last_reindex_result()


@app.get("/api/indexer-info")
def api_indexer_info():
    return get_scheduler_info()


@app.post("/api/indexer-info")
def api_indexer_info_set(body: dict = Body(...)):
    interval = body.get("interval_seconds")
    if not isinstance(interval, int) or interval < 3600:
        raise HTTPException(status_code=400, detail="Interval must be at least 3600 seconds (1 hour)")
    try:
        reschedule_interval(interval)
        settings.set_interval(interval)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return get_scheduler_info()


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


# --- LLM / OpenRouter -------------------------------------------------------


@lru_cache(maxsize=1)
def _get_llm_config_cached():
    return {"configured": llm.is_configured()}


@app.get("/api/llm/config")
def api_llm_config():
    return _get_llm_config_cached()


@app.post("/api/llm/summarize/{paste_id}")
def api_llm_summarize(paste_id: str):
    paste = get_paste_by_id(paste_id)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found")
    content = paste.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="Paste has no content")
    title = f"{paste.get('source', '?')}:{paste.get('filename') or paste_id}"
    try:
        result = llm.summarize_paste(paste_id, content, title=title)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error("LLM summarize failed for %s: %s", paste_id, e)
        raise HTTPException(status_code=502, detail=str(e))

    markdown = result["markdown"]

    # Persist to the report archive (best-effort — never fail the analysis).
    report_id = None
    try:
        report_id = reports.save_single(
            {
                "paste_id": paste_id,
                "source": paste.get("source"),
                "filename": paste.get("filename"),
            },
            markdown,
            model=llm.MODEL,
            analysis=result.get("analysis"),
        )
    except Exception:
        logger.exception("Failed to archive single-paste report %s", paste_id)

    return {
        "summary": markdown,
        "analysis": result.get("analysis"),
        "structured": result.get("structured", False),
        "report_id": report_id,
    }


@app.get("/api/llm/key")
def api_llm_key():
    return {"key_preview": llm.get_key_preview()}


@app.post("/api/llm/key")
def api_llm_key_save(body: dict = Body(...)):
    key = (body.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Key is required")
    llm.save_key(key)
    # Invalidate the cached config endpoint so the UI reflects the change
    _get_llm_config_cached.cache_clear()
    return {"configured": True}


@app.delete("/api/llm/key")
def api_llm_key_delete():
    llm.remove_key()
    _get_llm_config_cached.cache_clear()
    return {"configured": False}


# --- LLM Report ----------------------------------------------------------------

# Hard cap on pastes per report run. Enforced with a cheap COUNT before any
# paste content is loaded, so an unfiltered run over a large DB fails fast.
MAX_REPORT_PASTES = 500


def _build_detailed_findings(findings: list, max_rows: int = 2000) -> str:
    """Build a deduplicated markdown table of BlackSignal's own detections."""
    if not findings:
        return "## BlackSignal Detections\n\nNo regex detections.\n"

    lines = [
        "## BlackSignal Detections",
        "",
        f"{len(findings)} unique detection(s) from BlackSignal's regex scanner.",
        "",
        "| Source | Paste ID | Type | Line | Finding |",
        "|---|---|---|---|---|",
    ]
    for f in findings[:max_rows]:
        # Escape pipes and collapse newlines so the markdown table stays intact
        match = " ".join(str(f["match"]).split())
        match = match.replace("|", "\\|")
        if len(match) > 160:
            match = match[:157] + "..."
        paste_id = str(f["id"]).replace("|", "\\|")
        lines.append(
            f"| {f['source']} | `{paste_id}` | {f['type']} | {f['line']} | `{match}` |"
        )
    if len(findings) > max_rows:
        lines.append("")
        lines.append(f"*... and {len(findings) - max_rows} more findings (truncated).*")
    lines.append("")
    return "\n".join(lines)


@app.post("/api/llm/report")
def api_llm_report(
    q: str = Query("", description="Search query"),
    source: list[str] = Query([], description="Source filter (repeatable)"),
    content_type: list[str] = Query([], description="Content type filter (repeatable)"),
    has_secrets: str = Query(None, description="Only pastes with secrets ('true' or 'false')"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
    triage_status: list[str] = Query([], description="Triage status filter (OR)"),
    stale: bool = Query(False, description="Only pastes changed since they were triaged"),
    date_from: str = Query(None, description="Filter by first_seen >= (YYYY-MM-DD)"),
    date_to: str = Query(None, description="Filter by first_seen <= (YYYY-MM-DD)"),
):
    if not llm.is_configured():
        raise HTTPException(status_code=400, detail="OpenRouter not configured")

    # Count first — cheap COUNT with no row content — so an unfiltered run over a
    # large database fails fast instead of materializing every paste into memory.
    query_norm = normalize_fts_query(q)
    has_sec = _parse_bool(has_secrets)
    secret_types = secret_type if secret_type else None
    try:
        total = count_pastes(
            query=query_norm,
            source=source or None,
            content_type=content_type or None,
            has_secrets=has_sec,
            secret_types=secret_types,
            date_from=date_from,
            date_to=date_to,
            triage_status=triage_status or None,
            stale=stale,
        )
    except QueryError:
        raise HTTPException(status_code=400, detail="Invalid search query")
    if total == 0:
        return {"status": "done", "report": "No pastes matched the current filters."}
    if total > MAX_REPORT_PASTES:
        raise HTTPException(
            status_code=400,
            detail=f"{total} pastes match — narrow your filters (max {MAX_REPORT_PASTES})",
        )

    # Claim the run atomically before any expensive work. Without this, two
    # concurrent requests could both pass the check and start two paid runs.
    if not llm.begin_report():
        raise HTTPException(status_code=409, detail="A report is already in progress")

    try:
        # Metadata + secrets only (no content) and hard-capped at the limit. Full
        # paste content is fetched lazily per paste inside the worker thread so we
        # never hold every paste body in memory at once.
        rows = list(export_pastes(
            query=query_norm,
            source=source or None,
            content_type=content_type or None,
            has_secrets=has_sec,
            secret_types=secret_types,
            include_content=False,
            date_from=date_from,
            date_to=date_to,
            limit=MAX_REPORT_PASTES,
            triage_status=triage_status or None,
            stale=stale,
        ))
    except QueryError:
        llm.reset_report_progress()
        raise HTTPException(status_code=400, detail="Invalid search query")
    except Exception:
        llm.reset_report_progress()
        raise

    total = len(rows)
    if total == 0:
        llm.reset_report_progress()
        return {"status": "done", "report": "No pastes matched the current filters."}

    def _generate():
        llm._set_report_running(total)
        per_paste_files: list[dict] = []
        used_names: set = set()
        pastes_meta: list = []
        structured_findings: list = []
        regex_findings: list = []
        seen = set()
        analysed = 0

        for i, row in enumerate(rows):
            if llm.is_report_cancelled():
                return
            if llm.get_report_progress().get("phase") == "error":
                return
            pid = row.get("id", "unknown")
            row_source = row.get("source", "?")
            filename = row.get("filename", pid)
            # Content is fetched lazily (one paste at a time) so we never hold all
            # paste bodies in memory simultaneously.
            paste = get_paste_by_id(pid)
            content = (paste or {}).get("content", "") or ""
            row_type = row.get("content_type", "?")
            row_has_secrets = row.get("has_secrets", 0)
            row_has_passwords = row.get("has_passwords", 0)
            secret_types = row.get("secret_types", [])
            secrets_detail = row.get("secrets_detail") or []
            title = f"{row_source}:{filename}"

            entry = {
                "id": pid,
                "source": row_source,
                "filename": filename,
                "content_type": row_type,
                "size": row.get("size", 0),
                "has_secrets": bool(row_has_secrets),
                "has_passwords": bool(row_has_passwords),
                "secret_types": secret_types,
                "first_seen": row.get("first_seen"),
                "findings": 0,
            }
            pastes_meta.append(entry)

            for sd in secrets_detail:
                match = (sd.get("match") or "").strip()
                if not match:
                    continue
                key = (row_source, pid, sd.get("type", "?"), match)
                if key in seen:
                    continue
                seen.add(key)
                regex_findings.append({
                    "source": row_source,
                    "id": pid,
                    "filename": filename,
                    "type": sd.get("type", "?"),
                    "line": sd.get("line", 0),
                    "match": match,
                })

            out_name = reports.safe_filename(
                f"{row_source}_{filename}" if filename else f"{row_source}_{pid}",
                used_names,
            )

            try:
                result = llm.summarize_paste(pid, content, title=title)
                structured = result.get("analysis") if result.get("structured") else None
                if structured:
                    entry["findings"] = len(structured.get("findings") or [])
                    for f in structured.get("findings") or []:
                        structured_findings.append({
                            **f,
                            "paste_id": pid,
                            "source": row_source,
                            "filename": filename,
                        })
                    analysed += 1
                per_paste_files.append({"filename": out_name, "content": result["markdown"]})
            except (ValueError, RuntimeError) as e:
                fail_entry = (
                    f"# BlackSignal — LLM Analysis\n\n**Paste**: `{title}`\n\n"
                    f"## Analysis Failed\n\n*{e}*\n"
                )
                per_paste_files.append({"filename": out_name, "content": fail_entry})
            llm._set_report_progress(i + 1)

        if llm.is_report_cancelled():
            return
        llm._set_report_progress(total, phase="aggregating")
        if not per_paste_files:
            llm._set_report_error("No summaries could be generated")
            return

        filters = {
            "q": q,
            "source": source,
            "content_type": content_type,
            "has_secrets": has_secrets,
            "secret_type": secret_type,
            "triage_status": triage_status,
            "stale": stale,
            "date_from": date_from,
            "date_to": date_to,
        }

        # Deterministic aggregation: dedupe values across pastes and correlate
        # entities that appear in more than one paste.
        deduped = analysis.dedupe_findings(structured_findings)
        correlations = analysis.correlate(structured_findings)

        compact = _json.dumps({
            "paste_count": len(pastes_meta),
            "analysed": analysed,
            "filters": {k: v for k, v in filters.items() if v},
            "findings": [
                {
                    "severity": f.get("severity"),
                    "kind": f.get("kind"),
                    "category": f.get("category"),
                    "title": f.get("title"),
                    "relationship": f.get("relationship"),
                    "entities": f.get("entities", []),
                    "pastes": len(f.get("pastes", [])),
                }
                for f in deduped[:150]
            ],
            "correlations": [
                {"type": c["type"], "value": c["value"], "pastes": len(c["pastes"])}
                for c in correlations[:100]
            ],
        }, separators=(",", ":"))

        try:
            narrative = llm.summarize_batch(compact)
        except (ValueError, RuntimeError) as e:
            llm._set_report_error(str(e))
            return
        # The rating is derived from the identified findings (and correlations).
        narrative["risk"] = analysis.compute_risk(deduped, correlations)

        report_text = render.render_batch(
            narrative,
            deduped,
            correlations,
            pastes_meta,
            filters=filters,
            total_analyzed=len(pastes_meta),
            regex_findings_markdown=_build_detailed_findings(regex_findings),
        )
        llm._set_report_done(report_text, per_paste_files)

        # Persist to the report archive (best-effort — never fail the run).
        try:
            reports.save_batch(
                {"filters": filters},
                report_text,
                per_paste_files,
                model=llm.MODEL,
                pastes=pastes_meta,
                analysis={
                    "narrative": narrative,
                    "findings": deduped,
                    "correlations": correlations,
                    "analysed": analysed,
                },
            )
        except Exception:
            logger.exception("Failed to archive batch report")
    threading.Thread(target=_generate, daemon=True).start()
    return {"status": "started", "total": total}


@app.get("/api/llm/report-status")
def api_llm_report_status():
    return llm.get_report_progress()


@app.post("/api/llm/report-cancel")
def api_llm_report_cancel():
    llm.cancel_report()
    return {"status": "cancelled"}


@app.get("/api/llm/report-download")
def api_llm_report_download():
    """Backward-compatible alias: download the newest archived batch report."""
    for meta in reports.list_reports():
        if meta.get("type") == "batch":
            data = reports.build_zip(meta["id"])
            if data is not None:
                return Response(
                    content=data,
                    media_type="application/zip",
                    headers={
                        "Content-Disposition": 'attachment; filename="blacksignal-llm-report.zip"',
                        "Content-Length": str(len(data)),
                    },
                )
            break
    raise HTTPException(status_code=404, detail="No completed report available")


# --- Report archive -----------------------------------------------------------


@app.get("/api/reports")
def api_reports_list():
    return {"reports": reports.list_reports()}


@app.get("/api/reports/{report_id}/download")
def api_report_download(report_id: str):
    item = reports.get_report(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="Report not found")
    meta = item["meta"]
    if meta.get("type") == "batch":
        data = reports.build_zip(report_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Report not found")
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="blacksignal-report-{report_id}.zip"',
                "Content-Length": str(len(data)),
            },
        )
    content = item["markdown"].encode("utf-8")
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="blacksignal-report-{report_id}.md"',
            "Content-Length": str(len(content)),
        },
    )


@app.get("/api/reports/{report_id}")
def api_report_get(report_id: str):
    item = reports.get_report(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="Report not found")
    return item


@app.delete("/api/reports")
def api_reports_delete_all():
    return {"deleted": reports.delete_all_reports()}


@app.delete("/api/reports/{report_id}")
def api_report_delete(report_id: str):
    if not reports.delete_report(report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"status": "deleted"}


# --- Database / config stats --------------------------------------------------


import indexer as indexer_module


def _get_dir_size(path: str) -> int:
    """Recursively sum file sizes in a directory."""
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path):
            for fn in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, fn))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _get_file_count(path: str) -> int:
    """Count files recursively in a directory."""
    count = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path):
            count += len(filenames)
    except OSError:
        pass
    return count


@app.get("/api/db-stats")
def api_db_stats():
    from database import get_conn
    conn = get_conn()
    paste_count = conn.execute("SELECT COUNT(*) FROM pastes").fetchone()[0]

    db_size = 0
    try:
        db_size = os.path.getsize(DB_PATH)
    except OSError:
        pass

    raw_path = indexer_module.RAW_PASTES_DIR
    raw_size = _get_dir_size(raw_path)
    raw_count = _get_file_count(raw_path)
    # Files the indexer will actually scan: regular files directly inside each
    # top-level source folder. Reuse walk_pastes() so this matches the indexer
    # exactly instead of re-implementing the walk semantics.
    try:
        indexable_count = len(indexer_module.walk_pastes())
    except Exception:
        logger.exception("Failed to count indexable files")
        indexable_count = 0

    return {
        "db_size_bytes": db_size,
        "paste_count": paste_count,
        "raw_pastes_size_bytes": raw_size,
        "raw_files_total": raw_count,
        "indexable_files_count": indexable_count,
    }


# --- SPA static serving -----------------------------------------------------

if STATIC_DIR and os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        filepath = _static_path(STATIC_DIR, full_path)
        if filepath is None:
            raise HTTPException(status_code=404)
        if os.path.isfile(filepath):
            return FileResponse(filepath)
        spa_html = os.path.join(os.path.realpath(STATIC_DIR), "index.html")
        if os.path.exists(spa_html):
            return FileResponse(spa_html)
        raise HTTPException(status_code=404)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info")