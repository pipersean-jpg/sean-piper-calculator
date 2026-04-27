#!/usr/bin/env bash
# Run once from the torrentbot/ directory: bash launchd/install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_DST="$HOME/Library/LaunchAgents/com.torrentbot.bot.plist"

echo "=== TorrentBot installer ==="
echo "Bot directory: $BOT_DIR"

# ── Python ────────────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
    echo "ERROR: Homebrew not found. Install it first: https://brew.sh"
    exit 1
fi

if ! command -v python3.11 &>/dev/null; then
    echo "Installing Python 3.11 via Homebrew..."
    brew install python@3.11
fi

PYTHON=$(command -v python3.11)
echo "Python: $PYTHON ($($PYTHON --version))"

# ── Virtualenv + deps ─────────────────────────────────────────────────────────
if [ ! -d "$BOT_DIR/.venv" ]; then
    $PYTHON -m venv "$BOT_DIR/.venv"
fi
source "$BOT_DIR/.venv/bin/activate"
pip install -q -r "$BOT_DIR/requirements.txt"
VENV_PYTHON="$BOT_DIR/.venv/bin/python"

# ── Config files ──────────────────────────────────────────────────────────────
mkdir -p "$BOT_DIR/logs"

if [ ! -f "$BOT_DIR/config.yaml" ]; then
    cp "$BOT_DIR/config.yaml.example" "$BOT_DIR/config.yaml"
    echo "Created config.yaml — fill in your settings before starting."
fi

if [ ! -f "$BOT_DIR/.env" ]; then
    cp "$BOT_DIR/.env.example" "$BOT_DIR/.env"
    echo "Created .env — add TELEGRAM_TOKEN and ANTHROPIC_API_KEY."
fi

# ── launchd plist ─────────────────────────────────────────────────────────────
mkdir -p "$HOME/Library/LaunchAgents"
sed \
    -e "s|REPLACE_PYTHON|$VENV_PYTHON|g" \
    -e "s|REPLACE_DIR|$BOT_DIR|g" \
    "$SCRIPT_DIR/com.torrentbot.plist" > "$PLIST_DST"

echo ""
echo "=== Done. Next steps: ==="
echo "  1. Edit $BOT_DIR/.env"
echo "  2. Edit $BOT_DIR/config.yaml"
echo "  3. launchctl load   $PLIST_DST"
echo "  4. launchctl start  com.torrentbot.bot"
echo ""
echo "To check logs:"
echo "  tail -f $BOT_DIR/logs/bot.log"
