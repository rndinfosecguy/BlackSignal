"""OpenRouter LLM integration for paste summarization.

Reads configuration from ``openrouter.json`` in the data directory.
Exposes ``is_configured()`` and ``summarize_paste()``.
"""

import json
import logging
import os
import threading
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger("blacksignal")

OPENROUTER_CONFIG_PATH = os.environ.get(
    "OPENROUTER_CONFIG_PATH",
    "/app/data/openrouter.json",
)

# Dev fallback: look for openrouter.json next to the backend dir
CONFIG_DEV_FALLBACK = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "data",
    "openrouter.json",
)

OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta-llama/llama-3.1-8b-instruct"

SYSTEM_PROMPT = """You are a security analyst analyzing paste content. Provide a structured markdown summary with these sections:

## Summary
Brief 2-3 sentence overview of what the content contains.

## Sensitive Data Found

### Technical / Infrastructure
List any of the following:
- Credentials: passwords, API keys, tokens (AWS, GitHub, Stripe, Slack, Discord, JWT, etc.), private keys (SSH, PGP, TLS), connection strings, database URLs, admin login pairs
- Infrastructure exposure: internal hostnames, IP addresses, internal URLs (Jenkins, Grafana, Kibana, Prometheus, internal DNS names), cloud metadata endpoints, debug endpoints, environment variable dumps, configuration files exposing secrets
- Code-level secrets: hardcoded secrets in source code, .env files, docker-compose files, CI/CD pipeline tokens, npm/PyPI/pip tokens, cloud provider credentials
- Network data: internal IP ranges, VPN configurations, firewall rules, certificates

### Personal / PII
List any of the following:
- Names, email addresses, phone numbers, home addresses
- Government IDs: Social Security numbers, passport numbers, driver's license numbers, national ID numbers
- Financial data: credit card numbers, bank account details, crypto wallet addresses (BTC, ETH)
- Biographical data: dates of birth combined with names, medical information
- Account identifiers: usernames, session tokens, cookies, device fingerprints

Format each finding as a bullet list with the type/category and the value (or partial/masked value). Group related findings. If nothing sensitive is found in a sub-section, write "None detected."

## Risk Assessment
Rate the overall risk as Low / Medium / High and explain why in 1-2 sentences. Consider both the severity of exposed data and the potential attack surface."""

REPORT_PROMPT = """You are a security analyst. Below are individual analyses of multiple paste files from a paste monitoring system. Each entry includes the paste source, ID, type, size, BlackSignal's detection results, and an LLM analysis.

Synthesize them into an overall security report with these sections:

## Executive Summary
Brief 2-4 sentence overview of the overall security posture of the analyzed pastes.

## Most Critical Findings
List the most severe findings, ordered by severity, with brief context.

## Sensitive Data Overview by Category
Summarize types of sensitive data found and how many pastes were affected.

## Top Sources of Risk
Which paste sources contained the most or most severe sensitive data.

Below are the individual analyses:"""


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


def _find_config() -> str | None:
    """Return the path to an existing openrouter.json, or None.

    If OPENROUTER_CONFIG_PATH is explicitly set in the environment, use it
    exclusively. Otherwise fall back to known locations. This ensures tests
    can isolate via env var without interference from real config files.
    """
    env_val = os.environ.get("OPENROUTER_CONFIG_PATH")
    if env_val is not None:
        # Explicitly set — use it even if it doesn't exist (caller gets None)
        if os.path.exists(env_val):
            return env_val
        return None

    # No explicit env var — try fallback paths
    if os.path.exists(CONFIG_DEV_FALLBACK):
        return CONFIG_DEV_FALLBACK
    cwd = os.path.join(os.getcwd(), "data", "openrouter.json")
    if os.path.exists(cwd):
        return cwd
    return None


def _load_config() -> dict | None:
    """Load the OpenRouter config file. Returns None on any failure."""
    path = _find_config()
    if not path:
        return None
    try:
        with open(path) as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            logger.warning("openrouter.json is not a JSON object")
            return None
        return cfg
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read openrouter.json: %s", e)
        return None


def is_configured() -> bool:
    """Check whether an OpenRouter API key is available in the config."""
    cfg = _load_config()
    if not cfg:
        return False
    key = cfg.get("openrouter_key", "").strip()
    return bool(key)


def _get_write_path() -> str:
    """Return the path where openrouter.json should be saved.

    Uses the env var if set, otherwise the dev fallback, otherwise the
    CWD-based path. Ensures the parent directory exists.
    """
    env_val = os.environ.get("OPENROUTER_CONFIG_PATH")
    if env_val is not None:
        path = env_val
    elif os.path.exists(CONFIG_DEV_FALLBACK):
        path = CONFIG_DEV_FALLBACK
    else:
        path = os.path.join(os.getcwd(), "data", "openrouter.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def save_key(key: str) -> None:
    """Save an OpenRouter API key to the config file.

    Clears any cached config state so the next call to is_configured()
    reflects the new value.
    """
    path = _get_write_path()
    with open(path, "w") as f:
        json.dump({"openrouter_key": key.strip()}, f)
    logger.info("OpenRouter config saved to %s", path)


def remove_key() -> None:
    """Remove the OpenRouter API key from the config file."""
    path = _get_write_path()
    with open(path, "w") as f:
        json.dump({"openrouter_key": ""}, f)
    logger.info("OpenRouter key removed from %s", path)


def get_key_preview() -> str:
    """Return a masked preview of the configured key, or empty string."""
    cfg = _load_config()
    if not cfg:
        return ""
    key = cfg.get("openrouter_key", "").strip()
    if not key or len(key) < 8:
        return ""
    prefix = key[:8]
    suffix = key[-4:]
    return f"{prefix}...{suffix}"


def _call_llm(messages: list) -> str:
    """Send a chat request to OpenRouter and return the response text.

    Raises:
        ValueError: if OpenRouter is not configured.
        RuntimeError: if the API call fails.
    """
    cfg = _load_config()
    if not cfg:
        raise ValueError("OpenRouter not configured - create data/openrouter.json")

    key = cfg.get("openrouter_key", "").strip()
    if not key:
        raise ValueError("OpenRouter not configured - create data/openrouter.json")

    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "max_tokens": 2000,
        "temperature": 0.3,
    }).encode("utf-8")

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


def summarize_paste(paste_id: str, content: str) -> str:
    """Send paste content to OpenRouter and return the LLM's markdown summary.

    Raises:
        ValueError: if OpenRouter is not configured.
        RuntimeError: if the API call fails.
    """
    # Truncate to 200K chars (matching the frontend/backend scan limit)
    truncated = content[:200000] if content else ""
    text = _call_llm([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"PASTE CONTENT:\n\n{truncated}"},
    ])
    # Append a data-limitation note so the user knows only first 200K chars were analyzed
    text += "\n\n---\n\n*Note: Only the first 200 KB of content are analyzed by the LLM. The full paste may contain additional data beyond this limit if it is larger.*"
    return text