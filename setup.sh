#!/bin/bash
# setup.sh — Run once on fresh server (DigitalOcean Droplet)
set -e

echo "=== RevHeat Blog Engine Setup ==="

# System updates
echo "Updating system packages..."
apt update && apt upgrade -y

# Python 3.11+ and system fonts for image generation
echo "Installing Python, fonts, and dependencies..."
apt install -y python3 python3-pip python3-venv git fonts-dejavu-core fonts-liberation2

# Create project user (if not exists)
if ! id -u revheat >/dev/null 2>&1; then
    useradd -m -s /bin/bash revheat
    echo "Created user: revheat"
fi

# Setup as revheat user
sudo -u revheat bash << 'USERSETUP'
cd ~

# Clone project (update URL when repo is ready)
if [ ! -d ~/revheat-blog-engine ]; then
    echo "Please clone the repository manually:"
    echo "  git clone <repo-url> ~/revheat-blog-engine"
    exit 1
fi

cd ~/revheat-blog-engine

# Virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Check for .env
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "IMPORTANT: Edit .env with your credentials:"
    echo "  nano ~/revheat-blog-engine/.env"
    echo ""
fi

# Create output directories
mkdir -p output/images logs

echo "Setup complete for revheat user."
USERSETUP

# Setup systemd services
echo "Installing systemd services..."
cp cron/daily_content.service /etc/systemd/system/
cp cron/daily_content.timer /etc/systemd/system/
cp cron/reddit_monitor.service /etc/systemd/system/
cp cron/reddit_monitor.timer /etc/systemd/system/

# Enable and start timers
systemctl daemon-reload
systemctl enable daily_content.timer
systemctl start daily_content.timer
systemctl enable reddit_monitor.timer
systemctl start reddit_monitor.timer

# Security: lock down .env
chmod 600 /home/revheat/revheat-blog-engine/.env 2>/dev/null || true

echo ""
echo "=== Setup Complete ==="
echo "  Daily content engine scheduled for 5 AM EST"
echo "  Reddit monitor scheduled for 5 AM EST"
echo ""
echo "Next steps:"
echo "  1. Edit /home/revheat/revheat-blog-engine/.env with credentials"
echo "  2. Run: sudo -u revheat bash -c 'cd ~/revheat-blog-engine && source venv/bin/activate && python scripts/verify_wordpress.py'"
echo "  3. Run: sudo -u revheat bash -c 'cd ~/revheat-blog-engine && source venv/bin/activate && pytest tests/ -v'"
