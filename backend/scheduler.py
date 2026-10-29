import os
import logging
import threading

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from indexer import walk_pastes, detect_content_type
from database import upsert_paste, get_indexed_ids, delete_paste, get_conn
from detector import scan_content

logger = logging.getLogger("blacksignal")

RAW_PASTES_DIR = os.environ.get("RAW_PASTES_DIR", "/app/raw_pastes")

_index_lock = threading.Lock()


def index_all_pastes():
    if not _index_lock.acquire(blocking=False):
        logger.info("Index already in progress, skipping")
        return

    try:
        files = walk_pastes()
        indexed_ids = get_indexed_ids()
        current_ids = set()
        indexed_count = 0
        deleted_count = 0
        total_files = len(files)

        logger.info("Starting full index: %d files to process", total_files)

        for idx, f in enumerate(files, 1):
            current_ids.add(f["id"])
            if f["id"] in indexed_ids:
                continue

            if idx % 100 == 0:
                logger.info("Index progress: %d/%d (%.0f%%)", idx, total_files, 100.0 * idx / total_files)

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
                logger.warning("Failed to index %s: %s", f["path"], e)

        get_conn().commit()

        for pid in (indexed_ids - current_ids):
            delete_paste(pid, commit=False)
            deleted_count += 1
        get_conn().commit()

        logger.info("Index complete: %d new, %d deleted, %d total",
                    indexed_count, deleted_count, len(current_ids))
        return {"indexed": indexed_count, "deleted": deleted_count, "total": len(current_ids)}
    except Exception:
        logger.exception("Indexing failed with unexpected error")
    finally:
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