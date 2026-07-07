"""Wave monitor: screenshot -> OCR -> detect wave defeat -> Telegram.

Designed to run as a long-running service on a Google Cloud VM (systemd).

Run with:
    python monitor.py

Configuration via environment variables (see .env.example). OCR is used ONLY
to detect wave-defeat keywords. If matched, a high-priority alert (with the
screenshot) is sent to TELEGRAM_ALERT_CHAT_ID. If NOT matched, the screenshot
is posted to TELEGRAM_LOG_CHAT_ID (falls back to the alert chat if not set).

Set RUN_INTERVAL_SECONDS > 0 (default 300) to loop forever — ideal for a
systemd service. Set it to 0 to run a single pass (e.g. for cron).
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

import signing  # noqa: E402  (import after env loaded so credentials exist)

# --- Config from env ---
PAD_CODES = [c.strip() for c in os.environ.get("PAD_CODES", "").split(",") if c.strip()]
IMAGE_FORMAT = os.environ.get("IMAGE_FORMAT", "png")
SETTLE_SECONDS = int(os.environ.get("SETTLE_SECONDS", "2"))

# How often (in seconds) to run the monitor loop. 0 = run once and exit.
RUN_INTERVAL_SECONDS = int(os.environ.get("RUN_INTERVAL_SECONDS", "300"))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALERT_CHAT_ID = os.environ.get("TELEGRAM_ALERT_CHAT_ID", "")
TELEGRAM_LOG_CHAT_ID = os.environ.get("TELEGRAM_LOG_CHAT_ID", "") or TELEGRAM_ALERT_CHAT_ID

# Comma-separated phrases that indicate a wave has been defeated.
# Example: "wave defeated,wave cleared,victory,level complete"
WAVE_DEFEATED_KEYWORDS = [
    k.strip().lower() for k in os.environ.get("WAVE_DEFEATED_KEYWORDS", "wave defeated,wave cleared,victory").split(",")
    if k.strip()
]

# OCR backend: OCR.space API (free, 25k requests/month). Needs no local
# RAM/CPU and is far more accurate on stylized game fonts than Tesseract.
OCR_SPACE_API_KEY = os.environ.get("OCR_SPACE_API_KEY", "")
if not OCR_SPACE_API_KEY:
    raise RuntimeError(
        "OCR_SPACE_API_KEY must be set in the environment. "
        "Get a free key at https://ocr.space/ocrapi"
    )
# OCR.space engine: 1 = default, 2 = better for low-resolution / stylized text.
OCR_SPACE_ENGINE = os.environ.get("OCR_SPACE_ENGINE", "2")
# Optional: set to a base URL proxy if api.ocr.space is blocked. Leave blank.
OCR_SPACE_API_URL = os.environ.get("OCR_SPACE_API_URL", "https://api.ocr.space/parse/image")

# State file to avoid re-alerting on the same wave repeatedly.
STATE_FILE = os.environ.get("STATE_FILE", "state.json")


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


# --- Telegram helpers ---
def telegram_send(text, chat_id=None, parse_mode=None):
    if not TELEGRAM_BOT_TOKEN:
        log("TELEGRAM_BOT_TOKEN not set; skipping message.")
        return
    chat_id = chat_id or TELEGRAM_ALERT_CHAT_ID
    if not chat_id:
        log("No Telegram chat id configured; skipping message.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=15)
        if resp.status_code != 200:
            log(f"Telegram error {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        log(f"Telegram request failed: {e}")


def telegram_send_photo(filepath, chat_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return
    chat_id = chat_id or TELEGRAM_ALERT_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(filepath, "rb") as f:
            resp = requests.post(url, data={"chat_id": chat_id}, files={"photo": f}, timeout=60)
        if resp.status_code != 200:
            log(f"Telegram photo error {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        log(f"Telegram photo request failed: {e}")


# --- OCR ---
def _ocr_space(filepath):
    """Run OCR via the OCR.space free API. Returns recognized text."""
    import base64

    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"

    payload = {
        "apikey": OCR_SPACE_API_KEY,
        "base64Image": data_url,
        "language": "eng",
        "isOverlayRequired": "false",
        "scale": "true",
        "detectOrientation": "true",
        "OCREngine": OCR_SPACE_ENGINE,
    }
    resp = requests.post(OCR_SPACE_API_URL, data=payload, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    if body.get("IsErroredOnProcessing"):
        raise RuntimeError(f"OCR.space error: {body.get('ErrorMessage', body)}")
    parts = []
    for r in body.get("ParsedResults", []) or []:
        parts.append(r.get("ParsedText", "") or "")
    return "\n".join(parts).strip()


def run_ocr(filepath):
    """Run OCR on an image via the OCR.space API and return the recognized text."""
    return _ocr_space(filepath)


def is_wave_defeated(text):
    lowered = text.lower()
    for kw in WAVE_DEFEATED_KEYWORDS:
        if kw in lowered:
            return True, kw
    return False, None


# --- State (to avoid duplicate alerts) ---
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_alerted": {}}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"last_alerted": {}}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        log(f"Could not save state: {e}")


# --- Main ---
def run_once():
    """Run a single monitor pass over all pad codes."""
    if not PAD_CODES:
        log("PAD_CODES not set. Exiting.")
        sys.exit(1)

    log(f"Starting monitor pass for {len(PAD_CODES)} pad(s).")
    state = load_state()

    try:
        results = signing.fetch_screenshot(PAD_CODES, fmt=IMAGE_FORMAT, settle_seconds=SETTLE_SECONDS)
    except Exception as e:
        log(f"Screenshot fetch failed: {e}")
        telegram_send(f"[Monitor] Screenshot fetch failed: {e}")
        return

    for result in results:
        pad_code = result["pad_code"]
        filepath = result["filepath"]
        error = result["error"]

        if error:
            log(f"[{pad_code}] Screenshot error: {error}")
            telegram_send(f"[{pad_code}] Screenshot error: {error}")
            continue

        log(f"[{pad_code}] Screenshot saved: {filepath}")

        try:
            ocr_text = run_ocr(filepath)
        except Exception as e:
            log(f"[{pad_code}] OCR failed: {e}")
            # Still post the photo to the log chat so you can see what happened.
            telegram_send_photo(filepath, chat_id=TELEGRAM_LOG_CHAT_ID)
            continue

        log(f"[{pad_code}] OCR text (first 200 chars): {ocr_text[:200]!r}")

        defeated, matched_kw = is_wave_defeated(ocr_text)

        if not defeated:
            # No wave-defeat keyword found: post the screenshot to the log chat.
            telegram_send_photo(filepath, chat_id=TELEGRAM_LOG_CHAT_ID)
            continue

        # Wave defeated: avoid re-alerting within a cooldown window.
        last_alerted_ts = state.get("last_alerted", {}).get(pad_code, 0)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        cooldown = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "600"))
        if now_ts - last_alerted_ts < cooldown:
            log(f"[{pad_code}] Wave defeated ('{matched_kw}') but in cooldown; not alerting.")
            # Post to log chat instead so it's still visible without spamming alerts.
            telegram_send_photo(filepath, chat_id=TELEGRAM_LOG_CHAT_ID)
            continue

        alert_msg = "WAVE DEFEATED!"
        log(f"[{pad_code}] {alert_msg} (matched '{matched_kw}')")
        telegram_send(alert_msg, chat_id=TELEGRAM_ALERT_CHAT_ID)
        if filepath and os.path.exists(filepath):
            telegram_send_photo(filepath, chat_id=TELEGRAM_ALERT_CHAT_ID)
            # Also mirror the defeat to the log chat so it's always visible there.
            telegram_send_photo(filepath, chat_id=TELEGRAM_LOG_CHAT_ID)

        state.setdefault("last_alerted", {})[pad_code] = now_ts
        save_state(state)


def main():
    if RUN_INTERVAL_SECONDS <= 0:
        run_once()
        return

    # Long-running loop mode — ideal for a systemd service on a VM.
    log(f"Loop mode: running every {RUN_INTERVAL_SECONDS}s. Press Ctrl+C to stop.")
    while True:
        try:
            run_once()
        except Exception as e:
            # Never let an unexpected error kill the service.
            log(f"Pass failed with unexpected error: {e}")
        log(f"Sleeping {RUN_INTERVAL_SECONDS}s until next pass...")
        time.sleep(RUN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
