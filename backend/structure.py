"""Deterministic structural hints for relationship-aware analysis.

The LLM sees the full paste, but explicit hints help it link values that are
only sensitive together (e.g. DB_USER / DB_PASS / DB_HOST in one block).
This module is intentionally dependency-free and cheap.
"""

import re

MAX_GROUPS = 25
MAX_VALUE = 60

_KEYVAL = re.compile(
    r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.-]{0,60})\s*[:=]\s*(.+?)\s*$'
)
_PEM = re.compile(r'-----BEGIN\s+([A-Z ]*?)PRIVATE KEY-----', re.I)
_JWT = re.compile(r'\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}')
_URL_CRED = re.compile(r'\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@', re.I)
_SECRETISH = re.compile(r'pass|pwd|secret|token|key|credential|auth', re.I)


def _short(value: str, limit: int = MAX_VALUE) -> str:
    value = " ".join(value.split())
    return value[:limit] + ("..." if len(value) > limit else "")


def hint_block(content: str) -> str:
    """Return a compact hint block, or an empty string if nothing is found."""
    if not content:
        return ""
    lines = content.split("\n")

    groups: dict[str, list[tuple[int, str, str]]] = {}
    for line_no, line in enumerate(lines, 1):
        m = _KEYVAL.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if len(value) < 2 or len(value) > 300:
            continue
        prefix = re.split(r"[_.-]", key)[0].upper() or key.upper()
        groups.setdefault(prefix, []).append((line_no, key, value))

    hints: list[str] = []
    for prefix, items in groups.items():
        if len(items) < 2 and not any(_SECRETISH.search(k) for _, k, _ in items):
            continue
        parts = []
        for line_no, key, value in items[:8]:
            if _SECRETISH.search(key) or len(items) <= 4:
                parts.append(f"{key} (line {line_no})={_short(value)}")
            else:
                parts.append(f"{key} (line {line_no})")
        hints.append(f"- related keys `{prefix}*`: " + ", ".join(parts))
        if len(hints) >= MAX_GROUPS:
            break

    seen: set[str] = set()
    for line_no, line in enumerate(lines, 1):
        if _PEM.search(line) and "pem" not in seen:
            hints.append(f"- private key block starting at line {line_no}")
            seen.add("pem")
        if _JWT.search(line) and "jwt" not in seen:
            hints.append(f"- JWT present at line {line_no}")
            seen.add("jwt")
        if _URL_CRED.search(line) and "urlcred" not in seen:
            hints.append(f"- URL with embedded credentials at line {line_no}")
            seen.add("urlcred")
        if len(hints) >= MAX_GROUPS + 10:
            break

    if not hints:
        return ""
    return (
        "\nSTRUCTURAL HINTS (deterministic; use these to link values across lines):\n"
        + "\n".join(hints)
        + "\n"
    )
