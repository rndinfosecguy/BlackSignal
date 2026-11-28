import os
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from indexer import walk_pastes, detect_content_type
from database import (upsert_paste, get_indexed_ids, get_indexed_mtimes,
                      delete_paste, get_conn, get_stats, get_sources,
                      get_content_types, get_secret_types, search_pastes)
from detector import scan_content

logger = logging.getLogger("blacksignal")

# Number of parallel I/O + detection workers. Set INDEX_WORKERS=0 to disable
# multi-threaded indexing (same as the original single-threaded behaviour).
_INDEX_WORKERS = int(os.environ.get("INDEX_WORKERS", "6"))

_index_lock = threading.Lock()

_index_progress = {
    "running": False,
    "current": 0,
    "total": 0,
    "phase": "",
}

# Last reindex result — stored by index_all_pastes, read by /api/last-reindex.
# Always holds the last *successful* run's counts plus attempt/error metadata.
_last_reindex_result = {}


def get_last_reindex_result():
    return dict(_last_reindex_result)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def get_index_progress():
    return dict(_index_progress)


def set_index_running(running: bool, phase: str = ""):
    """Set the running state and phase of the indexer.
    Used by purge to mark itself running before the long clear_all_data() call."""
    _index_progress.update(running=running, current=0, total=0, phase=phase)


def _warm_os_cache():
    """Run the queries the UI hits first so their pages are in the OS cache.

    Called at the end of every index run. Uses the real data accessors rather
    than hand-written SQL so the warm-up cannot drift from the endpoints. The
    old full FTS count was removed: it cost hundreds of ms per run and did not
    warm what normal searches use.
    """
    try:
        logger.info("Warming OS cache with common queries\u2026")
        # Global stats: covering index scan (idx_pastes_stats).
        get_stats()
        # Dashboard distributions.
        get_sources()
        get_content_types()
        get_secret_types()
        # First list page: row pages, paste_meta join and duplicate counts.
        search_pastes(page=1, per_page=50)
        # The queue users open first: unreviewed, priority-sorted.
        search_pastes(triage_status=["new"], has_secrets=True,
                      sort="priority", per_page=50)
        logger.info("Cache warm-up complete")
    except Exception:
        logger.exception("Cache warm-up failed (non-fatal)")


def _process_single(f, scan_limit=None):
    """Read, detect and scan a single file — runs in a worker thread.
    scan_limit — max chars to scan (None = default 200K, 0 = unlimited)."""
    # Skip tiny files — realistically can't contain meaningful secrets
    if f["size"] < 32:
        return {"id": f["id"], "skipped": True}
    try:
        with open(f["path"], "r", errors="replace") as fh:
            content = fh.read(512000)
    except Exception as e:
        return {"id": f["id"], "error": str(e)}

    try:
        content_type = detect_content_type(f["path"], content)
        has_passwords, has_secrets, findings = scan_content(content, scan_limit=scan_limit)
        # Determine if the file was fully scanned
        if scan_limit == 0:
            fully_scanned = 1  # comprehensive — full content scanned
        else:
            effective_limit = 200000 if scan_limit is None else scan_limit
            fully_scanned = 1 if len(content) <= effective_limit else 0
        return {
            "id": f["id"],
            "filename": f["filename"],
            "source": f["source"],
            "content": content,
            "content_type": content_type,
            "size": f["size"],
            "has_passwords": 1 if has_passwords else 0,
            "has_secrets": 1 if has_secrets else 0,
            "secrets_detail": findings,
            "modified_at": f["modified_at"],
            "fully_scanned": fully_scanned,
        }
    except Exception as e:
        return {"id": f["id"], "error": str(e)}


def index_all_pastes(scan_limit=None, incremental=False):
    """Index all paste files. 
    scan_limit — max chars to scan per file (None = default 200K, 0 = unlimited).
    incremental — when True, skip files whose mtime hasn't changed since last index."""
    if not _index_lock.acquire(blocking=False):
        logger.info("Index already in progress, skipping")
        return

    started = time.monotonic()
    _last_reindex_result["last_attempt_at"] = _now_iso()
    _last_reindex_result.pop("last_error", None)
    _last_reindex_result.pop("last_error_at", None)

    try:
        _index_progress.update(running=True, current=0, total=0, phase="scanning")
        files = walk_pastes()
        indexed_ids = get_indexed_ids()
        current_ids = set()
        indexed_count = 0
        deleted_count = 0

        # In incremental mode, also look up stored mtimes to skip unchanged files
        indexed_mtimes = get_indexed_mtimes() if incremental else {}

        total_files = len(files)

        _index_progress.update(current=0, total=total_files, phase="indexing")

        logger.info("Scanning %d files (%d new)", total_files, len(files) - len(indexed_ids))

        LOG_INTERVAL = max(1, total_files // 100)

        for f in files:
            current_ids.add(f["id"])

        # In comprehensive mode, re-process files that exceeded the default scan limit
        if scan_limit == 0:
            default_limit = 200000
            recheck_ids = {f["id"] for f in files if f["id"] in indexed_ids and f["size"] > default_limit}
            if recheck_ids:
                logger.info("Comprehensive: re-processing %d files that exceeded the size limit", len(recheck_ids))
            indexed_ids -= recheck_ids

        # In incremental mode, skip files whose mtime hasn't changed
        if indexed_mtimes:
            skip_count = 0
            for f in files:
                if f["id"] in indexed_ids and f["id"] in indexed_mtimes:
                    if f["modified_at"] == indexed_mtimes[f["id"]]:
                        indexed_ids.add(f["id"])  # keep it in the indexed set — skip it
                        skip_count += 1
                    else:
                        # mtime changed — remove from indexed_ids so it gets re-processed
                        indexed_ids.discard(f["id"])
            if skip_count:
                logger.info("Incremental: skipping %d unchanged files", skip_count)

        # Collect files that actually need processing (preserving order)
        new_files = [f for f in files if f["id"] not in indexed_ids]

        use_threads = _INDEX_WORKERS > 0 and len(new_files) > 4

        if use_threads:
            # ---- threaded pipeline -------------------------------------------
            # Workers do I/O and detection; main thread writes DB in-order.
            executor = ThreadPoolExecutor(max_workers=_INDEX_WORKERS)
            pending: OrderedDict[int, object] = OrderedDict()
            submit_idx = 0
            prog = 0
            skipped_count = 0

            # Lookup from file id -> index in new_files
            new_file_idx = {f["source"] + ":" + f["id"]: i for i, f in enumerate(new_files)}

            def fill():
                nonlocal submit_idx
                while submit_idx < len(new_files) and len(pending) < _INDEX_WORKERS * 2:
                    future = executor.submit(_process_single, new_files[submit_idx], scan_limit)
                    pending[submit_idx] = future
                    submit_idx += 1

            fill()

            for f in files:
                prog += 1
                # Update progress for API ~10x more often than log messages
                if prog % max(1, LOG_INTERVAL // 10) == 0:
                    _index_progress.update(current=prog, phase="indexing")
                if prog % LOG_INTERVAL == 0:
                    logger.info("Progress: %d/%d (%.0f%%), %d new indexed",
                                prog, total_files, 100.0 * prog / total_files,
                                indexed_count)

                if f["id"] in indexed_ids:
                    continue

                idx = new_file_idx[f["source"] + ":" + f["id"]]
                result = pending.pop(idx).result()

                if result.get("skipped"):
                    skipped_count += 1
                elif result.get("error"):
                    logger.warning("Failed to process %s: %s",
                                   result["id"], result["error"])
                else:
                    upsert_paste(
                        paste_id=result["id"],
                        filename=result["filename"],
                        source=result["source"],
                        content=result["content"],
                        content_type=result["content_type"],
                        size=result["size"],
                        has_passwords=result["has_passwords"],
                        has_secrets=result["has_secrets"],
                        secrets_detail=result["secrets_detail"],
                        modified_at=result["modified_at"],
                        fully_scanned=result.get("fully_scanned", 0),
                        commit=False,
                    )
                    indexed_count += 1
                    if indexed_count % 500 == 0:
                        get_conn().commit()

                fill()

            executor.shutdown(wait=True)
            get_conn().commit()
            if skipped_count:
                logger.info("Skipped %d files under 32 bytes", skipped_count)

        else:
            # ---- synchronous fallback (same logic as original) ----------------
            skipped_count = 0
            for idx, f in enumerate(files, 1):
                # Update progress for API ~10x more often than log messages
                if idx % max(1, LOG_INTERVAL // 10) == 0:
                    _index_progress.update(current=idx, phase="indexing")
                if idx % LOG_INTERVAL == 0:
                    logger.info("Progress: %d/%d (%.0f%%)",
                                idx, total_files, 100.0 * idx / total_files)

                if f["id"] in indexed_ids:
                    continue

                if f["size"] < 32:
                    skipped_count += 1
                    continue

                try:
                    with open(f["path"], "r", errors="replace") as fh:
                        content = fh.read(512000)
                except Exception as e:
                    logger.warning("Failed to read %s: %s", f["path"], e)
                    continue

                try:
                    content_type = detect_content_type(f["path"], content)
                    has_passwords, has_secrets, findings = scan_content(content, scan_limit=scan_limit)
                    fully_scanned = 1 if scan_limit == 0 or len(content) <= (200000 if scan_limit is None else scan_limit) else 0
                    upsert_paste(
                        paste_id=f["id"],
                        filename=f["filename"],
                        source=f["source"],
                        content=content,
                        content_type=content_type,
                        size=f["size"],
                        has_passwords=1 if has_passwords else 0,
                        has_secrets=1 if has_secrets else 0,
                        secrets_detail=findings,
                        modified_at=f["modified_at"],
                        fully_scanned=fully_scanned,
                        commit=False,
                    )
                    indexed_count += 1
                    if indexed_count % 500 == 0:
                        get_conn().commit()
                except Exception as e:
                    logger.warning("Failed to process %s: %s", f["path"], e)

            get_conn().commit()
            if skipped_count:
                logger.info("Skipped %d files under 32 bytes", skipped_count)

        # ---- deletion pass (unchanged) ---------------------------------------
        for pid in (indexed_ids - current_ids):
            delete_paste(pid, commit=False)
            deleted_count += 1
        get_conn().commit()

        _index_progress.update(phase="maintenance")

        if indexed_count > 0 or deleted_count > 0:
            try:
                from main import clear_cache
                clear_cache()
            except ImportError:
                pass

        logger.info("Complete: %d new, %d deleted, %d total",
                    indexed_count, deleted_count, len(current_ids))

        result = {"indexed": indexed_count, "deleted": deleted_count, "total": len(current_ids)}
        _last_reindex_result.update(result)
        _last_reindex_result["skipped"] = skipped_count
        _last_reindex_result["finished_at"] = _now_iso()
        _last_reindex_result["duration_seconds"] = round(time.monotonic() - started, 1)
        _last_reindex_result.pop("last_error", None)
        _last_reindex_result.pop("last_error_at", None)

        _warm_os_cache()

        return result
    except Exception as e:
        logger.exception("Indexing failed")
        _last_reindex_result["last_error"] = str(e) or e.__class__.__name__
        _last_reindex_result["last_error_at"] = _now_iso()
    finally:
        _index_progress.update(running=False, current=0, total=0, phase="")
        _index_lock.release()


scheduler = AsyncIOScheduler()
_REINDEX_INTERVAL = 300  # default, overridden by start_scheduler


def start_scheduler(interval_seconds=300):
    global _REINDEX_INTERVAL
    _REINDEX_INTERVAL = interval_seconds
    scheduler.add_job(
        index_all_pastes,
        "interval",
        seconds=interval_seconds,
        id="reindex",
        replace_existing=True,
        kwargs={"incremental": True},
    )
    scheduler.start()
    logger.info("Scheduler started: re-index every %d seconds", interval_seconds)


def get_scheduler_info():
    """Return scheduler status and next run time."""
    next_run = None
    job = scheduler.get_job("reindex")
    if job and job.next_run_time:
        next_run = job.next_run_time.isoformat()
    return {
        "interval_seconds": _REINDEX_INTERVAL,
        "next_run": next_run,
        "running": scheduler.running,
    }


def reschedule_interval(interval_seconds: int) -> None:
    """Change the auto-index interval. Minimum 1 hour (3600 seconds)."""
    global _REINDEX_INTERVAL
    if interval_seconds < 3600:
        raise ValueError("Interval must be at least 1 hour (3600 seconds)")
    _REINDEX_INTERVAL = interval_seconds
    job = scheduler.get_job("reindex")
    if job:
        scheduler.reschedule_job("reindex", trigger="interval", seconds=interval_seconds)
    else:
        scheduler.add_job(
            index_all_pastes,
            "interval",
            seconds=interval_seconds,
            id="reindex",
            replace_existing=True,
            kwargs={"incremental": True},
        )
    logger.info("Reindex interval changed to %d seconds", interval_seconds)