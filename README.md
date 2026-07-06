# Wave Monitor

Monitors a [VMOS Cloud](https://www.vmoscloud.com/) cloud-phone instance every 5 minutes, runs OCR on the screenshot, detects whether a game **wave has been defeated**, and sends you a **Telegram alert** (with the screenshot) when it has. When no wave-defeat keyword is found, the screenshot is posted to a separate **log chat** (a muted channel you can scroll through at your leisure).

```
GitHub Actions (every 5 min)
    │
    ▼
VMOS screenshot API  ──►  download PNG
    │
    ▼
Tesseract OCR  ──►  text
    │
    ├─► "wave defeated" keywords?  ──►  Telegram DM alert + photo
    │
    └─► no match                   ──►  Telegram log channel (muted) + photo
```

## Files

| File | Purpose |
|---|---|
| `signing.py` | VMOS API client with HMAC-SHA256 request signing (extracted from `a.py`). |
| `monitor.py` | Main monitor: screenshot → OCR → wave detection → Telegram. |
| `.env.example` | Sample environment configuration. Copy to `.env` for local runs. |
| `requirements.txt` | Python dependencies. |
| `.github/workflows/monitor.yml` | GitHub Actions workflow that runs every 5 minutes. |
| `a.py` | Original one-off script (kept for reference). |

## Prerequisites

1. **VMOS Cloud credentials** — your `ACCESS_KEY` and `SECRET_KEY` (the values already in `a.py`).
2. **Pad code(s)** — the instance ID(s) to monitor, e.g. `AC32010970468`.
3. A **Telegram bot** (free) for notifications — see setup below.

---

## Step 1 — Create a Telegram bot and get chat ids

1. Open Telegram, talk to **@BotFather**, send `/newbot`, pick a name and username. Copy the **bot token** (looks like `123456:ABC-...`).
2. **For the alert chat (your DM):** start a private chat with your new bot and send it any message (e.g. `/start`).
3. **For the log chat (muted channel):** create a new Telegram channel (or group), then add the bot to it as an administrator so it can post. Mute the channel on your phone so the every-5-min screenshots don't notify you.

### Getting the chat ids

Telegram chats are addressed by a numeric id. There are two easy ways to find them:

**Option A — using `getUpdates` (no extra bot needed):**

1. Send a message in each chat (the DM with the bot, and the log channel).
2. Open this URL in a browser, replacing `<TOKEN>` with your bot token:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. In the JSON response, find each chat under `result[].message.chat` and copy the `id` field.
   - Your DM will look like `"chat": {"id": 123456789, "type": "private"}`
   - A channel will look like `"chat": {"id": -1001234567890, "type": "channel"}` (note the leading `-100`)

**Option B — using @userinfobot:**

1. In the DM with your bot, forward a message to **@userinfobot** — it replies with that chat's id.
2. For a channel, forward a message from the channel to @userinfobot (channels allow forwarding if not restricted).

> For channels, the id is usually negative and starts with `-100` (e.g. `-1001234567890`). Copy it **exactly**, including the sign. The bot **must be an admin** of the channel to send messages there.

You now have:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALERT_CHAT_ID` — your DM id (wave-defeated alerts, unmuted)
- `TELEGRAM_LOG_CHAT_ID` — the muted channel id (every-run screenshots; leave blank to reuse the alert chat)

## Step 2 — Create a GitHub repository

1. Go to [github.com/new](https://github.com/new) and create a **new repository**.
   - For **unlimited free Actions minutes**, make it **public**. The screenshot secrets stay hidden either way.
   - For a private repo, you get 2,000 free Actions minutes/month (~6.6 hours of runtime — fine if each run is ~90s).
2. Push these files to the repo (root level):
   ```
   signing.py
   monitor.py
   requirements.txt
   .env.example
   .gitignore
   .github/workflows/monitor.yml
   ```
   You can drag-and-drop via the GitHub web UI, or:
   ```bash
   git init
   git add .
   git commit -m "Wave monitor"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```

   > **Never commit `.env`** — it contains secrets. `.gitignore` already excludes it.

## Step 3 — Add secrets to the repository

In your repo: **Settings → Secrets and variables → Actions → New repository secret**.

Add these **secrets** (sensitive values):

| Secret name | Value |
|---|---|
| `VMOS_ACCESS_KEY` | your VMOS access key |
| `VMOS_SECRET_KEY` | your VMOS secret key |
| `VMOS_HOST` | `api.vmoscloud.com` |
| `PAD_CODES` | `AC32010970468` (comma-separated for multiple) |
| `TELEGRAM_BOT_TOKEN` | your bot token |
| `TELEGRAM_ALERT_CHAT_ID` | your alert chat id |
| `TELEGRAM_LOG_CHAT_ID` | your log chat id (muted channel) |

Under **Settings → Secrets and variables → Actions → Variables** (non-sensitive config), add these **variables** (optional — defaults are baked in):

| Variable name | Example value |
|---|---|
| `IMAGE_FORMAT` | `png` |
| `SETTLE_SECONDS` | `2` |
| `WAVE_DEFEATED_KEYWORDS` | `wave defeated,wave cleared,victory,level complete` |
| `ALERT_COOLDOWN_SECONDS` | `600` |

> Secrets are encrypted and never visible in logs. Variables are visible but non-sensitive.

## Step 4 — Run it

1. In your repo: **Actions** tab → select **"Wave Monitor"** workflow.
2. Click **"Run workflow"** (manual trigger) to test immediately.
3. Check the run logs — you'll see OCR output and Telegram delivery status.
4. If it works, the schedule (`*/5 * * * *`) takes over automatically. GitHub Actions cron is **best-effort** and can be delayed 1–15 min under load.

### Artifacts

Each run uploads the screenshots to **run artifacts** (Actions tab → run → Artifacts at the bottom). Use these to verify OCR accuracy and tune your keywords. Artifacts are kept 7 days.

---

## Local testing (optional)

Useful for tuning OCR before deploying.

1. Install Python 3.10+.
2. Install Tesseract:
   - Windows: installer from <https://github.com/UB-Mannheim/tesseract/wiki>
   - macOS: `brew install tesseract`
   - Linux: `sudo apt-get install tesseract-ocr`
3. Create your env file and install deps:
   ```bash
   cp .env.example .env
   # edit .env with your real values
   pip install -r requirements.txt
   ```
4. Run:
   ```bash
   python monitor.py
   ```
5. Inspect `screenshots/` to see what OCR is working with. Tune `WAVE_DEFEATED_KEYWORDS` until detection is reliable, then push those values as repo Variables.

---

## How it works

- `signing.py` reproduces the HMAC-SHA256 request signing from `a.py`, reads credentials from the environment, and exposes `fetch_screenshot()` which triggers a screenshot, waits for the render, downloads the PNG.
- `monitor.py` calls `fetch_screenshot()`, runs Tesseract OCR, and:
  - **If** any `WAVE_DEFEATED_KEYWORDS` substring is found (case-insensitive), sends an alert + the screenshot to `TELEGRAM_ALERT_CHAT_ID` (your DM).
  - **If not**, posts the screenshot to `TELEGRAM_LOG_CHAT_ID` (your muted log channel).
  - Suppresses duplicate alerts for the same pad within `ALERT_COOLDOWN_SECONDS` using `state.json` (during cooldown, screenshots still go to the log chat).
- The GitHub Actions workflow restores `state.json` from cache so cooldown dedup survives between runs.

## Tuning OCR accuracy

Tesseract is decent but not perfect for game UI. Tips:

- **Upscaling** is already enabled for images under 1000px wide.
- If text is stylized, try `pytesseract.image_to_string(img, config="--psm 6")` (edit `monitor.py`).
- For much better accuracy, replace Tesseract with **EasyOCR** (`pip install easyocr`) — heavier but far better on game fonts. The `run_ocr()` function is the only place to change.
- Use the uploaded artifact screenshots to verify what Tesseract sees.

## Notes & limitations

- **GitHub Actions cron is not exact.** Expect ±5–15 min drift, and runs can be skipped during GitHub outages. This is fine for "wave cleared" alerts but not for sub-minute precision.
- **Scheduled workflows are disabled after 60 days of repo inactivity.** Push any commit to re-enable.
- **State persistence** uses the Actions cache (7-day retention). If the cache is evicted, cooldown dedup resets — worst case you get one extra alert. Acceptable for this use case.
- **VMOS rate limits** — verify the screenshot API tolerates a call every 5 min. If you see throttling (`code != 200`), raise `SETTLE_SECONDS` or increase the cron interval.
- **Credentials** are never in the repo — only in GitHub secrets or your local `.env`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `VMOS_ACCESS_KEY and VMOS_SECRET_KEY must be set` | Secret not added to repo, or not named exactly `VMOS_ACCESS_KEY` / `VMOS_SECRET_KEY`. |
| Telegram messages not arriving | Verify `TELEGRAM_BOT_TOKEN` and chat ids; the bot must have been messaged/added to the chat first. For channels, the bot must be an admin. Check the run log for `Telegram error <code>`. |
| OCR finds nothing | Download the artifact screenshot, check what's actually visible. Tune keywords. Game text may be stylized — consider EasyOCR. |
| Wave never detected | The on-screen text may not contain your keywords. Add the exact phrase shown (e.g. `STAGE CLEAR`, `WAVE COMPLETE`) to `WAVE_DEFEATED_KEYWORDS`. |
| Run is delayed / skipped | Normal GitHub Actions cron behavior. See "Notes & limitations". |
| Cooldown not respected | The Actions cache for `state.json` may have been evicted; this is expected occasionally. |

<!-- trigger workflow re-index -->

