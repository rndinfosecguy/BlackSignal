import os
import logging
import threading

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from indexer import walk_pastes, detect_content_type
from database import upsert_paste, get_indexed_ids, delete_paste, get_conn
from detector import scan_content

logger = logging.getLogger("blacksignal")

_index_lock = threading.Lock()

_index_progress = {
    "running": False,
    "current": 0,
    "total": 0,
    "phase": "",
}


def get_index_progress():
    return dict(_index_progress)


def index_all_pastes():
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

        for idx, f in enumerate(files, 1):
            current_ids.add(f["id"])

            if idx % LOG_INTERVAL == 0:
                _index_progress.update(current=idx, phase="indexing")
                logger.info("Progress: %d/%d (%.0f%%)", idx, total_files, 100.0 * idx / total_files)

            if f["id"] in indexed_ids:
                continue

            try:
                with open(f["path"], "r", errors="replace") as fh:
                    content = fh.read(512000)
            except Exception as e:
                logger.warning("Failed to read %s: %s", f["path"], e)
                continue

            try:
                content_type = detect_content_type(f["path"], content)
                has_passwords, has_secrets, findings = scan_content(content)

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
                if indexed_count % 100 == 0:
                    get_conn().commit()
            except Exception as e:
                logger.warning("Failed to process %s: %s", f["path"], e)

        get_conn().commit()

        for pid in (indexed_ids - current_ids):
            delete_paste(pid, commit=False)
            deleted_count += 1
        get_conn().commit()

        _index_progress.update(phase="maintenance")

        if indexed_count > 0 or deleted_count > 0:
            # FTS automerge=1 handles segment merging; explicit 'optimize' can
            # hang for a long time on large tables (EBS/overlay2 I/O stalls).
            try:
                from main import clear_cache
                clear_cache()
            except ImportError:
                pass

        logger.info("Complete: %d new, %d deleted, %d total",
                    indexed_count, deleted_count, len(current_ids))

        return {"indexed": indexed_count, "deleted": deleted_count, "total": len(current_ids)}
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