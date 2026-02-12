#!/bin/bash
# Oracle Cloud VM setup script for Coinbase Grid Bot
# Run as: sudo bash setup.sh

set -e

echo "=== Coinbase Grid Bot - Oracle Cloud Setup ==="

# Update system
echo "[1/6] Updating system packages..."
dnf update -y -q

# Install Python 3.12
echo "[2/6] Installing Python 3.12..."
dnf install -y -q python3.12 python3.12-pip git

# Create bot user
echo "[3/6] Creating bot user..."
useradd -r -m -s /bin/bash gridbot 2>/dev/null || true

# Clone repo
echo "[4/6] Cloning repository..."
sudo -u gridbot bash -c '
  cd /home/gridbot
  if [ -d coinbase-grid-bot ]; then
    cd coinbase-grid-bot && git pull
  else
    git clone https://github.com/jcoleman-droid/coinbase-grid-bot.git
    cd coinbase-grid-bot
  fi
  python3.12 -m pip install --user -e ".[dev]"
'

# Create data directory
sudo -u gridbot mkdir -p /home/gridbot/coinbase-grid-bot/data

# Create environment file
echo "[5/6] Setting up environment..."
if [ ! -f /home/gridbot/coinbase-grid-bot/.env ]; then
  cp /home/gridbot/coinbase-grid-bot/.env.example /home/gridbot/coinbase-grid-bot/.env
  chown gridbot:gridbot /home/gridbot/coinbase-grid-bot/.env
  chmod 600 /home/gridbot/coinbase-grid-bot/.env
  echo "  -> Created .env file. Edit it with your API keys when ready for live trading."
fi

# Install systemd service
echo "[6/6] Installing systemd service..."
cat > /etc/systemd/system/gridbot.service << 'UNIT'
[Unit]
Description=Coinbase Grid Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=gridbot
Group=gridbot
WorkingDirectory=/home/gridbot/coinbase-grid-bot
Environment=PATH=/home/gridbot/.local/bin:/usr/bin
EnvironmentFile=/home/gridbot/coinbase-grid-bot/.env
Environment=GRIDBOT_CONFIG_PATH=config/cloud.yaml
ExecStart=/home/gridbot/.local/bin/python3.12 -m src.main run --dashboard
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable gridbot

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Commands:"
echo "  sudo systemctl start gridbot    # Start the bot"
echo "  sudo systemctl stop gridbot     # Stop the bot"
echo "  sudo systemctl status gridbot   # Check status"
echo "  journalctl -u gridbot -f        # View live logs"
echo ""
echo "Dashboard: http://<your-vm-ip>:8080"
echo ""
echo "To update the bot later:"
echo "  cd /home/gridbot/coinbase-grid-bot && sudo -u gridbot git pull"
echo "  sudo systemctl restart gridbot"
