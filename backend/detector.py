import re
import os

SEARCH_TERMS_FILE = os.environ.get("SEARCH_TERMS_FILE", "/app/configs/searchterms.txt")

# ── Email:password ───────────────────────────────────────────────────────────
# Require 6+ chars on the password side with at least one non-alpha character.
EMAIL_PASS_RE = re.compile(
    r'[\w.+-]+@[\w-]+\.[\w.-]+[\s]*:[\s]*(?=[^\s]*[^a-zA-Z\s][^\s]*)[^\s]{6,}',
    re.IGNORECASE
)

# ── Key=value credential assignments ─────────────────────────────────────────
# Lines like password=something where the value looks like a real credential.
ASSIGN_CRED_RE = re.compile(
    r'(?:password|passwd|pwd|secret|db_password|db_username|api_key|api_secret)\s*=\s*\S+',
    re.IGNORECASE
)

# ── High-precision token patterns ────────────────────────────────────────────

PRIVATE_KEY_RE = re.compile(
    r'-----BEGIN\s+(RSA|DSA|EC|PGP|OPENSSH|PRIVATE)\s+KEY-----',
    re.IGNORECASE
)

AWS_KEY_RE = re.compile(r'AKIA[0-9A-Z]{16}')
GITHUB_TOKEN_RE = re.compile(r'(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}')
STRIPE_LIVE_RE = re.compile(r'(?:sk_live|rk_live|pk_live)_[A-Za-z0-9]{24,}')
GOOGLE_API_RE = re.compile(r'AIza[0-9A-Za-z_-]{35}')
SLACK_TOKEN_RE = re.compile(r'xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24}')

# ── Weakened patterns ────────────────────────────────────────────────────────

# JWT: broad base64-like pattern — kept but noisy.
JWT_RE = re.compile(r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')

# Discord: dropped the short NT prefix, kept only the distinctive mfa. prefix.
DISCORD_TOKEN_RE = re.compile(r'mfa\.[A-Za-z0-9]{23,25}')

# Connection string: require an @ (user:pass or token) in the URL.
URL_CONNECTION_RE = re.compile(
    r'(?:mysql|postgresql|postgres|mongodb(?:\\+srv)?|redis|jdbc|mssql)://[^\s\'"]*@[^\s\'"]+',
    re.IGNORECASE
)

# Onion: kept as-is (distinctive .onion TLD).
ONION_RE = re.compile(r'[a-z2-7]{16,56}\.onion', re.IGNORECASE)

# Auth header: require a 20+ char token after bearer/basic.
AUTH_HEADER_RE = re.compile(r'authorization:\s*(?:basic|bearer)\s+[^\s]{20,}', re.IGNORECASE)

# Credit card: validated with Luhn algorithm + heuristic filters below.
CC_RE = re.compile(r'\b(?:\d[ -]*?){13,16}\b')

# SQL INSERT INTO user-related tables (database dumps with credentials).
INSERT_INTO_RE = re.compile(
    r'INSERT\s+INTO\s+\w*(?:user|account|credential|password|auth|login|member|admin|customer|profile|employee|session|token|api)[_\w]*',
    re.IGNORECASE
)

# Common test/vanity card numbers that pass Luhn but aren't real.
_KNOWN_TEST_CARDS = frozenset({
    '4111111111111111', '5500000000000000', '4007000000000000',
    '4000000000000000', '5105105105105100', '2223000000000000',
    '4012888888881881', '4222222222222', '5555555555554444',
})

SEARCH_TERM_PATTERNS = []


def _luhn_check(digits: str) -> bool:
    """Luhn checksum — real credit card numbers pass, random digits don't."""
    if not digits.isdigit():
        return False
    # Reject all-same-digit (00000…, 11111…)
    if len(set(digits)) == 1:
        return False
    # Skip known test/vanity numbers
    if digits in _KNOWN_TEST_CARDS:
        return False
    total = 0
    reverse = digits[::-1]
    for i, d in enumerate(reverse):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def load_search_terms():
    global SEARCH_TERM_PATTERNS
    SEARCH_TERM_PATTERNS = []
    try:
        if os.path.exists(SEARCH_TERMS_FILE):
            with open(SEARCH_TERMS_FILE, "r") as f:
                for line in f:
                    term = line.strip()
                    if term and not term.startswith("#"):
                        SEARCH_TERM_PATTERNS.append(re.compile(re.escape(term), re.IGNORECASE))
    except Exception:
        pass


load_search_terms()

# Fast pre-filter: quick scan to skip lines that can't match any pattern.
# Covers all patterns in SCAN_PATTERNS below.
_HAS_TRIGGER = re.compile(
    r'[@=]|BEGIN |AKIA|gh[pousr]_|sk_live|rk_live|pk_live|AIza'
    r'|eyJ[A-Za-z0-9]|xox[baprs]-|mfa\.|://|\.onion|authorization:'
    r'|INSERT\s+INTO|\d{13,}',
    re.IGNORECASE
)

SCAN_PATTERNS = [
    ("email:password", EMAIL_PASS_RE),
    ("credential_assignment", ASSIGN_CRED_RE),
    ("private_key", PRIVATE_KEY_RE),
    ("aws_key", AWS_KEY_RE),
    ("github_token", GITHUB_TOKEN_RE),
    ("stripe_key", STRIPE_LIVE_RE),
    ("google_api_key", GOOGLE_API_RE),
    ("jwt_token", JWT_RE),
    ("slack_token", SLACK_TOKEN_RE),
    ("discord_token", DISCORD_TOKEN_RE),
    ("connection_string", URL_CONNECTION_RE),
    ("onion_address", ONION_RE),
    ("auth_header", AUTH_HEADER_RE),
    ("credit_card", CC_RE),
    ("sql_user_insert", INSERT_INTO_RE),
]


def scan_content(content):
    findings = []

    scan_limit = content
    lines = scan_limit.split("\n")

    for i, line in enumerate(lines, 1):
        # Fast pre-filter: skip lines that can't match any pattern
        if not _HAS_TRIGGER.search(line):
            continue
        for name, pattern in SCAN_PATTERNS:
            for match in pattern.finditer(line):
                group = match.group()

                # ── Credit card: Luhn + heuristic filters ────────────────
                if name == "credit_card":
                    digits = re.sub(r'[ -]', '', group)
                    if not _luhn_check(digits):
                        continue
                    # IIN check — real cards start with 2-6
                    # (Visa:4, Mastercard:2/51-55, Amex:34/37, Discover:6011/65)
                    if digits[0] not in '23456':
                        continue

                # ── Email:password: skip proxy/URL query strings ──────────
                elif name == "email:password":
                    colon_idx = group.find(':')
                    if colon_idx != -1:
                        pw_side = group[colon_idx + 1:].strip()
                        # Block if the "password" side looks like a URL
                        # query string or fragment (port + ?/#, common in proxy/VPN configs)
                        if '?' in pw_side or '#' in pw_side:
                            continue

                # ── Credential assignment: validate the value ─────────────
                elif name == "credential_assignment":
                    # Extract the value after =
                    value = group.split('=', 1)[1].strip().strip('"\'')
                    # Skip placeholders, empty values, short values
                    if not value or len(value) < 4:
                        continue
                    if value.lower() in ('null', 'none', 'undefined', 'your-password',
                                         'password', 'changeme', 'xxxx', '****',
                                         'your-password-here'):
                        continue
                    # Skip function calls (foo()) and property/method chains (foo.bar)
                    if '(' in value or '.' in value:
                        continue
                    # Skip if value is all-same-character (masked/placeholder)
                    if len(set(value)) == 1:
                        continue

                findings.append({
                    "type": name,
                    "line": i,
                    "match": group[:120],
                })

    for pattern in SEARCH_TERM_PATTERNS:
        for i, line in enumerate(lines, 1):
            for match in pattern.finditer(line):
                findings.append({
                    "type": "search_term",
                    "line": i,
                    "match": match.group()[:120],
                })

    has_passwords = any(f["type"] == "email:password" for f in findings)
    has_secrets = len(findings) > 0

    return has_passwords, has_secrets, findings