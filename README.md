# Wave Monitor

Monitors a [VMOS Cloud](https://www.vmoscloud.com/) cloud-phone instance, runs OCR on the screenshot, detects whether a game **wave has been defeated**, and sends you a **Telegram alert** (with the screenshot) when it has. When no wave-defeat keyword is found, the screenshot is posted to a separate **log chat** (a muted channel you can scroll through at your leisure).

Runs as a **long-running `systemd` service on a Google Cloud VM** — far more reliable and on-time than GitHub Actions cron, and no 60-day inactivity disablement.

```
Google Cloud VM (systemd, loops every 5 min)
    │
    ▼
VMOS screenshot API  ──►  download PNG
    │
    ▼
OCR.space API (or Tesseract)  ──►  text
    │
    ├─► "wave defeated" keywords?  ──►  Telegram DM alert + photo
    │
    └─► no match                   ──►  Telegram log channel (muted) + photo
```

## Files

| File | Purpose |
|---|---|
| `signing.py` | VMOS API client with HMAC-SHA256 request signing (extracted from `a.py`). |
| `monitor.py` | Main monitor: screenshot → OCR → wave detection → Telegram. Loops forever when `RUN_INTERVAL_SECONDS > 0`. |
| `.env.example` | Sample environment configuration. Copy to `.env` for the VM. |
| `requirements.txt` | Python dependencies. |
| `wave-monitor.service` | systemd unit file that runs `monitor.py` as a service (root setup). |
| `setup-vm.sh` | One-shot setup script for a Debian/Ubuntu Google Cloud VM (root, systemd). |
| `setup-vm-noroot.sh` | No-root setup: user-space venv + tmux session. Use when your VM user can't `sudo`. |
| `a.py` | Original one-off script (kept for reference). |

## Prerequisites

1. **VMOS Cloud credentials** — your `ACCESS_KEY` and `SECRET_KEY` (the values already in `a.py`).
2. **Pad code(s)** — the instance ID(s) to monitor, e.g. `AC32010970468`.
3. A **Telegram bot** (free) for notifications — see setup below.
4. A **Google Cloud account** with billing enabled (the free `e2-micro` tier in `us-west1`/`us-central1`/`us-east1` is enough for this).

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

## Step 2 — Create a Google Cloud VM

1. Go to the [GCP Console → Compute Engine → VM instances](https://console.cloud.google.com/compute/instances).
2. Click **Create instance**:
   - **Name:** `wave-monitor`
   - **Machine type:** `e2-micro` (free-tier eligible; enough for Tesseract on a single small screenshot).
   - **Boot disk:** Debian 12 (or Ubuntu 22.04+), 10 GB standard persistent disk.
   - **Firewall:** leave defaults — the monitor only makes outbound HTTPS calls, no inbound ports needed.
3. Click **Create** and wait for it to boot.

> Tip: a static external IP is not required, but assigning one (`VM details → Network interfaces → External IP → Reserve`) makes SSH and log scraping easier.

## Step 3 — Put your code and config on the VM

### Option A — clone from git (recommended)

Push this repo to GitHub (private is fine — there are no GitHub Actions minutes involved now), then on the VM:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/<you>/<repo>.git ~/wave-monitor
cd ~/wave-monitor
```

### Option B — upload files directly

```bash
# From your local machine with gcloud installed:
gcloud compute scp --recurse . wave-monitor:~/wave-monitor
```

Files needed at minimum: `signing.py`, `monitor.py`, `requirements.txt`, `.env.example`, `wave-monitor.service`, `setup-vm.sh`.

## Step 4 — Configure `.env`

On the VM, create `.env` from the example and fill in your real values:

```bash
cd ~/wave-monitor
cp .env.example .env
nano .env
```

Set at least:

| Variable | Value |
|---|---|
| `VMOS_ACCESS_KEY` | your VMOS access key |
| `VMOS_SECRET_KEY` | your VMOS secret key |
| `VMOS_HOST` | `api.vmoscloud.com` |
| `PAD_CODES` | `AC32010970468` (comma-separated for multiple) |
| `TELEGRAM_BOT_TOKEN` | your bot token |
| `TELEGRAM_ALERT_CHAT_ID` | your alert chat id |
| `TELEGRAM_LOG_CHAT_ID` | your log chat id (muted channel) |

Optional tuning variables:

| Variable | Default | Notes |
|---|---|---|
| `IMAGE_FORMAT` | `png` | |
| `SETTLE_SECONDS` | `2` | wait between screenshot trigger and download |
| `OCR_SPACE_API_KEY` | *(blank)* | free key from <https://ocr.space/ocrapi>; REQUIRED — the accurate cloud OCR backend. Monitor won't start without it. |
| `OCR_SPACE_ENGINE` | `2` | OCR.space engine: `1` = default, `2` = better for low-res/stylized text |
| `WAVE_DEFEATED_KEYWORDS` | `wave defeated,wave cleared,victory` | comma-separated, case-insensitive |
| `ALERT_COOLDOWN_SECONDS` | `600` | don't re-alert the same pad within this window |
| `RUN_INTERVAL_SECONDS` | `300` | loop interval. `0` = run once and exit (cron mode). |

> **Never commit `.env`** — it contains secrets. `.gitignore` already excludes it.

## Step 5 — Run the setup script

From the project directory on the VM:

```bash
sudo bash setup-vm.sh
```

This script:
- installs Python 3, Tesseract OCR, and git,
- creates a dedicated `wave` system user,
- copies the project to `/opt/wave-monitor`,
- builds a Python virtualenv and installs `requirements.txt`,
- installs and enables the `wave-monitor` systemd service.

If `.env` wasn't created in Step 4, the script will tell you to create it first and exit.

## Step 6 — Verify it's running

```bash
sudo systemctl status wave-monitor
sudo journalctl -u wave-monitor -f
```

You should see a "Starting monitor pass..." log each cycle, plus Telegram deliveries. Screenshots are written to `/opt/wave-monitor/screenshots/` — inspect them to tune OCR.

Useful service commands:

```bash
sudo systemctl restart wave-monitor   # restart after editing .env or code
sudo systemctl stop wave-monitor
sudo systemctl start wave-monitor
sudo journalctl -u wave-monitor --since "10 min ago"
```

---

## No-root setup (tmux) — when your VM user can't `sudo`

If your VM user isn't a sudoer (`sudo: ... I'm afraid I can't do that`), use `setup-vm-noroot.sh` instead. It installs everything into your home directory and runs the monitor inside a `tmux` session that survives SSH disconnects. It needs one system package already present on the VM (ask your VM admin to install it once):

```bash
sudo apt-get install -y tmux   # run once by a sudoer
```

Then from the project directory as your normal user:

```bash
bash setup-vm-noroot.sh
```

The script will create `~/wave-monitor` with a Python venv, build `.env` from `.env.example` on first run (edit it and re-run), and start the monitor in a tmux session named `wave-monitor`.

Useful tmux commands:

```bash
tmux attach -t wave-monitor        # view live logs (Ctrl+B then D to detach)
tmux kill-session -t wave-monitor  # stop the monitor
```

Auto-start on VM reboot — add to your crontab (`crontab -e`):

```
@reboot bash ~/wave-monitor/setup-vm-noroot.sh
```

> Caveat vs. the systemd setup: if the monitor process crashes inside tmux, it stays down until you re-run the script (systemd would auto-restart it). The monitor loop itself catches per-pass errors, so only a hard Python/import failure would stop it.

## Updating the code

After pushing new code to git, pull and redeploy:

```bash
cd ~/wave-monitor
git pull
sudo bash setup-vm.sh     # re-copies to /opt/wave-monitor and restarts the service
```

For a quick code-only restart without re-running the full setup:

```bash
sudo cp -r ~/wave-monitor/{monitor.py,signing.py,requirements.txt} /opt/wave-monitor/
sudo -u wave /opt/wave-monitor/venv/bin/pip install -r /opt/wave-monitor/requirements.txt
sudo systemctl restart wave-monitor
```

---

## Local testing (optional)

Useful for tuning OCR before deploying.

1. Install Python 3.10+.
2. Create your env file and install deps:
   ```bash
   cp .env.example .env
   # edit .env with your real values (OCR_SPACE_API_KEY is required — get a
   # free key at https://ocr.space/ocrapi)
   # set RUN_INTERVAL_SECONDS=0 for a single run, or leave 300 to loop
   pip install -r requirements.txt
   ```
3. Run:
   ```bash
   python monitor.py
   ```
4. Inspect `screenshots/` to see what OCR is working with. Tune `WAVE_DEFEATED_KEYWORDS` until detection is reliable.

---

## How it works

- `signing.py` reproduces the HMAC-SHA256 request signing from `a.py`, reads credentials from the environment, and exposes `fetch_screenshot()` which triggers a screenshot, waits for the render, downloads the PNG.
- `monitor.py` calls `fetch_screenshot()`, runs OCR (OCR.space API if `OCR_SPACE_API_KEY` is set, else local Tesseract), and:
  - **If** any `WAVE_DEFEATED_KEYWORDS` substring is found (case-insensitive), sends an alert + the screenshot to `TELEGRAM_ALERT_CHAT_ID` (your DM).
  - **If not**, posts the screenshot to `TELEGRAM_LOG_CHAT_ID` (your muted log channel).
  - Suppresses duplicate alerts for the same pad within `ALERT_COOLDOWN_SECONDS` using `state.json` (during cooldown, screenshots still go to the log chat).
- When `RUN_INTERVAL_SECONDS > 0` (the default, set by the systemd service), `monitor.py` loops forever; an unexpected error in one pass never kills the service. `state.json` persists on the VM disk, so cooldown dedup survives across restarts.
- The `wave-monitor.service` systemd unit runs the monitor under a dedicated `wave` user and auto-restarts on crash or VM reboot.

## Tuning OCR accuracy

The monitor uses the **OCR.space** free API (25,000 requests/month — you use ~9,000/mo at 300/day) via `OCR_SPACE_API_KEY` in `.env`. It's far more accurate than Tesseract on stylized game fonts and uses no local RAM/CPU, which makes it ideal for a 1 GB VM. Get a free key at <https://ocr.space/ocrapi> — **the monitor will not start without it.**

- `OCR_SPACE_ENGINE=2` (default) is tuned for low-resolution / stylized text. Switch to `1` if you see worse results.
- Inspect the screenshots in `/opt/wave-monitor/screenshots/` to verify what OCR sees.
- Tune `WAVE_DEFEATED_KEYWORDS` to the exact phrases shown on a defeat (e.g. `STAGE CLEAR`, `WAVE COMPLETE`).

## Notes & limitations

- **Timing is exact.** Unlike GitHub Actions cron, the `time.sleep(RUN_INTERVAL_SECONDS)` loop fires on a predictable cadence (no multi-minute drift), and `systemd` `Restart=always` keeps it alive across crashes and reboots.
- **Cost.** An `e2-micro` in a free-tier region costs nothing; otherwise a few USD/month. The VM is idle >99% of the time.
- **VMOS rate limits** — verify the screenshot API tolerates a call every 5 min. If you see throttling (`code != 200`), raise `SETTLE_SECONDS` or increase `RUN_INTERVAL_SECONDS`.
- **Credentials** are never in the repo — only in the VM's `/opt/wave-monitor/.env` (mode `600`, owned by the `wave` user).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `VMOS_ACCESS_KEY and VMOS_SECRET_KEY must be set` | `.env` missing or not loaded. Confirm `/opt/wave-monitor/.env` exists and `systemctl restart wave-monitor`. |
| Service won't start | `sudo journalctl -u wave-monitor -n 50` for the Python traceback. Usually a missing dep or bad `.env` value. |
| `sudo: ... I'm afraid I can't do that` | Your VM user isn't a sudoer. Use the [no-root (tmux) setup](#no-root-setup-tmux--when-your-vm-user-cant-sudo) instead, or get sudo via the GCP serial console / a default sudoer account. |
| Telegram messages not arriving | Verify `TELEGRAM_BOT_TOKEN` and chat ids; the bot must have been messaged/added to the chat first. For channels, the bot must be an admin. Check logs for `Telegram error <code>`. |
| OCR finds nothing | Inspect `/opt/wave-monitor/screenshots/`. Set `OCR_SPACE_API_KEY` in `.env` for the more accurate OCR.space backend. Tune keywords. |
| Wave never detected | The on-screen text may not contain your keywords. Add the exact phrase shown (e.g. `STAGE CLEAR`, `WAVE COMPLETE`) to `WAVE_DEFEATED_KEYWORDS`. |
| Loop stopped unexpectedly | `systemctl` should auto-restart it. If it didn't, check `Restart=` in the unit and `journalctl` for the exit reason. |
| Cooldown not respected | `state.json` lives on disk at `/opt/wave-monitor/state.json` and persists normally. Only a deleted/overwritten file resets it. |
