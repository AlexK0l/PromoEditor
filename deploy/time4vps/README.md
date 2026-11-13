## Генерация промпта и форматы CorelDRAW

После обновления приложение формирует проверяемый промпт из формы, затем оба размера в PNG, JPEG и послойном SVG. Для SVG→PNG/JPEG используется CairoSVG и системная библиотека `libcairo2`. Скрипт `update.sh` устанавливает Cairo runtime только при отсутствии и перезапускает только PromoEditor. Caddy и RegionalResearch не меняются. ZIP содержит фото и логотипы, встроенные в SVG — учитывайте конфиденциальность.

# PromoEditor on the EXISTING Time4VPS (RegionalResearch is kept intact)

## Editing the live server .env from Windows using PowerShell/SCP

The active systemd environment is /etc/promoeditor/promoeditor.env (root-owned mode 0600), NOT the .env in the Git checkout. It holds OpenAI keys and authentication secrets. Never commit or share it, and avoid OneDrive-synced directories. You need Windows OpenSSH scp.exe and SSH access to the VPS.

1. In **Windows PowerShell**, enter your actual VPS IP and download a copy. These commands assume SSH login as root is permitted.

   ~~~powershell
   $VPS_IP = "YOUR_VPS_IP"
   $LOCAL_DIR = Join-Path $env:USERPROFILE "PromoEditor-secrets"
   New-Item -ItemType Directory -Force $LOCAL_DIR | Out-Null
   scp.exe "root@${VPS_IP}:/etc/promoeditor/promoeditor.env" "$LOCAL_DIR\promoeditor.env"
   notepad.exe "$LOCAL_DIR\promoeditor.env"
   ~~~

   Edit as UTF-8 **without BOM**, preserving KEY=value lines. For changing the PromoEditor login password, use provision_auth.py on the VPS rather than manually altering PROMO_PASSWORD_HASH and PROMO_SESSION_SECRET.

2. On the **VPS**, open SSH as root and create a non-world-readable staging directory plus a dated backup BEFORE upload:

   ~~~bash
   install -d -o root -g root -m 700 /root/promoeditor-secrets
   cp -p /etc/promoeditor/promoeditor.env "/root/promoeditor-secrets/backup-$(date -u +%Y%m%d-%H%M%S).env"
   ~~~

3. In **Windows PowerShell**, upload to the **root-only staging directory**, not straight over the live file:

   ~~~powershell
   scp.exe "$LOCAL_DIR\promoeditor.env" "root@${VPS_IP}:/root/promoeditor-secrets/promoeditor.env.new"
   ~~~

4. On the **VPS**, atomically install as root:root, mode 0600, remove the staged copy, and restart **only** PromoEditor:

   ~~~bash
   install -o root -g root -m 600 /root/promoeditor-secrets/promoeditor.env.new /etc/promoeditor/promoeditor.env.next
   mv -f /etc/promoeditor/promoeditor.env.next /etc/promoeditor/promoeditor.env
   rm -f /root/promoeditor-secrets/promoeditor.env.new
   systemctl restart promoeditor
   systemctl is-active promoeditor
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/login
   ~~~

   Expect active plus HTTP 200 for the login page. Anonymous /api/config returns HTTP 401 when auth is enabled. If the service fails, restore the latest dated backup using install -o root -g root -m 600 and restart only promoeditor. Caddy and RegionalResearch do not need to restart.

5. After checking the site, delete the Windows secret file if it is no longer required. If your SSH account cannot log in as root, use a private 0700 directory in your SSH user's home for staging and sudo on the VPS for the protected original; NEVER place the secrets in world-readable /tmp.

## Migration on an existing VPS: password ONLY, no username

PromoEditor now offers its own single-password login page. This is similar to RegionalResearch, but it uses a separate secret and cookie; you can enter the same password string if you wish. **Do not copy, read, or change RegionalResearch credentials.**

An EXISTING Time4VPS deployment with a Caddy popup asking for username `promo` requires this migration after the app update. Run as root on the VPS:

    bash /opt/promoeditor/deploy/time4vps/update.sh
    bash /opt/promoeditor/deploy/time4vps/switch_to_password_login.sh

Enter a password of at least 8 characters when asked (twice, hidden). The script stores only a PBKDF2 password hash and a new HMAC session signing secret in `/etc/promoeditor/promoeditor.env` (mode 0600). It backs up this environment file and the imported `/etc/caddy/promoeditor.caddy`. Then it enables FastAPI session protection and **proves** that anonymous `/api/config` returns HTTP 401 and `/login` returns HTTP 200. **Only after these checks** is the OLD `basic_auth` block removed from the imported PromoEditor Caddy file. Caddy configuration is validated before reload; any validation/reload failure restores the previous PromoEditor site. The existing RegionalResearch service and Caddy host block are never edited.

After migration open the normal PromoEditor HTTPS URL in a private/incognito browser tab. You should see a page with one password field, not a username popup. A successful login grants a signed Secure HttpOnly cookie valid for up to 12 hours; the top menu has «Выйти». The app checks every API request, static asset and generated file. If password-only auth cannot be configured, it fails closed and Caddy Basic Auth remains active.

Changing the password later (root only; rotates the signing secret and invalidates previous sessions):

    python3 /opt/promoeditor/deploy/time4vps/provision_auth.py /etc/promoeditor/promoeditor.env
    systemctl restart promoeditor

Never publish your password, its hash, server session secret or OpenAI API key. Note that local non-VPS/dev runs can keep PROMO_AUTH_ENABLED=0; production must use PROMO_AUTH_ENABLED=1. Fresh installations in step 2 now prompt for the password before the service is exposed through Caddy. The step 4 initial configure_caddy.sh refuses to publish a site until app-level auth is working. Do NOT rerun initial configure_caddy.sh for an existing site.

This is the recommended deployment method for the owner's **already configured** Ubuntu Time4VPS server. It is **different** from `deploy/README_VPS.md`: that older Docker Compose recipe starts a second Caddy container and therefore **must not be run on this VPS**, where the existing system Caddy already owns ports 80/443.

## Existing host (historical, from 2026-11-09 records; verify before acting)

| Component | Existing RegionalResearch | New PromoEditor |
| --- | --- | --- |
| VPS | Time4VPS, Ubuntu 24.04, historical IPv4 (kept outside this public repo) | **same VPS** |
| App | Node.js + systemd `regionalresearch` | Python FastAPI + **separate** systemd `promoeditor` |
| Internal listener | `127.0.0.1:10000` | `127.0.0.1:18080` |
| Browser address | `https://<DASHED_VPS_IP>.sslip.io/` | `https://promoeditor.<DASHED_VPS_IP>.sslip.io/` |
| HTTPS | **Existing host Caddy** `/etc/caddy/Caddyfile` | Additive imported Caddy site, **no second proxy** |
| Authentication | RegionalResearch's own one-password session form | FastAPI password-only form (independent session) |
| App files | `/opt/regionalresearch` | `/opt/promoeditor` |
| Data | RegionalResearch SQLite/checkpoints/results | `/var/lib/promoeditor/jobs`, entirely separate |
| Secrets | Existing RegionalResearch `.env` (do not read/change) | `/etc/promoeditor/promoeditor.env`, mode `0600` |

The hostname uses free `sslip.io` DNS (an IP-based name); this is not a domain purchase. The observed VPS had **1.9 GiB RAM and no swap** and RegionalResearch supported parallel jobs. Memory capacity may have changed. **Do not deploy during a heavy research run** and check free RAM before enabling image generation. No existing research should be stopped or restarted.

The scripts have **not been run on the live VPS**. They do not access it automatically. SSH access and current server state must be verified locally.

## 0. First, inspect the server (NO changes)

Connect in your own terminal using your existing SSH key/account (never send keys, passwords, or OpenAI API keys in chat):

```bash
ssh root@YOUR_VPS_IP
```

On the VPS:

```bash
systemctl is-active regionalresearch
systemctl is-active caddy
ss -ltnp | grep -E ':(80|443|10000|18080)[[:space:]]' || true
free -h
swapon --show
getent ahostsv4 promoeditor.YOUR-DASHED-VPS-IP.sslip.io
```

Expect RegionalResearch and Caddy `active`, port 10000 **localhost only**, no service on 18080, DNS mapping to your server public IPv4. Stop and investigate if these differ. Avoid pasting secrets from configuration files into chat.

## 1. Bootstrap from GitHub

Run as the SSH user with sudo privileges (root shell shown in historical logs):

```bash
apt-get update && apt-get install -y git
mkdir -p /root/promoeditor-bootstrap
# Directory must be empty if pre-created.
git clone --branch main https://github.com/AlexK0l/PromoEditor.git /root/promoeditor-bootstrap
cd /root/promoeditor-bootstrap
bash deploy/time4vps/preflight.sh
```

Read the preflight report. If `/root/promoeditor-bootstrap` is not empty, do not overwrite it; use a different directory instead. `preflight.sh` is read-only.

## 2. Install isolated FastAPI + systemd

```bash
cd /root/promoeditor-bootstrap
bash deploy/time4vps/install.sh
systemctl status promoeditor --no-pager -l
# /login should be HTTP 200 and anonymous /api/config HTTP 401
curl -sSI http://127.0.0.1:18080/login | head -n 10
```

The installer sets up `/opt/promoeditor`, a dedicated non-login account, a virtualenv, and `/etc/systemd/system/promoeditor.service`. It uses **one Uvicorn worker**, port **18080 bound to loopback**, a dedicated output directory and a memory ceiling (`MemoryMax=800M`). Existing Caddy, RegionalResearch, SQLite, SSH and firewall are not modified. A new installation prompts for a password, which is stored only as a hash. No API call to OpenAI is made during installation.

Try the local demo **without an OpenAI key first**. Only if this works, continue to HTTPS.

## 3. Put the OpenAI key only on the server (optional)

Do not put secrets into GitHub or chat. On the VPS:

```bash
nano /etc/promoeditor/promoeditor.env
chmod 600 /etc/promoeditor/promoeditor.env
systemctl restart promoeditor
```

Set `OPENAI_API_KEY` locally when ready. You can leave it blank for a free, deterministic preview. Paid image generation is not run by installer or tests. Before using paid features, set usage alerts/budget controls in your OpenAI Platform account and make an explicit low-cost smoke test. This app currently does **not** enforce a hard monetary cap, and rate limits are process-local.

## 4. Add a SECOND HTTPS hostname to the EXISTING Caddy

No new reverse proxy or public ports. On the VPS:

```bash
bash /opt/promoeditor/deploy/time4vps/configure_caddy.sh
```

The fresh-install script verifies FastAPI password protection (anonymous `/api/config` must be HTTP 401, `/login` must be HTTP 200). It asks for a hostname and expected IP, adds only an imported Caddy site for that hostname with HTTPS and the 72 MB body limit, and **does not add Caddy Basic Auth**. This is possible because the FastAPI application now protects the entire page, its files and API.

Already installed? Use `switch_to_password_login.sh` described above, NOT the initial configure script.
## 5. Verify both apps after setup

```bash
systemctl is-active regionalresearch caddy promoeditor
curl -fsS http://127.0.0.1:18080/api/config
# Anonymous public website should redirect HTTP 303 to /login after certificate issuance.
curl -sSI https://promoeditor.YOUR-DASHED-VPS-IP.sslip.io/ | head -n 10
# Check that the original RegionalResearch remains accessible.
curl -sSI https://YOUR-DASHED-VPS-IP.sslip.io/ | head -n 10
ss -ltnp | grep -E ':(80|443|10000|18080)[[:space:]]' || true
```

In a browser, open `https://promoeditor.<DASHED_VPS_IP>.sslip.io/`, enter only the password you set on the VPS, run a **non-AI** demo, and download 4:3 and 9:16 PNG. Open original RegionalResearch in a separate tab to confirm it still works. If DNS or TLS issuance fails, check firewall/Caddy logs; do not turn off authentication or replace the original Caddy config as a workaround.

## Updates, diagnostics and backup

```bash
# Only PromoEditor restarts; refuses to overwrite uncommitted source edits.
bash /opt/promoeditor/deploy/time4vps/update.sh
# App diagnostics
journalctl -u promoeditor -n 80 --no-pager
systemctl status promoeditor --no-pager
# Shared reverse proxy diagnostics
journalctl -u caddy -n 50 --no-pager
# Existing project checks (read-only)
systemctl is-active regionalresearch
```

Keep `/etc/promoeditor/promoeditor.env` (server-only secret) and `/var/lib/promoeditor/jobs` separate from Git. Job files may contain commercial or personal data; the app expires generated links after two hours but only cleans old folders when new jobs run. For mandatory timed deletion, add a dedicated cleanup timer after the initial deployment. Back up original Caddyfile automatically before each host configuration change; **never overwrite existing RegionalResearch files or databases**.

### RAM and capacity

The historical Ubuntu VPS had just **1.9 GiB total RAM, with zero swap**. Running RegionalResearch research jobs and image generation together could cause out-of-memory errors. The PromoEditor service defaults to one worker and `800M` maximum memory. Test **one non-AI image job at a time**, inspect `free -h` and `journalctl -u promoeditor`, then decide whether to resize the VPS or add swap. Do not increase RegionalResearch's parallel limit without capacity evidence.

### Rollback

If PromoEditor is broken, stop **only** its service with `systemctl stop promoeditor`; RegionalResearch remains running. For a Caddy problem, retrieve the timestamped backup from `/root/promoeditor-backups` and restore **only** `/etc/caddy/Caddyfile`, validate and reload Caddy. The configuration script already tries to roll back on syntax/reload errors. Avoid `docker compose up` or any Docker command from the alternative `deploy/README_VPS.md` on this shared VPS.
