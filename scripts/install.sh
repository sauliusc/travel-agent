#!/usr/bin/env bash
# One-click installer for the travel-agent console, run inside a fresh
# Debian/Ubuntu Proxmox LXC container as root.
#
#   curl -fsSL https://raw.githubusercontent.com/sauliusc/travel-agent/main/scripts/install.sh | bash
#
# or, if you already cloned the repo:
#
#   sudo bash scripts/install.sh
#
# Idempotent: safe to re-run. Re-running skips steps that are already done
# and leaves an existing /etc/travel-agent/credentials.env untouched unless
# you pass --reconfigure.
#
# See docs/PROXMOX_SETUP.md for the full manual walkthrough this automates.

set -euo pipefail

REPO_URL="https://github.com/sauliusc/travel-agent"
INSTALL_DIR="/opt/travel-agent"
CREDENTIALS_DIR="/etc/travel-agent"
CREDENTIALS_FILE="$CREDENTIALS_DIR/credentials.env"
RECONFIGURE=false

for arg in "$@"; do
  case "$arg" in
    --reconfigure) RECONFIGURE=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

log() { echo -e "\n== $* =="; }

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (e.g. inside the LXC as root, or via sudo)." >&2
  exit 1
fi

# When invoked as `curl ... | bash`, bash's stdin (fd 0) is the incoming
# script text, not your keyboard — every `read` below would otherwise
# silently consume upcoming script lines as "input" and desync the whole
# run. Force all interactive reads through /dev/tty instead, which is the
# real terminal regardless of how this script was launched.
if [ -r /dev/tty ]; then
  TTY_IN=/dev/tty
else
  echo "No /dev/tty available — can't prompt interactively (e.g. running in CI)." >&2
  echo "Set credentials via a pre-existing /etc/travel-agent/credentials.env instead." >&2
  exit 1
fi

log "Installing system packages"
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git curl caddy >/dev/null

log "Fetching travel-agent"
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull --ff-only origin main
else
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

log "Setting up Python virtualenv"
cd "$INSTALL_DIR"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

log "Installing the Anthropic CLI (ant)"
if ! command -v ant >/dev/null 2>&1; then
  curl -fsSL https://cli.anthropic.com/install.sh | sh || {
    echo "ant CLI install failed — you can skip it and set ANTHROPIC_API_KEY instead." >&2
  }
else
  echo "ant already installed, skipping."
fi

mkdir -p "$CREDENTIALS_DIR"
chmod 700 "$CREDENTIALS_DIR"

anthropic_choice=""

if [ -f "$CREDENTIALS_FILE" ] && [ "$RECONFIGURE" = false ]; then
  log "Credentials already configured at $CREDENTIALS_FILE (use --reconfigure to redo this)"
else
  log "Configuring credentials (all stored in $CREDENTIALS_FILE, mode 600)"

  echo
  echo "Anthropic access:"
  echo "  1) I already ran (or will run) 'ant auth login' — leave ANTHROPIC_API_KEY empty"
  echo "  2) I have an API key to paste in"
  read -r -p "Choose 1 or 2 [1]: " anthropic_choice < "$TTY_IN"
  anthropic_choice="${anthropic_choice:-1}"
  ANTHROPIC_API_KEY=""
  if [ "$anthropic_choice" = "2" ]; then
    read -r -s -p "ANTHROPIC_API_KEY: " ANTHROPIC_API_KEY < "$TTY_IN"
    echo
  fi

  read -r -p "GITHUB_TOKEN (fine-grained PAT, Contents/PRs/Workflows/Pages read-write): " GITHUB_TOKEN < "$TTY_IN"
  read -r -p "GITHUB_OWNER [sauliusc]: " GITHUB_OWNER < "$TTY_IN"
  GITHUB_OWNER="${GITHUB_OWNER:-sauliusc}"

  read -r -p "Console basic-auth username [saulius]: " CONSOLE_USER < "$TTY_IN"
  CONSOLE_USER="${CONSOLE_USER:-saulius}"
  read -r -s -p "Console basic-auth password: " CONSOLE_PASSWORD < "$TTY_IN"
  echo

  cat > "$CREDENTIALS_FILE" <<EOF
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
GITHUB_TOKEN=$GITHUB_TOKEN
GITHUB_OWNER=$GITHUB_OWNER
CONSOLE_BASIC_AUTH_USER=$CONSOLE_USER
CONSOLE_BASIC_AUTH_PASSWORD=$CONSOLE_PASSWORD
EOF
  chmod 600 "$CREDENTIALS_FILE"
  echo "Written $CREDENTIALS_FILE"
fi

# Re-read what we just wrote (or what was already there) for the Caddy step,
# without `source`-ing the file — it holds a user-supplied password verbatim,
# and sourcing it would execute any shell metacharacters in that value.
get_credential() {
  grep -E "^$1=" "$CREDENTIALS_FILE" | head -n1 | cut -d= -f2-
}
CONSOLE_BASIC_AUTH_USER="$(get_credential CONSOLE_BASIC_AUTH_USER)"
CONSOLE_BASIC_AUTH_PASSWORD="$(get_credential CONSOLE_BASIC_AUTH_PASSWORD)"

log "Installing systemd service"
cp "$INSTALL_DIR/deploy/travel-console.service" /etc/systemd/system/travel-console.service
systemctl daemon-reload

log "Configuring Caddy (basic auth reverse proxy on :80)"
CADDY_HASH="$(caddy hash-password --plaintext "$CONSOLE_BASIC_AUTH_PASSWORD")"
# bcrypt hashes can contain '/', so '|' is used as the sed delimiter here.
sed \
  -e "s|__CONSOLE_BASIC_AUTH_USER__|${CONSOLE_BASIC_AUTH_USER:-saulius}|" \
  -e "s|__CONSOLE_BASIC_AUTH_HASH__|$CADDY_HASH|" \
  "$INSTALL_DIR/deploy/Caddyfile.template" > /etc/caddy/Caddyfile

log "Starting services"
systemctl enable --now travel-console
systemctl restart caddy

IP="$(hostname -I | awk '{print $1}')"
log "Done"
echo "Console: http://${IP:-<this-container-ip>}/"
echo
if [ "$anthropic_choice" = "1" ]; then
  echo "Reminder: run 'ant auth login' if you haven't yet — the console will warn on"
  echo "startup (journalctl -u travel-console) until Anthropic credentials are present."
fi
echo "Logs: journalctl -u travel-console -f"
