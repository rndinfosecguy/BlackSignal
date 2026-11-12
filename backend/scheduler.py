import os
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from indexer import walk_pastes, detect_content_type
from database import upsert_paste, get_indexed_ids, delete_paste, get_conn
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
_last_reindex_result = {}


def get_last_reindex_result():
    return dict(_last_reindex_result)


def get_index_progress():
    return dict(_index_progress)


def set_index_running(running: bool, phase: str = ""):
    """Set the running state and phase of the indexer.
    Used by purge to mark itself running before the long clear_all_data() call."""
    _index_progress.update(running=running, current=0, total=0, phase=phase)


def _warm_os_cache():
    """Run common SELECT queries to pull database pages into the OS filesystem cache.
    Called at the end of every index run so that first-user interactions
    (source filter, stats, type distribution) serve instantly."""
    import time
    try:
        conn = get_conn()
        logger.info("Warming OS cache with common queries…")
        conn.execute("SELECT COUNT(*) FROM pastes").fetchone()
        conn.execute("SELECT COUNT(*) FROM pastes WHERE has_secrets = 1").fetchone()
        conn.execute("SELECT COUNT(*) FROM pastes WHERE has_passwords = 1").fetchone()
        conn.execute("SELECT source, COUNT(*) AS cnt FROM pastes GROUP BY source ORDER BY cnt DESC").fetchall()
        conn.execute("SELECT content_type, COUNT(*) AS cnt FROM pastes GROUP BY content_type ORDER BY cnt DESC").fetchall()
        conn.execute("SELECT secret_types, COUNT(*) AS cnt FROM pastes WHERE secret_types != '' GROUP BY secret_types ORDER BY cnt DESC").fetchall()
        sources = conn.execute("SELECT DISTINCT source FROM pastes").fetchall()
        for row in sources:
            conn.execute("SELECT COUNT(*) FROM pastes WHERE source = ?", (row["source"],)).fetchone()
        conn.execute("SELECT rowid FROM pastes_fts WHERE pastes_fts MATCH '\"\"' LIMIT 1").fetchall()
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
        }
    except Exception as e:
        return {"id": f["id"], "error": str(e)}


def index_all_pastes(scan_limit=None):
    """Index all paste files. 
    scan_limit — max chars to scan per file (None = default 200K, 0 = unlimited)."""
    if not _index_lock.acquire(blocking=False):
        logger.info("Index already in progress, skipping")
        return

    try:
        _index_progress.update(running=True, current=0, total=0, phase="scanning")
        files = walk_pastes()
        indexed_ids = get_indexed_ids()
        current_ids = set()
        indexed_count = 0
        deleted_count = 0
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
                if prog % LOG_INTERVAL == 0:
                    _index_progress.update(current=prog, phase="indexing")
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
                if idx % LOG_INTERVAL == 0:
                    _index_progress.update(current=idx, phase="indexing")
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

        _warm_os_cache()

        return result
    except Exception:
        logger.exception("Indexing failed")
    finally:
        _index_progress.update(running=False, current=0, total=0, phase="")
        _index_lock.release()


scheduler = AsyncIOScheduler()


def start_scheduler(interval_seconds=300):
    scheduler.add_job(
        index_all_pastes,
        "interval",
        seconds=interval_seconds,
        id="reindex",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: re-index every %d seconds", interval_seconds)