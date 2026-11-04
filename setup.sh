#!/bin/bash
set -e

# ── BlackSignal setup: Docker Engine + Compose plugin ──────────────────────

if [ "$EUID" -ne 0 ]; then
    echo "Re-running with sudo…"
    exec sudo "$0" "$@"
fi

export DEBIAN_FRONTEND=noninteractive

echo "==> Updating package lists…"
apt-get update -qq

echo "==> Installing Docker Engine…"
apt-get install -y -qq docker.io

echo "==> Installing Docker Compose…"
if apt-get install -y -qq docker-compose-plugin 2>/dev/null; then
    echo "    (via docker-compose-plugin)"
else
    echo "    Plugin not available — installing standalone binary…"
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  ARCH=x86_64 ;;
        aarch64) ARCH=aarch64 ;;
        armv7l)  ARCH=armv7l ;;
        *)       echo "Unsupported architecture: $ARCH"; exit 1 ;;
    esac
    LATEST=$(curl -fsSL https://api.github.com/repos/docker/compose/releases/latest \
              | grep '"tag_name":' | cut -d\" -f4)
    [ -z "$LATEST" ] && { echo "Failed to detect latest Compose version"; exit 1; }
    URL="https://github.com/docker/compose/releases/download/${LATEST}/docker-compose-linux-${ARCH}"
    curl -fsSL "$URL" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo "    Standalone ${LATEST} installed to /usr/local/bin/docker-compose"
fi

echo "==> Enabling and starting Docker…"
systemctl enable --now docker

echo ""
echo "==> Versions"
docker --version
if command -v docker-compose &>/dev/null; then
    docker-compose --version
else
    docker compose version
fi

# ── Cleanup ──────────────────────────────────────────────────────────────────

README="raw_pastes/README.md"
if [ -f "$README" ]; then
    rm -f "$README"
    echo "==> Removed $README"
else
    echo "==> $README not present, nothing to clean"
fi

echo ""
echo "============================================"
echo "  Setup complete."
echo ""
echo "  Next step: start the application"
echo "    docker compose up -d --build"
echo ""
echo "  Then open http://localhost:9090"
echo "============================================"