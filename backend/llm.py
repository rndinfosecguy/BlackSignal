"""OpenRouter LLM integration.

Configuration (API key) lives in ``data/settings.json`` via the settings
module. Analysis is requested as structured JSON (see ``analysis.py``) and
rendered deterministically (see ``render.py``) so reports keep a stable shape.
"""

import json
import logging
import threading
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import analysis
import render
import settings
import structure

logger = logging.getLogger("blacksignal")

OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta-llama/llama-3.1-8b-instruct"


# Report progress state (used by /api/llm/report-status polling)
_report_progress_lock = threading.Lock()
_report_progress = {
    "running": False,
    "current": 0,
    "total": 0,
    "phase": "",
    "final_report": None,
    "error": None,
    "cancelled": False,
    "_per_paste_files": None,
}

# Keys that must never be serialized to the status endpoint / clients.
_INTERNAL_REPORT_KEYS = ("_per_paste_files",)


def get_report_progress() -> dict:
    with _report_progress_lock:
        return {k: v for k, v in _report_progress.items() if k not in _INTERNAL_REPORT_KEYS}


def get_report_files() -> list[dict] | None:
    """Return the per-paste report files for the ZIP download, if available."""
    with _report_progress_lock:
        files = _report_progress.get("_per_paste_files")
        return list(files) if files else None


def reset_report_progress() -> None:
    with _report_progress_lock:
        _report_progress.update(running=False, current=0, total=0, phase="", final_report=None, error=None, cancelled=False, _per_paste_files=None)


def _set_report_running(total: int) -> None:
    with _report_progress_lock:
        _report_progress.update(running=True, current=0, total=total, phase="analyzing", final_report=None, error=None, cancelled=False, _per_paste_files=None)


def begin_report() -> bool:
    """Atomically claim the report slot before doing any expensive work.

    Returns False if a report is already running. This closes the check-then-act
    race in the HTTP handler, which spends time counting/fetching before it
    spawns the worker thread.
    """
    with _report_progress_lock:
        if _report_progress["running"]:
            return False
        _report_progress.update(
            running=True, current=0, total=0, phase="preparing",
            final_report=None, error=None, cancelled=False, _per_paste_files=None,
        )
        return True


def _set_report_progress(current: int, phase: str = "") -> None:
    with _report_progress_lock:
        _report_progress["current"] = current
        if phase:
            _report_progress["phase"] = phase


def _set_report_done(report: str, per_paste_files: list[dict] | None = None) -> None:
    with _report_progress_lock:
        _report_progress.update(
            running=False,
            final_report=report,
            phase="complete",
            current=_report_progress["total"],
            _per_paste_files=per_paste_files,
        )


def _set_report_error(error: str) -> None:
    with _report_progress_lock:
        _report_progress.update(running=False, phase="error", error=error)


def cancel_report() -> None:
    """Signal the report generation to stop. Sets cancelled flag and clears running state."""
    with _report_progress_lock:
        _report_progress.update(running=False, phase="cancelled", cancelled=True, final_report=None, _per_paste_files=None)


def is_report_cancelled() -> bool:
    """Check if the user has requested cancellation."""
    with _report_progress_lock:
        return _report_progress.get("cancelled", False)


def is_configured() -> bool:
    """Check whether an OpenRouter API key is configured."""
    return bool(settings.get_openrouter_key())


def save_key(key: str) -> None:
    """Store the OpenRouter API key in ``data/settings.json``."""
    settings.set_openrouter_key(key)


def remove_key() -> None:
    """Remove the stored OpenRouter API key."""
    settings.clear_openrouter_key()


def get_key_preview() -> str:
    """Return a masked preview of the configured key, or empty string."""
    return settings.get_key_preview()


def _call_llm(messages: list, temperature: float = 0.3,
              max_tokens: int = 2000, json_mode: bool = False) -> str:
    """Send a chat request to OpenRouter and return the response text.

    Raises:
        ValueError: if OpenRouter is not configured.
        RuntimeError: if the API call fails.
    """
    key = settings.get_openrouter_key()
    if not key:
        raise ValueError("OpenRouter not configured - add a key in the Config tab")

    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    body = json.dumps(payload).encode("utf-8")

    req = Request(
        OPENROUTER_API,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:9090",
            "X-Title": "BlackSignal",
        },
    )

    try:
        resp = urlopen(req, timeout=60)
        data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        raise RuntimeError(
            f"OpenRouter API error (HTTP {e.code}): {detail or e.reason}"
        ) from e
    except URLError as e:
        raise RuntimeError(f"OpenRouter connection failed: {e.reason}") from e
    except OSError as e:
        raise RuntimeError(f"OpenRouter request failed: {e}") from e

    try:
        choice = data["choices"][0]["message"]
        text = (choice.get("content") or choice.get("reasoning") or "").strip()
        if not text:
            text = "(no response content)"
        return text
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(
            f"Unexpected OpenRouter response format: {e}"
        ) from e


def _fallback_markdown(raw: str, title: str | None = None) -> str:
    """Render a stored report when the model failed to produce valid JSON."""
    out = ["# BlackSignal — LLM Analysis", ""]
    if title:
        out += [f"**Paste**: `{title}`", ""]
    out += [
        "## Unstructured Analysis",
        "*The model did not return valid structured output; the raw response is shown below.*",
        "",
        "```text",
        (raw or "").strip()[:20000],
        "```",
        "",
        render.DATA_LIMIT_NOTE,
        "",
    ]
    return "\n".join(out)


def summarize_paste(paste_id: str, content: str, title: str | None = None) -> dict:
    """Analyse one paste and return ``{structured, analysis, markdown}``.

    Raises:
        ValueError: if OpenRouter is not configured.
        RuntimeError: if the API call fails.
    """
    truncated = content[:200000] if content else ""
    hints = structure.hint_block(truncated)
    messages = analysis.build_single_messages(truncated, hints)

    raw = _call_llm(messages, temperature=0.1, max_tokens=3000, json_mode=True)
    obj = analysis.extract_json(raw)

    if obj is None:
        logger.warning("Malformed JSON from model for %s; retrying once", paste_id)
        repaired = _call_llm(
            messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": analysis.REPAIR_PROMPT},
            ],
            temperature=0.1, max_tokens=3000, json_mode=True,
        )
        obj = analysis.extract_json(repaired)
        if obj is None:
            logger.error("Model returned invalid JSON twice for %s; storing unstructured output", paste_id)
            return {
                "structured": False,
                "analysis": None,
                "markdown": _fallback_markdown(repaired or raw, title),
            }

    normalized = analysis.normalize_analysis(obj)
    normalized = analysis.correct_evidence_lines(normalized, truncated)
    return {
        "structured": True,
        "analysis": normalized,
        "markdown": render.render_single(normalized, title),
    }


def summarize_batch(compact: str) -> dict:
    """Generate the batch narrative (summary/risk/highlights) from aggregated JSON."""
    messages = analysis.build_batch_messages(compact)
    raw = _call_llm(messages, temperature=0.1, max_tokens=1500, json_mode=True)
    obj = analysis.extract_json(raw)

    if obj is None:
        repaired = _call_llm(
            messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": analysis.BATCH_REPAIR_PROMPT},
            ],
            temperature=0.1, max_tokens=1500, json_mode=True,
        )
        obj = analysis.extract_json(repaired)
        if obj is None:
            # Last resort: keep the run useful with a plain summary.
            return {
                "summary": (repaired or raw or "").strip()[:2000] or "No summary generated.",
                "highlights": [],
            }

    return analysis.normalize_batch(obj)