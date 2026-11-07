import re
import os

SEARCH_TERMS_FILE = os.environ.get("SEARCH_TERMS_FILE", "/app/configs/searchterms.txt")
if not os.path.exists(SEARCH_TERMS_FILE):
    local = os.path.join(os.path.dirname(__file__), "searchterms.txt")
    if os.path.exists(local):
        SEARCH_TERMS_FILE = local

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
    r'-----BEGIN\s+(?:(?:RSA|DSA|EC|OPENSSH|PGP)\s+)?PRIVATE\s+KEY-----',
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

# Onion: matches all lowercase alphanumeric onion v3 addresses.
ONION_RE = re.compile(r'[a-z0-9]{16,56}\.onion', re.IGNORECASE)

# Auth header: require a 20+ char token after bearer/basic.
AUTH_HEADER_RE = re.compile(r'authorization:\s*(?:basic|bearer)\s+[^\s]{20,}', re.IGNORECASE)

# Credit card: validated with Luhn algorithm + heuristic filters below.
CC_RE = re.compile(r'\b(?:\d[- ]*?){13,16}\b')

# SQL INSERT INTO user-related tables (database dumps with credentials).
INSERT_INTO_RE = re.compile(
    r'INSERT\s+INTO\s+\w*(?:user|account|credential|password|auth|login|member|admin|customer|profile|employee|session|token|api)[_\w]*',
    re.IGNORECASE
)

# GitHub personal access token (pat_ prefix, not covered by GITHUB_TOKEN_RE).
GITHUB_PAT_RE = re.compile(r'github_pat_[A-Za-z0-9_]{20,}')

# PHP mysqli_connect call — often contains hardcoded credentials.
MYSQLI_CONNECT_RE = re.compile(
    r'mysqli_connect\s*\([^;]+',
    re.IGNORECASE
)

# WordPress config file reference.
WPCONFIG_RE = re.compile(r'wp-config\.php', re.IGNORECASE)

# OAuth client_secret assignment.
CLIENT_SECRET_RE = re.compile(
    r'client_secret\s*=\s*\S+',
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
    r'|INSERT\s+INTO|\d{13,}'
    r'|\b\d[- ]*\d[- ]*\d[- ]*\d[- ]*\d[- ]*\d[- ]*\d[- ]*\d'
    r'[- ]*\d[- ]*\d[- ]*\d[- ]*\d[- ]*\d[- ]*'
    r'|github_pat_|mysqli_connect|wp-config|client_secret',
    re.IGNORECASE
)

SCAN_PATTERNS = [
    ("email:password", EMAIL_PASS_RE),
    ("credential_assignment", ASSIGN_CRED_RE),
    ("private_key", PRIVATE_KEY_RE),
    ("aws_key", AWS_KEY_RE),
    ("github_token", GITHUB_TOKEN_RE),
    ("github_pat", GITHUB_PAT_RE),
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
    ("mysql_connect", MYSQLI_CONNECT_RE),
    ("wp_config", WPCONFIG_RE),
    ("client_secret", CLIENT_SECRET_RE),
]


def scan_content(content, scan_limit=None):
    """Scan paste content for secrets. 
    scan_limit — max characters to scan (None = default 200K, 0 = unlimited)."""
    findings = []

    if scan_limit == 0:
        scan_text = content
    elif scan_limit is None:
        scan_text = content[:200000] if len(content) > 200000 else content
    else:
        scan_text = content[:scan_limit] if len(content) > scan_limit else content
    lines = scan_text.split("\n")

    for i, line in enumerate(lines, 1):
        # Fast pre-filter: skip lines that can't match any pattern
        if not _HAS_TRIGGER.search(line):
            continue
        for name, pattern in SCAN_PATTERNS:
            for match in pattern.finditer(line):
                group = match.group()

                # ── Credit card: Luhn + heuristic filters ────────────────
                if name == "credit_card":
                    # Skip if preceded by '.' — decimal fraction, not a CC
                    if match.start() > 0 and line[match.start() - 1] == '.':
                        continue
                    # Skip if preceded by '-' and match contains '-' — embedded in SID/ID
                    if '-' in group and match.start() > 0 and line[match.start() - 1] == '-':
                        continue
                    digits = re.sub(r'[ -]', '', group)
                    if not _luhn_check(digits):
                        continue
                    # IIN + digit-length validation
                    # Visa: 4xxx (13 or 16 digits)
                    # Mastercard: 51-55 or 2221-2720 (16 digits)
                    # Amex: 34 or 37 (15 digits)
                    # Discover: 6011 or 65 (16 digits)
                    d = digits
                    if d[0] not in '23456':
                        continue
                    if d[0] == '2' and (len(d) != 16 or not (2221 <= int(d[:4]) <= 2720)):
                        continue
                    if d[0] == '3' and len(d) != 15:
                        continue
                    if d[0] == '4' and len(d) not in (13, 16):
                        continue
                    if d[0] == '5' and (len(d) != 16 or not (51 <= int(d[:2]) <= 55)):
                        continue
                    if d[0] == '6' and (len(d) != 16 or not (d[:4] == '6011' or d[:2] == '65')):
                        continue

                # ── Email:password: skip proxy/URL query strings ──────────
                elif name == "email:password":
                    colon_idx = group.find(':')
                    if colon_idx != -1:
                        # Skip double colon (::) — protocol/version separator, not a password
                        if colon_idx + 1 < len(group) and group[colon_idx + 1] == ':':
                            continue
                        pw_side = group[colon_idx + 1:].strip()
                        # Block if the "password" side looks like a URL/path/proxy/config
                        # rather than a real credential
                        if '?' in pw_side or '#' in pw_side or '/' in pw_side or pw_side.startswith('"'):
                            continue
                        # Block if it contains param-style assignments (= followed by digit)
                        if re.search(r'=\d', pw_side):
                            continue
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
                    # Skip shell variable references ($VAR, ${VAR})
                    if '$' in value or '{' in value:
                        continue
                    # Skip if value is all-same-character (masked/placeholder)
                    if len(set(value)) == 1:
                        continue

                # ── Auth header: skip variable references ─────────────────
                elif name == "auth_header":
                    if '$' in group:
                        continue

                # ── Client secret: validate the value ────────────────────
                elif name == "client_secret":
                    value = group.split('=', 1)[1].strip().strip('"\'') if '=' in group else group
                    if not value or len(value) < 4:
                        continue
                    if '(' in value or '.' in value or '$' in value:
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