"""Structured, relationship-aware LLM analysis.

The model is asked for a JSON object and its output is normalised into a stable
shape. Rendering is done deterministically elsewhere (``render.py``), so report
structure never depends on the model's prose.
"""

import json
import logging
import re

logger = logging.getLogger("blacksignal")

KINDS = {"standalone", "combination", "contextual"}
CATEGORIES = {"credential", "pii", "infrastructure", "financial", "business", "code", "other"}
SEVERITIES = {"low", "medium", "high", "critical"}

# Authoritative 0-100 risk scale. The level is always derived from the score so
# the label and the number can never disagree.
RISK_BANDS = (
    (0, 24, "low"),
    (25, 49, "medium"),
    (50, 74, "high"),
    (75, 100, "critical"),
)

# Deterministic scoring: the rating is a function of the identified findings,
# never of model prose. Weights are chosen so each finding severity lands in the
# matching band, with combination/context findings scoring higher.
SEVERITY_BASE = {"low": 18, "medium": 40, "high": 62, "critical": 82}
KIND_BONUS = {"standalone": 0, "combination": 8, "contextual": 6}
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# Entity types that are always at least High, even if the model marks them lower.
HIGH_IMPACT_ENTITY_TYPES = {
    "password", "private_key", "api_key", "ssn", "passport",
    "card_number", "bank_account",
}
# Combination findings in these categories are always at least High.
HIGH_IMPACT_CATEGORIES = {"credential", "pii", "financial"}


def score_to_level(score: int) -> str:
    for low, high, level in RISK_BANDS:
        if low <= score <= high:
            return level
    return "critical" if score > 100 else "low"


def effective_severity(finding: dict) -> str:
    """Model severity raised to a floor based on what the finding actually contains."""
    sev = str(finding.get("severity") or "medium").lower()
    if sev not in SEVERITY_RANK:
        sev = "medium"

    floor = "low"
    if finding.get("kind") == "combination" and finding.get("category") in HIGH_IMPACT_CATEGORIES:
        floor = "high"
    if any(str(e.get("type") or "").lower() in HIGH_IMPACT_ENTITY_TYPES
           for e in finding.get("entities", [])):
        floor = "high"

    return sev if SEVERITY_RANK[sev] >= SEVERITY_RANK[floor] else floor


def _risk_rationale(findings: list[dict], level: str, correlations: list | None) -> str:
    if not findings:
        return "No sensitive data identified."

    top = max(
        findings,
        key=lambda f: (SEVERITY_RANK[effective_severity(f)],
                       KIND_BONUS.get(f.get("kind"), 0)),
    )
    top_sev = effective_severity(top)
    text = (
        f"Rated {level.capitalize()} from {len(findings)} finding(s). "
        f"Highest: {top_sev} {top.get('kind', 'standalone')} {top.get('category', 'other')} - "
        f"{top.get('title', 'sensitive finding')}."
    )
    if correlations:
        text += f" {len(correlations)} correlated entity(ies) reused across pastes."
    return text


def compute_risk(findings: list[dict], correlations: list | None = None) -> dict:
    """Derive the 0-100 score and level from the identified findings."""
    if not findings:
        return {"level": "low", "score": 0, "rationale": "No sensitive data identified."}

    best = 0
    categories: set[str] = set()
    for finding in findings:
        sev = effective_severity(finding)
        score = SEVERITY_BASE[sev] + KIND_BONUS.get(finding.get("kind"), 0)
        best = max(best, score)
        if SEVERITY_RANK[sev] >= SEVERITY_RANK["high"]:
            categories.add(finding.get("category") or "other")

    # Breadth: additional high/critical categories increase exposure.
    breadth = min(8, max(0, len(categories) - 1) * 4)
    score = best + breadth

    # Aggregated risk: reused entities across pastes matter.
    if correlations:
        score += min(8, 4 + 2 * (len(correlations) - 1))

    score = max(0, min(100, score))
    level = score_to_level(score)
    return {"level": level, "score": score, "rationale": _risk_rationale(findings, level, correlations)}


ANALYSIS_SYSTEM_PROMPT = """You are a security analyst. Analyse the paste content and return ONLY a JSON object (no markdown fences, no prose) with exactly this shape:

{"summary": "2-4 sentence overview",
 "findings": [{
   "kind": "standalone|combination|contextual",
   "category": "credential|pii|infrastructure|financial|business|code|other",
   "title": "short description",
   "severity": "low|medium|high|critical",
   "confidence": 0.0,
   "evidence": [{"line": 1, "excerpt": "text from that line"}],
   "entities": [{"type": "name|username|password|api_key|private_key|token|host|ip|url|email|phone|address|dob|ssn|passport|license|national_id|bank_account|card_number|medical|wallet|other", "value": "..."}],
   "relationship": "why these values matter together (or empty)",
   "reasoning": "short explanation"
 }]}

Severity guidance per finding (the overall risk rating is computed from these):
- critical: directly exploitable, high-impact secret (admin credentials, private keys, live production API keys) or large PII sets with government IDs.
- high: usable credentials or tokens, a privileged credential, or PII including SSN/passport/financial data.
- medium: sensitive but limited exposure (internal hosts/topology, emails without passwords, moderate PII).
- low: minimal or metadata-only exposure.

Personal data rules (important):
- Personal data is sensitive even when no technical secrets are present.
- Always capture: full names, dates of birth, home/postal addresses, phone numbers, email addresses, government IDs (SSN, passport, driver's licence, national ID), financial data (bank accounts, card numbers), medical information, and account identifiers.
- When several fields describe the same person (e.g. name + date of birth + address + phone), report ONE finding with kind="combination", category="pii", listing the person (masked if needed) as an entity and every relevant evidence line. Still report separately any identifier that is sensitive on its own (SSN, passport, card number).
- A full name is worth reporting when it appears in a record/contact context or alongside other personal data; avoid flagging incidental words that merely look like names.

Technical and context rules (important):
- Do not only list standalone values. Look for values that become sensitive in combination or context.
- Credential bundles: username+password, API key+endpoint, private key+passphrase, JWT+issuer, cookie+domain, certificate+key.
- Infrastructure maps: internal hosts + ports + services + versions + credentials describing an attack surface.
- Business context: customer lists, pricing, contracts, proprietary logic.
- Use kind="combination" when the values are only sensitive together and cite every relevant line in evidence.
- Every finding must have at least one evidence line with the exact line number from the input.
- If nothing sensitive is found, return an empty findings array.
- Only describe what is actually present. Do not invent values."""

REPAIR_PROMPT = (
    "Your previous reply was not valid JSON. Reply again with ONLY the JSON object "
    "matching the requested schema — no markdown fences, no explanation."
)

BATCH_SYSTEM_PROMPT = """You are a security analyst writing the narrative for a report that aggregates structured findings from multiple pastes. You receive a compact JSON summary of findings and cross-paste correlations.

Return ONLY a JSON object (no markdown fences, no prose) with this shape:
{"summary": "3-5 sentence executive summary",
 "highlights": ["most important observation", "..."]}

Rules:
- Ground every statement in the provided data; do not invent.
- Emphasise cross-paste reuse/correlation when present.
- highlights: 3-6 short bullets, most severe first.
- The overall risk rating is computed by the application from the findings; do not provide a score.
- No markdown inside the JSON strings (plain text only)."""

BATCH_REPAIR_PROMPT = REPAIR_PROMPT


def build_single_messages(content: str, hints: str = "") -> list[dict]:
    user = f"PASTE CONTENT:\n\n{content}"
    if hints:
        user += "\n" + hints
    return [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_batch_messages(compact: str) -> list[dict]:
    return [
        {"role": "system", "content": BATCH_SYSTEM_PROMPT},
        {"role": "user", "content": f"AGGREGATED FINDINGS:\n\n{compact}"},
    ]


def extract_json(text: str | None) -> dict | None:
    """Best-effort extraction of a JSON object from model output."""
    if not text:
        return None
    s = text.strip()

    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()

    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(s[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _clean(value, limit: int = 500) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text[:limit]


def _enum(value, allowed: set[str], default: str) -> str:
    v = str(value or "").strip().lower()
    return v if v in allowed else default


def _int(value, default: int = 0, lo: int = 0, hi: int = 100) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _float(value, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def normalize_analysis(obj: dict) -> dict:
    """Coerce model output into the canonical analysis shape.

    The risk rating is computed from the findings (see ``compute_risk``); any
    risk object returned by the model is ignored.
    """
    summary = _clean(obj.get("summary"), 2000)

    findings: list[dict] = []
    raw_findings = obj.get("findings")
    if isinstance(raw_findings, list):
        for raw in raw_findings:
            if not isinstance(raw, dict):
                continue
            evidence = []
            for ev in raw.get("evidence") if isinstance(raw.get("evidence"), list) else []:
                if not isinstance(ev, dict):
                    continue
                evidence.append({
                    "line": _int(ev.get("line"), 0, 0, 10**9),
                    "excerpt": _clean(ev.get("excerpt"), 200),
                })
            entities = []
            for ent in raw.get("entities") if isinstance(raw.get("entities"), list) else []:
                if not isinstance(ent, dict):
                    continue
                value = _clean(ent.get("value"), 200)
                if not value:
                    continue
                entities.append({"type": _clean(ent.get("type"), 40) or "other", "value": value})

            title = _clean(raw.get("title"), 200)
            if not title:
                title = entities[0]["value"] if entities else "Sensitive finding"

            findings.append({
                "kind": _enum(raw.get("kind"), KINDS, "standalone"),
                "category": _enum(raw.get("category"), CATEGORIES, "other"),
                "title": title,
                "severity": _enum(raw.get("severity"), SEVERITIES, "medium"),
                "confidence": _float(raw.get("confidence")),
                "evidence": evidence,
                "entities": entities,
                "relationship": _clean(raw.get("relationship"), 400),
                "reasoning": _clean(raw.get("reasoning"), 600),
            })

    counts: dict[str, int] = {}
    for f in findings:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
    categories = [{"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]

    return {"summary": summary, "risk": compute_risk(findings), "findings": findings, "categories": categories}


def correct_evidence_lines(analysis_obj: dict, content: str) -> dict:
    """Point evidence at the real line for its excerpt.

    Models sometimes cite a nearby line number; matching the excerpt against the
    actual content makes evidence deterministic. Lines stay unchanged when the
    excerpt cannot be found.
    """
    lines = content.split("\n")[:200000]
    lowered = [line.lower() for line in lines]

    for finding in analysis_obj.get("findings", []):
        for ev in finding.get("evidence", []):
            excerpt = (ev.get("excerpt") or "").strip()
            if len(excerpt) < 4:
                continue
            probe = excerpt[:80].lower()
            for idx, line in enumerate(lowered):
                if probe in line:
                    ev["line"] = idx + 1
                    break
    return analysis_obj


def normalize_batch(obj: dict) -> dict:
    highlights = []
    for h in obj.get("highlights") if isinstance(obj.get("highlights"), list) else []:
        text = _clean(h, 300)
        if text:
            highlights.append(text)
    return {
        "summary": _clean(obj.get("summary"), 3000),
        "highlights": highlights[:8],
    }


CORRELATABLE_TYPES = {"email", "username", "password", "api_key", "private_key",
                      "host", "url", "domain", "ip", "wallet", "phone",
                      "ssn", "passport", "name", "address"}


def _normalize_text(value: str) -> str:
    """Normalise names/addresses for comparison: case, punctuation, whitespace."""
    v = value.lower().replace(".", " ").replace(",", " ")
    v = re.sub(r"\s+", " ", v).strip()
    return v


def _is_correlatable_value(etype: str, value: str) -> bool:
    """Apply stricter rules to avoid noisy name/address correlations."""
    text = value.strip()
    if etype == "name":
        words = [w for w in re.split(r"\s+", text) if any(c.isalpha() for c in w)]
        return len(words) >= 2 and len(text) >= 5
    if etype == "address":
        return len(text) >= 10
    return len(text) >= 4


def correlate(findings: list[dict]) -> list[dict]:
    """Find entity values that appear in more than one paste.

    ``findings`` items must include ``paste_id``, ``source`` and ``filename``
    alongside the normalised finding fields.
    """
    buckets: dict[tuple[str, str], dict] = {}
    for f in findings:
        for ent in f.get("entities", []):
            etype = str(ent.get("type") or "").lower()
            value = str(ent.get("value") or "").strip()
            if etype not in CORRELATABLE_TYPES or not _is_correlatable_value(etype, value):
                continue
            # Password-like values are compared case-sensitively; names/addresses
            # are normalised for punctuation/casing; other identifiers lowercase.
            if etype in {"password", "api_key", "private_key"}:
                key_value = value
            elif etype in {"name", "address"}:
                key_value = _normalize_text(value)
            else:
                key_value = value.lower()
            key = (etype, key_value)
            slot = buckets.setdefault(key, {"type": etype, "value": value, "pastes": {}})
            slot["pastes"][f["paste_id"]] = {
                "source": f.get("source", "?"),
                "id": f["paste_id"],
                "filename": f.get("filename", ""),
            }

    correlations = []
    for slot in buckets.values():
        if len(slot["pastes"]) >= 2:
            correlations.append({
                "type": slot["type"],
                "value": slot["value"],
                "pastes": list(slot["pastes"].values()),
            })
    correlations.sort(key=lambda c: (-len(c["pastes"]), c["type"], c["value"].lower()))
    return correlations


def dedupe_findings(findings: list[dict]) -> list[dict]:
    """Merge duplicate findings across pastes, keeping every paste reference."""
    merged: dict[tuple, dict] = {}
    for f in findings:
        entity_key = "|".join(sorted(
            f"{e.get('type','').lower()}={e.get('value','').strip().lower()}"
            for e in f.get("entities", [])
        ))
        key = (f.get("category"), f.get("kind"), f.get("title", "").strip().lower(), entity_key)
        if key not in merged:
            kept = dict(f)
            kept["pastes"] = [{"source": f.get("source", "?"), "id": f.get("paste_id", ""),
                               "filename": f.get("filename", "")}]
            merged[key] = kept
        else:
            merged[key]["pastes"].append({"source": f.get("source", "?"), "id": f.get("paste_id", ""),
                                          "filename": f.get("filename", "")})
    return list(merged.values())
