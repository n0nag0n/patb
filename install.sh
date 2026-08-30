#!/usr/bin/env bash
# Clone, run this, then `patb` is on PATH.
set -euo pipefail

YES=0
INSTALL_CRON=0
PREFIX="${HOME}/.local"
HOME_DIR=""
BIN_DIR=""

usage() {
  cat <<'EOF'
Usage: ./install.sh [--yes] [--cron] [--home DIR] [--prefix DIR]

  --yes      no prompts (for agents)
  --cron     Linux only: user crontab * * * * * patb tick
             Skip on Grok Bot (no crontab on that computer)
  --home     PATB_HOME (default: /workspace/patb if writable, else ~/.patb)
  --prefix   wrapper prefix (default: ~/.local) → $prefix/bin/patb
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --cron) INSTALL_CRON=1 ;;
    --home) HOME_DIR="$2"; shift ;;
    --prefix) PREFIX="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.9+ and re-run." >&2
  exit 1
fi

PYVER="$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "need Python 3.9+, found $PYVER" >&2
  exit 1
}

if [[ -z "$HOME_DIR" ]]; then
  if [[ -d /workspace && -w /workspace ]]; then
    HOME_DIR="/workspace/patb"
  else
    HOME_DIR="${HOME}/.patb"
  fi
fi

BIN_DIR="${PREFIX}/bin"

ask() {
  local prompt="$1" default="$2"
  if [[ "$YES" == 1 ]]; then
    echo "$default"
    return
  fi
  local ans
  read -r -p "$prompt [$default] " ans || true
  echo "${ans:-$default}"
}

echo "patb install"
echo "  python  : $(command -v python3) ($PYVER)"
echo "  clone   : $ROOT"
echo "  PATB_HOME: $HOME_DIR"
echo "  wrapper : ${BIN_DIR}/patb"
echo

if [[ "$YES" != 1 ]]; then
  go="$(ask "Continue?" "yes")"
  case "$go" in
    y|Y|yes|YES) ;;
    *) echo "aborted"; exit 1 ;;
  esac
fi

mkdir -p "$BIN_DIR" "$HOME_DIR" "$HOME_DIR/vault/private" "$HOME_DIR/vault/inbox"

WRAPPER="${BIN_DIR}/patb"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env python3
import sys
sys.path.insert(0, "${ROOT}/src")
from patb.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
EOF
chmod +x "$WRAPPER"

# Also expose next to the clone for computers that do not use ~/.local/bin
mkdir -p "${ROOT}/bin"
ln -sfn "$WRAPPER" "${ROOT}/bin/patb"

if [[ ! -f "$HOME_DIR/secrets.env" ]]; then
  cat > "$HOME_DIR/secrets.env" <<'EOF'
# patb secrets — do not commit
# HOME_ADDRESS=123 Example St
# AGENT_INBOX_WEBHOOK_URL=https://...
# AGENT_INBOX_WEBHOOK_KEY=
EOF
  chmod 600 "$HOME_DIR/secrets.env"
fi

if [[ ! -f "$HOME_DIR/vault/.gitignore" ]]; then
  printf 'private/\n*.sqlite\nsecrets.env\n' > "$HOME_DIR/vault/.gitignore"
fi

# Seed example vault only when empty of records
if [[ ! -d "$HOME_DIR/vault/protocols" ]]; then
  if [[ -d "$ROOT/vault.example" ]]; then
    if [[ "$YES" == 1 ]] || [[ "$(ask "Copy example vault into $HOME_DIR/vault?" "yes")" =~ ^[yY] ]]; then
      cp -R "$ROOT/vault.example/." "$HOME_DIR/vault/"
    fi
  fi
fi

export PATB_HOME="$HOME_DIR"
"$WRAPPER" reindex >/dev/null || true
"$WRAPPER" core >/dev/null || true

PATH_HINT="export PATH=\"${BIN_DIR}:\$PATH\""
NEED_PATH=1
case ":$PATH:" in
  *":${BIN_DIR}:"*) NEED_PATH=0 ;;
esac

if [[ "$NEED_PATH" == 1 ]]; then
  for rc in "${HOME}/.profile" "${HOME}/.bashrc"; do
    if [[ -f "$rc" ]] && grep -Fqx "$PATH_HINT" "$rc" 2>/dev/null; then
      continue
    fi
    if [[ "$YES" == 1 ]] || [[ "$(ask "Append PATH to $rc?" "yes")" =~ ^[yY] ]]; then
      printf '\n# patb\n%s\n' "$PATH_HINT" >> "$rc"
    fi
  done
fi

HAS_CRONTAB=0
if command -v crontab >/dev/null 2>&1; then
  HAS_CRONTAB=1
fi

if [[ "$INSTALL_CRON" == 1 ]]; then
  if [[ "$HAS_CRONTAB" == 1 ]]; then
    "$WRAPPER" cron install --bin "$WRAPPER" || echo "crontab install failed" >&2
  else
    echo "No crontab on this computer (normal on Grok Bot). Skipping --cron." >&2
    echo "Use Grok routines as the clock: see examples/grok-routine.md" >&2
  fi
elif [[ "$YES" != 1 && "$HAS_CRONTAB" == 1 ]]; then
  if [[ "$(ask "Install minute crontab for patb tick? (Linux/OpenClaw only; not Grok Bot)" "no")" =~ ^[yY] ]]; then
    "$WRAPPER" cron install --bin "$WRAPPER" || true
  fi
fi

echo
echo "Installed."
echo "  this session: $PATH_HINT"
echo "  try:          patb"
echo "  paste:        patb core   (into every Bot profile)"
echo "  get:          patb get KEY"
echo
if [[ -d /workspace ]]; then
  echo "Grok Bot: there is no OS crontab here. Keep your Grok routines on the same"
  echo "schedules as today. Each routine prompt should be only:"
  echo "  patb get job.<name>"
  echo "  follow only that body"
  echo "Do not add a routine that runs every minute with 'patb due'."
  echo "Template: $ROOT/examples/grok-routine.md"
else
  echo "Linux clock (optional): ./install.sh --cron   or   patb cron install"
fi
echo
echo "Add two lines per bot, e.g.  You are Inbox Curator. PATB_AGENT=agent.inbox"
echo "PII and webhook keys: echo VALUE | patb secret set NAME"
echo "Never commit $HOME_DIR/secrets.env or vault/private/"
