import os
import csv
import io
import logging
import re
import sys
import threading
import time
import zipfile
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, Query, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, Response
import uvicorn

from database import init_db, build_filter_conditions, search_pastes, search_pastes_grouped, export_pastes, get_paste_by_id, get_sources, \
    get_content_types, get_secret_types, get_stats, get_stats_filtered, clear_all_data, DB_PATH, count_pastes
from scheduler import index_all_pastes, start_scheduler, get_index_progress, get_last_reindex_result, set_index_running, get_scheduler_info, reschedule_interval
import llm
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
def _get_stats_cached(query, source, content_type, has_secrets, secret_types, date_from, date_to):
    conditions, params = build_filter_conditions(
        query=query,
        source=source,
        content_type=content_type,
        has_secrets=has_secrets,
        secret_types=secret_types,
        date_from=date_from,
        date_to=date_to,
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Warm the stats cache in a background thread. Running this directly here
    # would block ASGI startup (uvicorn does not accept requests until lifespan
    # startup returns), and on a large database the full-scan COUNT is slow —
    # which delayed the UI and made the first /api/index-status poll fail.
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

    threading.Thread(target=index_all_pastes, daemon=True).start()
    start_scheduler(REINDEX_INTERVAL)
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
    source: list[str] = Query([], description="Source filter (repeatable)"),
    content_type: list[str] = Query([], description="Content type filter (repeatable)"),
    has_secrets: str = Query(None, description="Only pastes with secrets ('true' or 'false')"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
    date_from: str = Query(None, description="Filter by first_seen >= (YYYY-MM-DD)"),
    date_to: str = Query(None, description="Filter by first_seen <= (YYYY-MM-DD)"),
):
    return _get_stats_cached(
        normalize_fts_query(q),
        tuple(source) if source else None,
        tuple(content_type) if content_type else None,
        _parse_bool(has_secrets),
        tuple(secret_type),
        date_from,
        date_to,
    )


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
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    group_by: str = Query(None, description="Group results by column (source, content_type)"),
    date_from: str = Query(None, description="Filter by first_seen >= (YYYY-MM-DD)"),
    date_to: str = Query(None, description="Filter by first_seen <= (YYYY-MM-DD)"),
):
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
    )


@app.get("/api/pastes/export")
def api_pastes_export(
    format: str = Query("csv", description="Export format: 'csv' or 'json'"),
    q: str = Query("", description="Search query"),
    source: list[str] = Query([], description="Source filter (repeatable)"),
    content_type: list[str] = Query([], description="Content type filter (repeatable)"),
    has_secrets: str = Query(None, description="Only pastes with secrets ('true' or 'false')"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
    include_content: str = Query("false", description="Include full paste content ('true' or 'false')"),
    date_from: str = Query(None, description="Filter by first_seen >= (YYYY-MM-DD)"),
    date_to: str = Query(None, description="Filter by first_seen <= (YYYY-MM-DD)"),
):
    import json as jsonlib

    query = normalize_fts_query(q)
    has_sec = _parse_bool(has_secrets)
    inc_content = _parse_bool(include_content)
    secret_types = secret_type if secret_type else None

    rows = list(export_pastes(query=query, source=source or None, content_type=content_type or None,
                              has_secrets=has_sec, secret_types=secret_types,
                              include_content=inc_content,
                              date_from=date_from, date_to=date_to))

    if format == "json":
        def json_stream():
            yield "[\n"
            for i, row in enumerate(rows):
                if i > 0:
                    yield ",\n"
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
                       "first_seen", "secrets_detail"]
            if inc_content:
                headers.append("content")
            writer.writerow(headers)
            yield output.getvalue()
            for row in rows:
                output = io.StringIO()
                writer = csv.writer(output)
                vals = [row["id"], row["filename"], row["source"], row["content_type"],
                        row["size"], int(row["has_passwords"]), int(row["has_secrets"]),
                        ",".join(row["secret_types"]),
                        row["first_seen"], _fmt_sd(row.get("secrets_detail"))]
                if inc_content:
                    vals.append(row.get("content", ""))
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
    try:
        summary = llm.summarize_paste(paste_id, content)
        return {"summary": summary}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error("LLM summarize failed for %s: %s", paste_id, e)
        raise HTTPException(status_code=502, detail=str(e))


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
    """Build a deduplicated markdown table of findings from BlackSignal detections."""
    if not findings:
        return "## Detailed Findings\n\nNo individual findings detected.\n"

    lines = [
        "## Detailed Findings",
        "",
        f"{len(findings)} unique finding(s) across the analyzed pastes.",
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


def _safe_zip_filename(source: str, filename: str, paste_id: str, used: set) -> str:
    """Build a filesystem-safe, unique name for a per-paste report inside the ZIP."""
    base = f"{source}_{filename}" if filename else f"{source}_{paste_id}"
    # Replace path separators and other unsafe characters
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", base)
    safe = " ".join(safe.split())        # collapse whitespace
    safe = safe.strip(". ")
    if not safe:
        safe = "paste"
    if len(safe) > 120:
        safe = safe[:120]
    candidate = f"{safe}.md"
    n = 2
    while candidate.lower() in used:
        candidate = f"{safe}-{n}.md"
        n += 1
    used.add(candidate.lower())
    return candidate


@app.post("/api/llm/report")
def api_llm_report(
    q: str = Query("", description="Search query"),
    source: list[str] = Query([], description="Source filter (repeatable)"),
    content_type: list[str] = Query([], description="Content type filter (repeatable)"),
    has_secrets: str = Query(None, description="Only pastes with secrets ('true' or 'false')"),
    secret_type: list[str] = Query([], description="Secret type filters (OR)"),
    date_from: str = Query(None, description="Filter by first_seen >= (YYYY-MM-DD)"),
    date_to: str = Query(None, description="Filter by first_seen <= (YYYY-MM-DD)"),
):
    if not llm.is_configured():
        raise HTTPException(status_code=400, detail="OpenRouter not configured")
    if llm.get_report_progress().get("running"):
        raise HTTPException(status_code=409, detail="A report is already in progress")

    # Count first — cheap COUNT with no row content — so an unfiltered run over a
    # large database fails fast instead of materializing every paste into memory.
    query_norm = normalize_fts_query(q)
    has_sec = _parse_bool(has_secrets)
    secret_types = secret_type if secret_type else None
    total = count_pastes(
        query=query_norm,
        source=source or None,
        content_type=content_type or None,
        has_secrets=has_sec,
        secret_types=secret_types,
        date_from=date_from,
        date_to=date_to,
    )
    if total == 0:
        return {"status": "done", "report": "No pastes matched the current filters."}
    if total > MAX_REPORT_PASTES:
        raise HTTPException(
            status_code=400,
            detail=f"{total} pastes match — narrow your filters (max {MAX_REPORT_PASTES})",
        )

    # Metadata + secrets only (no content) and hard-capped at the limit. Full paste
    # content is fetched lazily per paste inside the worker thread so we never hold
    # every paste body in memory at once.
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
    ))
    total = len(rows)
    if total == 0:
        return {"status": "done", "report": "No pastes matched the current filters."}

    def _generate():
        llm._set_report_running(total)
        summaries = []
        per_paste_files = []
        used_names: set = set()
        # Deterministic, deduplicated findings collected directly from BlackSignal's
        # own regex detections (avoids the LLM repeating the same finding many times).
        findings = []
        seen = set()
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

            for sd in secrets_detail:
                match = (sd.get("match") or "").strip()
                if not match:
                    continue
                key = (row_source, pid, sd.get("type", "?"), match)
                if key in seen:
                    continue
                seen.add(key)
                findings.append({
                    "source": row_source,
                    "id": pid,
                    "filename": filename,
                    "type": sd.get("type", "?"),
                    "line": sd.get("line", 0),
                    "match": match,
                })

            bsi_str = "\n".join(
                f"- Line {sd.get('line', '?')}: [{sd.get('type', '?')}] {sd.get('match', '')}"
                for sd in secrets_detail
            ) or "None"

            try:
                summary = llm.summarize_paste(pid, content)
                entry = (
                    f"### Paste: {row_source}:{filename}\n\n"
                    f"**Source**: {row_source} | **ID**: `{pid}` | **Type**: {row_type} | **Size**: {row.get('size', 0)}B\n\n"
                    f"**BlackSignal detection**: has_secrets={row_has_secrets}, has_passwords={row_has_passwords}\n"
                    f"**Detected types**: {', '.join(secret_types) if secret_types else 'none'}\n\n"
                    f"**BlackSignal findings**:\n{bsi_str}\n\n"
                    f"**LLM analysis**:\n{summary}\n"
                )
                summaries.append(entry)
                per_paste_files.append({
                    "filename": _safe_zip_filename(row_source, filename, pid, used_names),
                    "content": entry,
                })
            except (ValueError, RuntimeError) as e:
                fail_entry = f"### Paste: {row_source}:{filename}\n\n*Analysis failed: {e}*\n"
                summaries.append(fail_entry)
                per_paste_files.append({
                    "filename": _safe_zip_filename(row_source, filename, pid, used_names),
                    "content": fail_entry,
                })
            llm._set_report_progress(i + 1)
        if llm.is_report_cancelled():
            return
        # Final aggregation (narrative sections only — detailed findings are appended below)
        llm._set_report_progress(total, phase="aggregating")
        if summaries:
            all_text = "\n---\n".join(summaries)
            try:
                final = llm._call_llm([
                    {"role": "system", "content": llm.REPORT_PROMPT},
                    {"role": "user", "content": f"INDIVIDUAL ANALYSES:\n\n{all_text}"},
                ])
                header = (
                    f"# BlackSignal — LLM Security Report\n\n"
                    f"**Pastes analyzed**: {len(summaries)} of {total}\n"
                    f"**Filters**: q={q!r}, source={source}, content_type={content_type}, "
                    f"has_secrets={has_secrets}, secret_type={secret_type}\n\n---\n\n"
                )
                detailed = _build_detailed_findings(findings)
                llm._set_report_done(header + final + "\n\n" + detailed, per_paste_files)
            except (ValueError, RuntimeError) as e:
                llm._set_report_error(str(e))
        else:
            llm._set_report_error("No summaries could be generated")
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
    progress = llm.get_report_progress()
    report = progress.get("final_report")
    if not report:
        raise HTTPException(status_code=404, detail="No completed report available")

    files = llm.get_report_files() or []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Overall report at the archive root
        zf.writestr("report.md", report)
        readme = (
            "# BlackSignal — LLM Report Bundle\n\n"
            "This archive contains:\n\n"
            "- `report.md` — the aggregated security report across all analyzed pastes.\n"
            "- `pastes/` — one markdown analysis per analyzed paste.\n\n"
            f"Pastes bundled: {len(files)}\n"
        )
        zf.writestr("README.md", readme)
        # Per-paste analyses in a subfolder
        for f in files:
            zf.writestr(f"pastes/{f['filename']}", f["content"])

    data = buf.getvalue()
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="blacksignal-llm-report.zip"',
            "Content-Length": str(len(data)),
        },
    )


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

    return {
        "db_size_bytes": db_size,
        "paste_count": paste_count,
        "raw_pastes_size_bytes": raw_size,
        "raw_pastes_count": raw_count,
    }


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