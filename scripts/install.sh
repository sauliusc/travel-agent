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

log "Installing Claude Code CLI"
if ! command -v claude >/dev/null 2>&1; then
  # Official installer per code.claude.com/docs/en/setup.md. Agents in this
  # project run via `claude -p` (headless mode) on subscription auth, not
  # an API key -- the Agent SDK / API-key path was dropped because it
  # explicitly can't use claude.ai subscription login for third-party
  # products; `claude -p` itself is Claude Code's own supported way for a
  # subscriber to script their personal usage.
  curl -fsSL https://claude.ai/install.sh | bash || {
    echo "Claude Code install failed — see https://code.claude.com/docs/en/setup.md" >&2
    echo "and install it manually before continuing." >&2
  }
else
  echo "claude already installed, skipping."
fi

mkdir -p "$CREDENTIALS_DIR"
chmod 700 "$CREDENTIALS_DIR"

log "Checking Claude Code login"
CLAUDE_LOGGED_IN=false
if command -v claude >/dev/null 2>&1; then
  if claude auth status --json 2>/dev/null | grep -q '"loggedIn":[[:space:]]*true'; then
    CLAUDE_LOGGED_IN=true
    echo "Already logged in."
  fi
fi
if [ "$CLAUDE_LOGGED_IN" = false ] && command -v claude >/dev/null 2>&1; then
  echo
  echo "Not logged in. Claude Code will print a URL below — open it on any device"
  echo "with a browser, sign in, then paste the code it gives you back here."
  echo
  claude auth login < "$TTY_IN" || {
    echo "Login did not complete — you can run 'claude auth login' manually later." >&2
  }
fi

if [ -f "$CREDENTIALS_FILE" ] && [ "$RECONFIGURE" = false ]; then
  log "Credentials already configured at $CREDENTIALS_FILE (use --reconfigure to redo this)"
else
  log "Configuring credentials (all stored in $CREDENTIALS_FILE, mode 600)"

  read -r -p "GITHUB_TOKEN (fine-grained PAT, Contents/PRs/Workflows/Pages read-write): " GITHUB_TOKEN < "$TTY_IN"
  read -r -p "GITHUB_OWNER [sauliusc]: " GITHUB_OWNER < "$TTY_IN"
  GITHUB_OWNER="${GITHUB_OWNER:-sauliusc}"

  read -r -p "Console basic-auth username [saulius]: " CONSOLE_USER < "$TTY_IN"
  CONSOLE_USER="${CONSOLE_USER:-saulius}"
  read -r -s -p "Console basic-auth password: " CONSOLE_PASSWORD < "$TTY_IN"
  echo

  cat > "$CREDENTIALS_FILE" <<EOF
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
if [ "$CLAUDE_LOGGED_IN" = false ]; then
  echo "Reminder: run 'claude auth login' if it didn't complete above — the console"
  echo "will warn on startup (journalctl -u travel-console) until it's logged in."
fi
echo "Logs: journalctl -u travel-console -f"
