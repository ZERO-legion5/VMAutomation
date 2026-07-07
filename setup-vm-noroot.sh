#!/usr/bin/env bash
# No-root setup for the Wave Monitor on a Linux VM.
# Everything lives in your home directory; the monitor runs inside a tmux
# session that survives SSH disconnects.
#
# Run as your normal user (NO sudo):
#   bash setup-vm-noroot.sh
#
# Prerequisite: tmux must be installed on the system by someone with root.
# Check with:  tmux -V
# If it's missing, ask your VM admin to run:  sudo apt-get install -y tmux
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/wave-monitor"
VENV_DIR="$INSTALL_DIR/venv"
SESSION_NAME="wave-monitor"

echo "==> Stopping any existing tmux session first"
tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

echo "==> Checking for tmux"
if ! command -v tmux >/dev/null 2>&1; then
    echo "ERROR: 'tmux' not found in PATH."
    echo "       tmux is a system package and needs root to install."
    echo "       Ask your VM admin to run:  sudo apt-get install -y tmux"
    exit 1
fi

echo "==> Deploying project to $INSTALL_DIR (overriding existing files)"
mkdir -p "$INSTALL_DIR"
# Force copy everything (including .env), overriding any existing files.
# rsync --delete keeps the install dir in sync; falls back to cp -rf.
rsync -a --delete \
    --exclude='.git' --exclude='__pycache__' --exclude='screenshots' \
    --exclude='state.json' --exclude='venv' \
    "$PROJECT_DIR"/ "$INSTALL_DIR"/ 2>/dev/null || \
cp -rf "$PROJECT_DIR"/. "$INSTALL_DIR"/

# Always carry over .env from the source dir, overriding the install copy.
if [ -f "$PROJECT_DIR/.env" ]; then
    cp -f "$PROJECT_DIR/.env" "$INSTALL_DIR/.env"
fi

echo "==> Checking for .env"
if [ ! -f "$INSTALL_DIR/.env" ]; then
    if [ -f "$INSTALL_DIR/.env.example" ]; then
        cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
        echo "    Created .env from .env.example. EDIT IT NOW with real values:"
        echo "      nano $INSTALL_DIR/.env"
        echo "    Then re-run:  bash $PROJECT_DIR/$(basename "$0")"
        exit 0
    else
        echo "ERROR: no .env and no .env.example found."
        exit 1
    fi
fi
chmod 600 "$INSTALL_DIR/.env"

echo "==> Recreating Python virtualenv"
rm -rf "$VENV_DIR"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "==> Starting monitor in tmux session '$SESSION_NAME'"
tmux new-session -d -s "$SESSION_NAME" -c "$INSTALL_DIR" \
    "$VENV_DIR/bin/python $INSTALL_DIR/monitor.py"

echo
echo "==> Monitor is running in tmux session '$SESSION_NAME'."
echo
echo "Useful commands:"
echo "  tmux attach -t $SESSION_NAME        # view live logs (Ctrl+B then D to detach)"
echo "  tmux kill-session -t $SESSION_NAME  # stop the monitor"
echo "  cd $INSTALL_DIR && nano .env        # edit config"
echo "  bash $PROJECT_DIR/$(basename "$0")    # redeploy + restart after code changes"
echo
echo "To make the monitor auto-start on VM reboot, add to your crontab (crontab -e):"
echo "  @reboot bash $PROJECT_DIR/$(basename "$0")"
