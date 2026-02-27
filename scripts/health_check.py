#!/usr/bin/env python3
"""System health check — run hourly via cron."""

import os
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()


def check_last_run() -> tuple[bool, str]:
    """Verify daily engine ran within last 26 hours."""
    last_run_file = Path("logs/last_run.txt")
    if not last_run_file.exists():
        # Fallback to log file modification time
        log_file = Path("logs/revheat.log")
        if not log_file.exists():
            return False, "No last_run.txt or log file found"
        stat = log_file.stat()
        last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        age = datetime.now(timezone.utc) - last_modified
        if age > timedelta(hours=26):
            return False, f"Last log activity was {age.total_seconds()/3600:.1f} hours ago"
        return True, "OK (from log mtime)"

    lines = last_run_file.read_text().strip().split("\n")
    if len(lines) < 2:
        return False, "last_run.txt is malformed"

    status = lines[0].strip()
    timestamp_str = lines[1].strip()
    message = lines[2].strip() if len(lines) > 2 else ""

    try:
        last_run_time = datetime.fromisoformat(timestamp_str)
        age = datetime.now(timezone.utc) - last_run_time
    except ValueError:
        return False, f"Cannot parse last_run timestamp: {timestamp_str}"

    if status == "FAILURE":
        return False, f"Last run FAILED {age.total_seconds()/3600:.1f}h ago: {message}"

    if age > timedelta(hours=26):
        return False, f"Last successful run was {age.total_seconds()/3600:.1f} hours ago"

    return True, f"OK — last run {age.total_seconds()/3600:.1f}h ago"


def check_wordpress_api() -> tuple[bool, str]:
    """Verify WP REST API is accessible."""
    try:
        import requests
        wp_url = os.getenv("WP_URL", "https://revheat.com")
        resp = requests.get(f"{wp_url}/wp-json/wp/v2/", timeout=10)
        if resp.status_code == 200:
            return True, "OK"
        return False, f"WordPress API returned {resp.status_code}"
    except Exception as e:
        return False, f"Cannot reach WordPress: {e}"


def check_disk_space() -> tuple[bool, str]:
    """Warn if disk > 80% full."""
    import shutil
    total, used, free = shutil.disk_usage("/")
    pct_used = used / total * 100
    if pct_used > 80:
        return False, f"Disk {pct_used:.1f}% full ({free // (1024**3)}GB free)"
    return True, f"Disk {pct_used:.1f}% used"


def check_draft_queue() -> tuple[bool, str]:
    """Alert if drafts are piling up."""
    try:
        from src.wp_publisher import WordPressPublisher
        wp = WordPressPublisher()
        drafts = wp.get_draft_queue()
        if len(drafts) > 7:
            return False, f"{len(drafts)} drafts queued (Ken: review needed!)"
        return True, f"{len(drafts)} drafts in queue"
    except Exception as e:
        return True, f"Could not check drafts: {e}"


def send_alert(message: str):
    """Send email alert on failure."""
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    to_email = os.getenv("NOTIFICATION_EMAIL", "kglundin@gmail.com")

    if not smtp_user:
        print(f"ALERT: {message}")
        return

    try:
        msg = MIMEText(message)
        msg["Subject"] = "RevHeat Blog Engine ALERT"
        msg["From"] = smtp_user
        msg["To"] = to_email

        with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587"))) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
    except Exception as e:
        print(f"Could not send alert email: {e}")


def main():
    print(f"Health check: {datetime.now(timezone.utc).isoformat()}")
    alerts = []

    checks = [
        ("Last Run", check_last_run),
        ("Disk Space", check_disk_space),
    ]

    # Only check WP if credentials are configured
    if os.getenv("WP_URL"):
        checks.append(("WordPress API", check_wordpress_api))

    for name, check_fn in checks:
        ok, msg = check_fn()
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {name}: {msg}")
        if not ok:
            alerts.append(f"{name}: {msg}")

    if alerts:
        send_alert("Health check failures:\n\n" + "\n".join(alerts))
        return 1

    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
