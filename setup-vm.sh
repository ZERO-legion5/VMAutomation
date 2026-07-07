#!/usr/bin/env bash
# Sets up the Wave Monitor on a Google Cloud VM (Debian/Ubuntu).
# Run as root on a fresh VM, e.g.:
#   sudo bash setup-vm.sh
set -euo pipefail

INSTALL_DIR="/opt/wave-monitor"
SERVICE_USER="wave"

echo "==> Installing system packages (Python, Tesseract, etc.)"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip tesseract-ocr git

echo "==> Creating service user '$SERVICE_USER'"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "==> Deploying project to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
# Copy repo files alongside this script into the install dir.
cp -r . "$INSTALL_DIR"/
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"

echo "==> Creating Python virtualenv"
sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "==> .env not found. Copy .env.example and fill in real values:"
    echo "    sudo -u $SERVICE_USER cp $INSTALL_DIR/.env.example $INSTALL_DIR/.env"
    echo "    sudo -u $SERVICE_USER nano $INSTALL_DIR/.env"
    echo "    Then re-run this script or start the service manually."
    exit 1
fi
chown "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR/.env"
chmod 600 "$INSTALL_DIR/.env"

echo "==> Installing systemd service"
cp "$INSTALL_DIR/wave-monitor.service" /etc/systemd/system/wave-monitor.service
systemctl daemon-reload
systemctl enable wave-monitor.service

echo "==> Starting wave-monitor service"
systemctl restart wave-monitor.service

echo
echo "Done. Useful commands:"
echo "  sudo systemctl status wave-monitor"
echo "  sudo journalctl -u wave-monitor -f"
echo "  sudo systemctl restart wave-monitor"
