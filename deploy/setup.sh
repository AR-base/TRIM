#!/usr/bin/env bash
# One-command install of Trim on a fresh Ubuntu 22.04/24.04 server.
# Run from the repository root:   sudo ./deploy/setup.sh <your-domain>
# Safe to re-run: existing secrets in .env are kept, and the demo data is only loaded once.
set -euo pipefail

DOMAIN="${1:-}"
if [[ $EUID -ne 0 ]]; then echo "Run with sudo." >&2; exit 1; fi
if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]]; then
  echo "Usage: sudo ./deploy/setup.sh <domain>   (a DNS name pointing at this server, not an IP)" >&2
  exit 1
fi
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml)

echo "==> Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

echo "==> Swap (image builds need memory on small servers)"
if [[ -z "$(swapon --show)" && $(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo) -lt 3900 ]]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Firewall: SSH, HTTP, HTTPS only"
if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
  ufw --force enable >/dev/null
fi

FIRST_INSTALL=0
if [[ ! -f .env ]]; then
  echo "==> Generating secrets into .env (readable by root only)"
  FIRST_INSTALL=1
  read -r PGPW KEY TOKEN HASH < <(python3 - <<'PY'
import base64, hashlib, secrets
token = "trim_" + secrets.token_urlsafe(32)
print(secrets.token_urlsafe(32), base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
      token, hashlib.sha256(token.encode()).hexdigest())
PY
)
  umask 077
  cat > .env <<ENV
POSTGRES_PASSWORD=${PGPW}
TRIM_DOMAIN=${DOMAIN}
TRIM_API_TOKENS=admin:admin:${HASH}
TRIM_ENCRYPTION_KEY=${KEY}
TRIM_CONNECTOR=simulated
TRIM_CORS_ORIGINS=https://${DOMAIN}
TRIM_OBSERVATION_DAYS=14
TRIM_BASELINE_DAYS=14
TRIM_ACTIVITY_RETENTION_DAYS=90
ENV
else
  sed -i "s|^TRIM_DOMAIN=.*|TRIM_DOMAIN=${DOMAIN}|" .env
fi

echo "==> Building and starting (first build takes a few minutes)"
"${COMPOSE[@]}" up -d --build

if [[ $FIRST_INSTALL -eq 1 ]]; then
  echo "==> Loading the test organisation"
  "${COMPOSE[@]}" run --rm api trim simulate >/dev/null
fi

echo
echo "Trim is starting at https://${DOMAIN}  (the certificate can take a minute on first start)"
if [[ $FIRST_INSTALL -eq 1 ]]; then
  echo
  echo "Admin sign-in token (shown ONCE, save it in your password manager):"
  echo "  ${TOKEN}"
fi
