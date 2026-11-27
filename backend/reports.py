"""Persistent storage for LLM reports.

Reports are written under a data volume so they survive restarts:

    data/reports/<id>/
        meta.json        # metadata used for listing
        report.md        # single: the summary; batch: the aggregated report
        pastes/*.md      # batch only: one markdown file per analyzed paste

The module is filesystem-only (no DB schema changes). Writes are atomic
(temp file + os.replace) and pruning keeps the newest REPORT_ARCHIVE_MAX
reports.
"""

import io
import json
import logging
import os
import re
import shutil
import threading
import uuid
import zipfile
from datetime import datetime, timezone

logger = logging.getLogger("blacksignal")

DEFAULT_REPORTS_DIR = "/app/data/reports"
_DEV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "reports")

MAX_REPORTS = int(os.environ.get("REPORT_ARCHIVE_MAX", "100"))

_ID_RE = re.compile(r"^[0-9A-Za-z_-]+$")
_SAFE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

_lock = threading.Lock()


# ── paths ────────────────────────────────────────────────────────────────────

def base_dir() -> str:
    """Resolve (and create) the archive directory.

    REPORTS_DIR wins when set (tests, custom deployments). Otherwise prefer a
    sibling ``data/`` for local dev, falling back to the container path.
    """
    env = os.environ.get("REPORTS_DIR")
    if env:
        path = env
    else:
        dev_parent = os.path.dirname(_DEV_DIR)
        if os.path.isdir(dev_parent):
            path = _DEV_DIR
        else:
            path = DEFAULT_REPORTS_DIR
    os.makedirs(path, exist_ok=True)
    return path


def _report_dir(report_id: str) -> str | None:
    """Return the directory for a valid report id, or None. Blocks traversal."""
    if not report_id or not _ID_RE.match(report_id):
        return None
    path = os.path.join(base_dir(), report_id)
    # Defensive: ensure the resolved path is inside the archive root
    root = os.path.realpath(base_dir())
    if os.path.realpath(path) != os.path.join(root, report_id):
        return None
    return path


# ── helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id() -> str:
    now = datetime.now(timezone.utc)
    # Microsecond precision keeps ids sortable in creation order, even within
    # the same second (used by pruning and "newest first" listing).
    return f"{now.strftime('%Y%m%d-%H%M%S-%f')}-{uuid.uuid4().hex[:6]}"


def _write_atomic(path: str, data: str) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)


def _read_meta(dir_path: str) -> dict | None:
    try:
        with open(os.path.join(dir_path, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def safe_filename(base: str, used: set) -> str:
    """Turn an arbitrary label into a unique, filesystem-safe ``*.md`` name.

    Idempotent for names that already end in ``.md`` so callers can pass either
    bare names or pre-built ``*.md`` filenames.
    """
    safe = _SAFE_RE.sub("_", base or "")
    safe = " ".join(safe.split()).strip(". ")
    if not safe:
        safe = "paste"
    if len(safe) > 120:
        safe = safe[:120]
    stem = safe[:-3] if safe.lower().endswith(".md") else safe
    candidate = f"{stem}.md"
    n = 2
    while candidate.lower() in used:
        candidate = f"{stem}-{n}.md"
        n += 1
    used.add(candidate.lower())
    return candidate


# ── pruning ──────────────────────────────────────────────────────────────────

def _prune() -> None:
    """Keep only the newest MAX_REPORTS report directories."""
    if MAX_REPORTS <= 0:
        return
    base = base_dir()
    with _lock:
        try:
            names = [
                n for n in os.listdir(base)
                if _ID_RE.match(n) and os.path.isdir(os.path.join(base, n))
            ]
        except OSError:
            return
        names.sort()  # ids are timestamp-prefixed, so lexicographic == chronological
        excess = len(names) - MAX_REPORTS
        for name in names[:max(0, excess)]:
            shutil.rmtree(os.path.join(base, name), ignore_errors=True)


# ── save ─────────────────────────────────────────────────────────────────────

def save_single(paste_meta: dict, markdown: str, model: str | None = None,
                analysis: dict | None = None) -> str:
    """Persist a single-paste analysis. Returns the new report id."""
    report_id = _new_id()
    path = os.path.join(base_dir(), report_id)
    os.makedirs(path, exist_ok=True)

    source = paste_meta.get("source", "?")
    filename = paste_meta.get("filename")
    paste_id = paste_meta.get("paste_id")
    if filename:
        title = f"{source}:{filename}"
    else:
        title = paste_id or f"{source}:paste"
    meta = {
        "id": report_id,
        "type": "single",
        "created_at": _now_iso(),
        "title": title,
        "source": source,
        "filename": filename,
        "paste_id": paste_id,
        "model": model,
    }
    risk = analysis.get("risk") if isinstance(analysis, dict) else None
    if isinstance(risk, dict):
        meta["risk_level"] = risk.get("level")
        meta["risk_score"] = risk.get("score")
    _write_atomic(os.path.join(path, "meta.json"), json.dumps(meta, indent=2))
    _write_atomic(os.path.join(path, "report.md"), markdown)
    if analysis is not None:
        _write_atomic(os.path.join(path, "analysis.json"), json.dumps(analysis, indent=2))
    _prune()
    return report_id


def save_batch(meta_fields: dict, markdown: str,
               per_paste_files: list[dict], model: str | None = None,
               pastes: list[dict] | None = None,
               analysis: dict | None = None) -> str:
    """Persist a multi-paste report plus its per-paste analyses.

    ``pastes`` is the structured list of pastes included in the report
    (source, id, filename, …); it is written to ``pastes.json`` so the exact
    input set is machine-readable. ``analysis`` is the aggregated structured
    result and is stored as ``analysis.json``.
    """
    report_id = _new_id()
    path = os.path.join(base_dir(), report_id)
    pastes_dir = os.path.join(path, "pastes")
    os.makedirs(pastes_dir, exist_ok=True)

    paste_count = len(pastes) if pastes is not None else len(per_paste_files)
    meta = {
        "id": report_id,
        "type": "batch",
        "created_at": _now_iso(),
        "title": f"Report — {paste_count} paste{'s' if paste_count != 1 else ''}",
        "paste_count": paste_count,
        "filters": meta_fields.get("filters"),
        "model": model,
    }
    narrative = analysis.get("narrative") if isinstance(analysis, dict) else None
    risk = narrative.get("risk") if isinstance(narrative, dict) else None
    if isinstance(risk, dict):
        meta["risk_level"] = risk.get("level")
        meta["risk_score"] = risk.get("score")
    _write_atomic(os.path.join(path, "meta.json"), json.dumps(meta, indent=2))
    _write_atomic(os.path.join(path, "report.md"), markdown)
    if pastes is not None:
        _write_atomic(os.path.join(path, "pastes.json"), json.dumps(pastes, indent=2))
    if analysis is not None:
        _write_atomic(os.path.join(path, "analysis.json"), json.dumps(analysis, indent=2))

    used: set = set()
    for f in per_paste_files:
        name = safe_filename(f.get("filename", "paste"), used)
        _write_atomic(os.path.join(pastes_dir, name), f.get("content", ""))

    _prune()
    return report_id


# ── read / list ──────────────────────────────────────────────────────────────

def list_reports() -> list[dict]:
    """Return report metadata, newest first."""
    base = base_dir()
    items: list[dict] = []
    try:
        names = os.listdir(base)
    except OSError:
        return []
    for name in names:
        if not _ID_RE.match(name):
            continue
        d = os.path.join(base, name)
        if not os.path.isdir(d):
            continue
        meta = _read_meta(d)
        if meta:
            items.append(meta)
    items.sort(key=lambda m: (m.get("created_at") or "", m.get("id") or ""), reverse=True)
    return items


def get_report(report_id: str) -> dict | None:
    """Return ``{meta, markdown}`` for a report, or None."""
    d = _report_dir(report_id)
    if not d or not os.path.isdir(d):
        return None
    meta = _read_meta(d)
    if not meta:
        return None
    try:
        with open(os.path.join(d, "report.md"), encoding="utf-8") as f:
            markdown = f.read()
    except OSError:
        markdown = ""

    analysis = None
    try:
        with open(os.path.join(d, "analysis.json"), encoding="utf-8") as f:
            analysis = json.load(f)
    except (OSError, json.JSONDecodeError):
        analysis = None

    return {"meta": meta, "markdown": markdown, "analysis": analysis}


def delete_report(report_id: str) -> bool:
    d = _report_dir(report_id)
    if not d or not os.path.isdir(d):
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


# ── download ─────────────────────────────────────────────────────────────────

def build_zip(report_id: str) -> bytes | None:
    """Build a ZIP bundle for a batch report (report.md + pastes/*.md)."""
    d = _report_dir(report_id)
    if not d or not os.path.isdir(d):
        return None
    meta = _read_meta(d)
    if not meta:
        return None
    try:
        with open(os.path.join(d, "report.md"), encoding="utf-8") as f:
            report = f.read()
    except OSError:
        report = ""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.md", report)
        meta_json = json.dumps(meta, indent=2)
        zf.writestr("meta.json", meta_json)
        # Structured list of the exact pastes used (source + id, …)
        pastes_json_path = os.path.join(d, "pastes.json")
        if os.path.isfile(pastes_json_path):
            with open(pastes_json_path, encoding="utf-8", errors="replace") as f:
                zf.writestr("pastes.json", f.read())
        analysis_json_path = os.path.join(d, "analysis.json")
        if os.path.isfile(analysis_json_path):
            with open(analysis_json_path, encoding="utf-8", errors="replace") as f:
                zf.writestr("analysis.json", f.read())
        pastes_dir = os.path.join(d, "pastes")
        pastes = []
        if os.path.isdir(pastes_dir):
            for name in sorted(os.listdir(pastes_dir)):
                fp = os.path.join(pastes_dir, name)
                if os.path.isfile(fp):
                    pastes.append(name)
        readme = (
            "# BlackSignal — LLM Report Bundle\n\n"
            "- `report.md` — the aggregated security report.\n"
            "- `pastes/` — one markdown analysis per analyzed paste.\n"
            "- `pastes.json` — source, ID and metadata for every paste included.\n"
            "- `analysis.json` — structured findings, correlations and narrative.\n"
            "- `meta.json` — report metadata.\n\n"
            f"Created: {meta.get('created_at', '?')}\n"
            f"Pastes bundled: {len(pastes)}\n"
        )
        zf.writestr("README.md", readme)
        for name in pastes:
            with open(os.path.join(pastes_dir, name), encoding="utf-8", errors="replace") as f:
                zf.writestr(f"pastes/{name}", f.read())

    return buf.getvalue()
