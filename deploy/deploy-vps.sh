#!/usr/bin/env bash
# Deploys the game server on the VPS (run as root on the server).
# Rollback: see the "rollback" lines printed at the end.
set -euo pipefail

APP=/var/www/liars-poker
UNIT=/etc/systemd/system/liars-poker.service
BACKUPS=/root/backups
BRANCH=${BRANCH:-mobile-app-integration}

mkdir -p "$BACKUPS"
cd "$APP"
OLD=$(git rev-parse HEAD)
STAMP=$(date +%Y%m%d-%H%M%S)
cp "$UNIT" "$BACKUPS/liars-poker.service.$STAMP"
echo "$OLD" > "$BACKUPS/liars-poker.commit.$STAMP"
echo "== previous commit $OLD saved"

git fetch -q origin
git checkout -q "$BRANCH"
git pull -q --ff-only origin "$BRANCH"
echo "== now at $(git log --oneline -1)"

venv/bin/pip install -q --disable-pip-version-check -r requirements-server.txt
echo "== dependencies installed"

venv/bin/python -m pytest -q -p no:cacheprovider tests 2>&1 | tail -2
mkdir -p data
chown -R www-data:www-data data

cat > "$UNIT" <<EOF
[Unit]
Description=Liars Poker game server (python-socketio on uvicorn)
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=$APP
Environment="PATH=$APP/venv/bin"
Environment="DB_PATH=$APP/data/liars_poker.db"
Environment="APP_VERSION=server-$(git rev-parse --short HEAD)"
# One process on purpose: live games are held in memory (and saved to DB_PATH).
ExecStart=$APP/venv/bin/uvicorn --factory server.app:create_app --host 127.0.0.1 --port 4000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=3
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl restart liars-poker
sleep 3
systemctl is-active liars-poker
curl -fsS http://127.0.0.1:4000/health && echo
echo "== deployed. rollback: git -C $APP checkout $OLD && cp $BACKUPS/liars-poker.service.$STAMP $UNIT && systemctl daemon-reload && systemctl restart liars-poker"
