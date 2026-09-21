#!/usr/bin/env bash
# Lightweight update: pull latest code, refresh Python deps and the systemd
# unit if they changed, restart the console. No prompts, no re-running the
# apt/claude-login steps that scripts/install.sh does on every invocation.
#
#   curl -fsSL https://raw.githubusercontent.com/sauliusc/travel-agent/main/scripts/update.sh | bash
#
# or, if already cloned:
#
#   sudo bash /opt/travel-agent/scripts/update.sh
#
# For a fresh box, or to redo credentials/claude login, use install.sh instead.

set -euo pipefail

INSTALL_DIR="/opt/travel-agent"

log() { echo -e "\n== $* =="; }

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (e.g. inside the LXC as root, or via sudo)." >&2
  exit 1
fi

if [ ! -d "$INSTALL_DIR/.git" ]; then
  echo "$INSTALL_DIR is not a travel-agent checkout — run scripts/install.sh first." >&2
  exit 1
fi

cd "$INSTALL_DIR"

log "Pulling latest code"
BEFORE="$(git rev-parse HEAD)"
git pull --ff-only origin main
AFTER="$(git rev-parse HEAD)"

if [ "$BEFORE" = "$AFTER" ]; then
  echo "Already up to date ($AFTER)."
else
  echo "Updated $BEFORE -> $AFTER"

  if git diff --name-only "$BEFORE" "$AFTER" | grep -q '^requirements\.txt$'; then
    log "requirements.txt changed — reinstalling dependencies"
    .venv/bin/pip install -q -r requirements.txt
  fi

  if git diff --name-only "$BEFORE" "$AFTER" | grep -q '^deploy/travel-console\.service$'; then
    log "systemd unit changed — reinstalling it"
    cp deploy/travel-console.service /etc/systemd/system/travel-console.service
    systemctl daemon-reload
  fi
fi

log "Restarting travel-console"
systemctl restart travel-console
systemctl --no-pager --lines=0 status travel-console || true

echo
echo "Logs: journalctl -u travel-console -f"
