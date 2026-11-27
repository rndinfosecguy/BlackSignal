"""Deterministic markdown rendering for structured LLM analyses.

Layout and wording of the fixed sections are produced here, not by the model,
so reports have the same structure on every run.
"""

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

RISK_SCALE_NOTE = "Risk scale: 0-24 Low · 25-49 Medium · 50-74 High · 75-100 Critical"

DATA_LIMIT_NOTE = (
    "*Note: Only the first 200 KB of content are analyzed by the LLM. "
    "The full paste may contain additional data beyond this limit if it is larger.*"
)


def _band_range(level: str) -> str:
    ranges = {"low": "0-24", "medium": "25-49", "high": "50-74", "critical": "75-100"}
    return ranges.get(str(level or "").lower(), "")


def _risk_line(risk: dict) -> str:
    level = str(risk.get("level") or "").lower()
    score = risk.get("score")
    rationale = risk.get("rationale") or ""
    if not level or score is None:
        head = "**No rating available**"
    else:
        head = f"**{level.capitalize()}** - score **{score}/100** ({_band_range(level)})"
    return head + (f". {rationale}" if rationale else ".")


def _cell(value) -> str:
    text = " ".join(str(value or "").split())
    text = text.replace("|", "\\|")
    if len(text) > 160:
        text = text[:157] + "..."
    return text


def _table(headers: list[str], rows: list[list]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return "\n".join(lines)


def _sev(severity: str) -> str:
    return str(severity or "medium").capitalize()


def _lines_of(finding: dict) -> str:
    lines = [str(e.get("line")) for e in finding.get("evidence", []) if e.get("line")]
    return ", ".join(lines) if lines else "—"


def _entities(finding: dict) -> str:
    parts = [f"{e.get('type', 'other')}=`{_cell(e.get('value'))}`" for e in finding.get("entities", [])]
    return ", ".join(parts) if parts else "—"


def _sorted_findings(findings: list[dict]) -> list[dict]:
    return sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER.get(f.get("severity", "medium"), 9), f.get("title", "").lower()),
    )


def render_single(analysis: dict, title: str | None = None) -> str:
    findings = analysis.get("findings") or []
    ordered = _sorted_findings(findings)
    risk = analysis.get("risk") or {}

    out: list[str] = ["# BlackSignal — LLM Analysis", ""]
    if title:
        out.append(f"**Paste**: `{_cell(title)}`")
        out.append("")

    out += ["## Summary", analysis.get("summary") or "No summary provided.", ""]

    out += [
        "## Risk Assessment",
        _risk_line(risk),
        "",
        RISK_SCALE_NOTE,
        "",
    ]

    out += ["## Findings", ""]
    if not ordered:
        out += ["No sensitive data detected.", ""]
    else:
        for i, f in enumerate(ordered, 1):
            out.append(f"### {i}. [{_sev(f.get('severity'))}] {f.get('title', 'Sensitive finding')}")
            out.append("")
            out.append(f"- **Kind / Category**: {f.get('kind', 'standalone')} / {f.get('category', 'other')}")
            if f.get("confidence") is not None:
                out.append(f"- **Confidence**: {float(f.get('confidence', 0)):.2f}")
            evidence = f.get("evidence") or []
            if evidence:
                rendered = "; ".join(
                    f"line {e.get('line')}: `{_cell(e.get('excerpt'))}`" for e in evidence
                )
                out.append(f"- **Evidence**: {rendered}")
            out.append(f"- **Entities**: {_entities(f)}")
            if f.get("relationship"):
                out.append(f"- **Relationship**: {f['relationship']}")
            if f.get("reasoning"):
                out.append(f"- **Reasoning**: {f['reasoning']}")
            out.append("")

    out += ["## Detailed Findings", ""]
    if ordered:
        rows = [
            [i, _sev(f.get("severity")), f.get("kind", "standalone"), f.get("category", "other"),
             f.get("title", ""), _lines_of(f)]
            for i, f in enumerate(ordered, 1)
        ]
        out.append(_table(["#", "Severity", "Kind", "Category", "Finding", "Lines"], rows))
    else:
        out.append("No findings.")
    out.append("")

    categories = analysis.get("categories") or []
    if categories:
        out += ["## Categories", ""]
        out.append(_table(["Category", "Count"], [[c.get("name"), c.get("count")] for c in categories]))
        out.append("")

    out += ["---", "", DATA_LIMIT_NOTE, ""]
    return "\n".join(out)


def render_batch(
    narrative: dict,
    findings: list[dict],
    correlations: list[dict],
    pastes: list[dict],
    filters: dict | None = None,
    total_analyzed: int | None = None,
    regex_findings_markdown: str | None = None,
) -> str:
    ordered = _sorted_findings(findings)
    risk = (narrative or {}).get("risk") or {}
    total = total_analyzed if total_analyzed is not None else len(pastes)

    out: list[str] = ["# BlackSignal — LLM Security Report", ""]
    out.append(f"**Pastes analyzed**: {total}")
    if filters:
        fparts = []
        for key in ("q", "source", "content_type", "has_secrets", "secret_type", "date_from", "date_to"):
            value = filters.get(key)
            if value:
                fparts.append(f"{key}={value}")
        if fparts:
            out.append(f"**Filters**: {', '.join(fparts)}")
    out += ["", "---", ""]

    out += ["## Executive Summary", (narrative or {}).get("summary") or "No summary provided.", ""]

    out += [
        "## Risk Assessment",
        _risk_line(risk),
        "",
        RISK_SCALE_NOTE,
        "",
    ]

    highlights = (narrative or {}).get("highlights") or []
    if highlights:
        out += ["## Key Highlights", ""]
        out += [f"- {h}" for h in highlights]
        out.append("")

    out += ["## Correlated Findings", ""]
    if correlations:
        for c in correlations:
            where = ", ".join(
                f"`{p.get('source')}:{p.get('id')}`" for p in c.get("pastes", [])
            )
            out.append(f"- **{c.get('type')}** `{_cell(c.get('value'))}` — seen in {len(c.get('pastes', []))} pastes: {where}")
    else:
        out.append("No cross-paste correlations detected.")
    out.append("")

    categories: dict[str, int] = {}
    for f in ordered:
        name = f.get("category", "other")
        categories[name] = categories.get(name, 0) + 1
    out += ["## Findings by Category", ""]
    if categories:
        out.append(_table(["Category", "Findings"],
                          [[k, v] for k, v in sorted(categories.items(), key=lambda kv: -kv[1])]))
    else:
        out.append("No findings.")
    out.append("")

    out += ["## Detailed Findings", ""]
    if ordered:
        rows = []
        for i, f in enumerate(ordered, 1):
            where = ", ".join(
                f"{p.get('source')}:{p.get('id')}" for p in f.get("pastes", [])
            ) or "—"
            rows.append([
                i, _sev(f.get("severity")), f.get("kind", "standalone"),
                f.get("category", "other"), f.get("title", ""), where, _lines_of(f),
            ])
        out.append(_table(["#", "Severity", "Kind", "Category", "Finding", "Pastes", "Lines"], rows))
    else:
        out.append("No findings.")
    out.append("")

    if regex_findings_markdown:
        out += [regex_findings_markdown.rstrip(), ""]

    out += ["## Pastes Analyzed", ""]
    if pastes:
        rows = [[p.get("source", "?"), f"`{p.get('id', '')}`", p.get("content_type", ""),
                 p.get("findings", 0)] for p in pastes]
        out.append(_table(["Source", "Paste ID", "Type", "Findings"], rows))
    else:
        out.append("None.")
    out.append("")

    out += ["---", "", DATA_LIMIT_NOTE, ""]
    return "\n".join(out)
