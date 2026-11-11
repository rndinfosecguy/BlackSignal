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

def _is_low_entropy(s: str) -> bool:
    """True if the string has 4+ consecutive identical characters (low entropy)."""
    count = 1
    for i in range(1, len(s)):
        count = count + 1 if s[i] == s[i-1] else 1
        if count >= 4:
            return True
    return False
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

# WordPress config file — matches actual WP-specific define() calls within the file,
# not just filename mentions.
WPCONFIG_RE = re.compile(
    r"""define\s*\(\s*['"](?:DB_NAME|DB_USER|DB_PASSWORD|DB_HOST|AUTH_KEY|SECURE_AUTH_KEY|LOGGED_IN_KEY|NONCE_KEY|AUTH_SALT|SECURE_AUTH_SALT|LOGGED_IN_SALT|NONCE_SALT|WP_LOCALE|WP_DEBUG|DB_CHARSET|DB_COLLATE)['"]"""
    r"""|\$table_prefix\s*=""",
    re.IGNORECASE
)

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

# ── Personal data patterns ────────────────────────────────────────────────────

# Standalone email (not in email:password format)
PERSONAL_EMAIL_RE = re.compile(
    r'[\w.+-]{2,}@[\w-]{3,}\.[a-z]{2,}',
    re.IGNORECASE
)

# Social Security Number: xxx-xx-xxxx
SSN_RE = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')

# Bitcoin address (legacy 1... or SegWit 3...)
BTC_ADDR_RE = re.compile(r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,40}\b')

# Ethereum address: 0x + 40 hex
ETH_ADDR_RE = re.compile(r'\b0x[a-fA-F0-9]{40}\b')

# Passport number: letter(s) + 6-9 digits, word-bounded
PASSPORT_RE = re.compile(r'\b[A-Z]{1,2}\d{6,9}\b')

# Name + DOB on same line: "First Last" near a date
NAME_DOB_RE = re.compile(
    r'[A-Z][a-z]+ [A-Z][a-z]+.{0,40}?\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',
)

PATTERN_CATEGORIES = {
    "personal_email": "personal",
    "ssn": "personal",
    "btc_address": "personal",
    "eth_address": "personal",
    "passport": "personal",
    "name_dob": "personal",
}

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
    r'|github_pat_|mysqli_connect|client_secret'
    r'|define\s*\(|table_prefix'
    r'|\d{3}-\d{2}-\d{4}|[13][a-km-zA-HJ-NP-Z]|0x[a-fA-F0-9]{20,}'
    r'|[A-Z]{1,2}\d{6,9}|\d{1,2}/\d{1,2}/\d{2,4}',
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
    ("personal_email", PERSONAL_EMAIL_RE),
    ("ssn", SSN_RE),
    ("btc_address", BTC_ADDR_RE),
    ("eth_address", ETH_ADDR_RE),
    ("passport", PASSPORT_RE),
    ("name_dob", NAME_DOB_RE),
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
                    # Skip if preceded by a letter — part of SVG path or code identifier
                    if match.start() > 0 and line[match.start() - 1].isalpha():
                        continue
                    # Skip if match has 5+ small groups separated by spaces (SVG coords, not CC)
                    parts = group.split(' ')
                    if len(parts) >= 5 and all(len(p) <= 3 for p in parts):
                        continue
                    # Skip if preceded by '-' and match contains '-' — embedded in SID/ID
                    if '-' in group and match.start() > 0 and line[match.start() - 1] == '-':
                        continue
                    # Skip if followed by '-' — inside a subtraction or negative number
                    if match.end() < len(line) and line[match.end()] == '-':
                        after = match.end() + 1
                        if after < len(line) and (line[after].isdigit() or line[after] in '(d'):
                            continue
                    # Skip if match has '-' and a segment has 7+ digits (math, not CC)
                    if '-' in group:
                        segs = group.replace(' ', '').split('-')
                        if any(len(s) >= 7 for s in segs):
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
                        if '?' in pw_side or '#' in pw_side or '/' in pw_side or pw_side.startswith('"') or '$' in pw_side:
                            continue
                        # Block if it contains param-style assignments (= followed by digit)
                        if re.search(r'=\d', pw_side):
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
                    # Skip file paths (/path/to/file)
                    if '/' in value:
                        continue
                    # Skip shell variable references ($VAR, ${VAR})
                    if '$' in value or '{' in value:
                        continue
                    # Skip if value is all-same-character (masked/placeholder)
                    if len(set(value)) == 1:
                        continue

                # ── AWS key: skip low-entropy matches (base64 artifacts) ──
                elif name == "aws_key":
                    # AKIA + 16 chars: total 20 chars, check suffix
                    if len(group) > 4 and _is_low_entropy(group[4:]):
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

                # ── Personal email: skip if already caught by email:password ─
                elif name == "personal_email":
                    # Skip if line also contains email:password pattern (already caught)
                    if ':' in group.split('@')[0]:
                        continue
                    parts = group.split('@')
                    if len(parts) == 2:
                        domain = parts[1].split('.')[0]
                        # Skip if domain starts with a digit (random encoded text)
                        if domain and domain[0].isdigit():
                            continue
                        # Skip if domain has mixed case with uppercase not at start (random text)
                        if domain and any(c.isupper() for c in domain[1:]):
                            continue

                # ── SSN: reject test/placeholder numbers ───────────────────
                elif name == "ssn":
                    digits = group.replace('-', '')
                    if digits in ('000000000', '123456789', '111111111'):
                        continue

                # ── Passport: skip if too short or looks like a code ───────
                elif name == "passport":
                    if len(group) < 7:
                        continue
                    # Skip if preceded by a word character (likely part of code)
                    if match.start() > 0 and line[match.start() - 1].isalnum():
                        continue
                    # Skip if preceded by @ or | (tag/identifier, not passport)
                    if match.start() > 0 and line[match.start() - 1] in '@|':
                        continue
                    # Skip if the digit portion starts with a leading zero (ID number, not passport)
                    digits = re.sub(r'[^0-9]', '', group)
                    if digits and digits[0] == '0':
                        continue

                # ── BTC / ETH: skip if part of a file path ────────────────
                elif name in ("btc_address", "eth_address"):
                    # Skip if preceded by / or \ (path segment, not wallet address)
                    if match.start() > 0 and line[match.start() - 1] in '/\\':
                        continue
                    # Skip if followed by / or . (path continuation or file extension)
                    if match.end() < len(line) and line[match.end()] in '/.':
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