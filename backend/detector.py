import re
import os

SEARCH_TERMS_FILE = os.environ.get("SEARCH_TERMS_FILE", "/app/configs/searchterms.txt")

EMAIL_PASS_RE = re.compile(
    r'[\w.+-]+@[\w-]+\.[\w.-]+[\s]*:[\s]*[^\s]{4,}',
    re.IGNORECASE
)

PRIVATE_KEY_RE = re.compile(
    r'-----BEGIN\s+(RSA|DSA|EC|PGP|OPENSSH|PRIVATE)\s+KEY-----',
    re.IGNORECASE
)

AWS_KEY_RE = re.compile(r'AKIA[0-9A-Z]{16}')
GITHUB_TOKEN_RE = re.compile(r'(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}')
STRIPE_LIVE_RE = re.compile(r'(?:sk_live|rk_live|pk_live)_[A-Za-z0-9]{24,}')
GOOGLE_API_RE = re.compile(r'AIza[0-9A-Za-z_-]{35}')
JWT_RE = re.compile(r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')

SLACK_TOKEN_RE = re.compile(r'xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24}')
DISCORD_TOKEN_RE = re.compile(r'(?:mfa\.|NT[A-Za-z0-9]{23,25})')

URL_CONNECTION_RE = re.compile(
    r'(?:mysql|postgresql|postgres|mongodb(?:\\+srv)?|redis|jdbc|mssql)://[^\s\'"]+',
    re.IGNORECASE
)

ONION_RE = re.compile(r'[a-z2-7]{16,56}\.onion', re.IGNORECASE)

AUTH_HEADER_RE = re.compile(r'authorization:\s*(?:basic|bearer)\s+[^\s]+', re.IGNORECASE)

CC_RE = re.compile(r'\b(?:\d[ -]*?){13,16}\b')

HEROKU_API_RE = re.compile(r'[hH][eE][rR][oO][kK][uU].*[aA][pP][iI]_[kK][eE][yY]', re.IGNORECASE)

SEARCH_TERM_PATTERNS = []


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

SCAN_PATTERNS = [
    ("email:password", EMAIL_PASS_RE),
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
    ("heroku_api_key", HEROKU_API_RE),
]


def scan_content(content):
    findings = []

    scan_limit = content[:100000] if len(content) > 100000 else content
    lines = scan_limit.split("\n")

    for name, pattern in SCAN_PATTERNS:
        for i, line in enumerate(lines, 1):
            for match in pattern.finditer(line):
                findings.append({
                    "type": name,
                    "line": i,
                    "match": match.group()[:120],
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