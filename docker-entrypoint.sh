#!/bin/bash
set -e

HTPASSWD_FILE="/app/data/.htpasswd"
CRED_FILE="/app/data/.credentials"

mkdir -p /app/data /app/configs

if [ ! -f /app/configs/searchterms.txt ]; then
    cp /app/searchterms.txt /app/configs/searchterms.txt 2>/dev/null || true
fi

if [ ! -f "$HTPASSWD_FILE" ]; then
    AUTH_USER="${AUTH_USER:-admin}"
    AUTH_PASS="${AUTH_PASSWORD:-$(openssl rand -base64 12)}"
    htpasswd -bc "$HTPASSWD_FILE" "$AUTH_USER" "$AUTH_PASS"
    echo "URL:     http://localhost" > "$CRED_FILE"
    echo "Username: $AUTH_USER" >> "$CRED_FILE"
    echo "Password: $AUTH_PASS" >> "$CRED_FILE"
    echo ""
    echo "┌──────────────────────────────────────┐"
    echo "│     BlackSignal Web App Credentials   │"
    echo "│                                      │"
    printf "│  URL:     http://localhost             │\n"
    printf "│  Username: %-28s │\n" "$AUTH_USER"
    printf "│  Password: %-28s │\n" "$AUTH_PASS"
    echo "└──────────────────────────────────────┘"
    echo ""
fi

nginx

cd /app
exec python3 main.py