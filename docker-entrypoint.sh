#!/bin/bash
set -e

CRED_FILE="/app/data/.credentials"

mkdir -p /app/data /app/configs

if [ ! -f /app/configs/searchterms.txt ]; then
    cp /app/searchterms.txt /app/configs/searchterms.txt 2>/dev/null || true
fi

# Credentials are created on first boot. The backend derives a password hash
# from this file into /app/data/.auth.json on startup; auth is enforced by the
# application (login screen / HTTP Basic), so no htpasswd file is needed.
if [ ! -f "$CRED_FILE" ]; then
    AUTH_USER="${AUTH_USER:-admin}"
    AUTH_PASS="${AUTH_PASSWORD:-$(openssl rand -base64 12)}"
    umask 077
    echo "URL:     http://localhost" > "$CRED_FILE"
    echo "Username: $AUTH_USER" >> "$CRED_FILE"
    echo "Password: $AUTH_PASS" >> "$CRED_FILE"
    umask 022
    INNER=46
    printf -v BORDER '─%.0s' $(seq 1 $INNER)
    echo "┌${BORDER}┐"
    printf "│  %-42s  │\n" "BlackSignal Web App Credentials"
    printf "│  %-42s  │\n" ""
    printf "│  %-42s  │\n" "URL:     http://localhost"
    printf "│  Username: %-32s  │\n" "$AUTH_USER"
    printf "│  Password: %-32s  │\n" "$AUTH_PASS"
    echo "└${BORDER}┘"
    echo ""
fi

nginx

cd /app
exec python3 main.py