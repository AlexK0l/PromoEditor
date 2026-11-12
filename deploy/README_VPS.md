# PromoEditor: installation on a Linux VPS

> **НЕ применять эту Docker Compose схему к Time4VPS с RegionalResearch.** На сервере уже запущен Caddy на 80/443; используйте [time4vps/README.md](time4vps/README.md) для второго приложения через существующий прокси и systemd.

This recipe prepares a **private, password-protected** instance. It does not deploy to a VPS automatically. It assumes Ubuntu 22.04+/Debian 12+, Docker Engine with the Compose v2 plugin, a domain name, and working DNS. Do not point it at a shared reverse proxy without checking which service already owns ports 80/443.

## Prerequisites

- A Linux VPS with at least **2 vCPU, 2 GiB RAM and 10 GiB free disk** (4 GiB RAM is preferable for image-heavy jobs). Non-root sudo account with SSH-key access.
- A domain/subdomain such as `promo.example.com`, with an **A** (and, if used, correct AAAA) record pointing to the VPS public address. Allow inbound TCP **80** and **443** in the VPS provider firewall; limit SSH to trusted addresses.
- Install Docker Engine and the Compose plugin from the [official Docker Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/) or [Debian instructions](https://docs.docker.com/engine/install/debian/). Check `docker version` and `docker compose version`.
- Docker requires elevated privileges. Run `sudo docker compose ...` if your account is not configured for Docker, and remember membership in the `docker` group is effectively root-equivalent.

## 1. Clone

```bash
sudo mkdir -p /opt/promoeditor
sudo chown "$USER":"$USER" /opt/promoeditor
git clone https://github.com/AlexK0l/PromoEditor.git /opt/promoeditor
cd /opt/promoeditor
cp deploy/app.env.example deploy/app.env
cp deploy/caddy.env.example deploy/caddy.env
chmod 600 deploy/app.env deploy/caddy.env
```

If `/opt/promoeditor` was pre-created and is not empty, clone into a new directory instead.

## 2. Configure DNS and password

Open `deploy/caddy.env` with a terminal text editor and set `PROMO_DOMAIN` to your **real domain** and `PROMO_AUTH_USER` to your chosen login.

Generate a **new password hash interactively** (do not put the plaintext password in chat, GitHub, a command-line flag, or shell history):

```bash
docker run --rm -it caddy:2.10.2-alpine caddy hash-password
```

You will be prompted for a password. Copy the printed bcrypt hash into `PROMO_AUTH_HASH`, surrounded by single quotes, e.g. `PROMO_AUTH_HASH='$2a$14$...'`. Never put a plaintext password here. The hashes contain `$` symbols that need single quotes in Compose env files.

Optional: open `deploy/app.env` and set `OPENAI_API_KEY` (from your own OpenAI developer account), then configure project usage alerts/budget restrictions in the OpenAI dashboard. With no key set, the free demo and deterministic poster generation still work; paid AI actions will be unavailable. **Never paste the API key in a chat or commit it to GitHub.**

## 3. Start

```bash
cd /opt/promoeditor
./deploy/deploy.sh
```

The installer refuses to start with example hostname/password placeholders, checks Compose configuration, builds the image, and launches two containers. Only Caddy publishes 80/443. App port 8000 is accessible **only within Docker's private network**. Caddy obtains and renews TLS certificates automatically.

## 4. Verify

```bash
docker compose -f compose.vps.yaml ps
docker compose -f compose.vps.yaml logs --tail=100 app caddy
# Expected without credentials: HTTP 401 (HTTPS certificate must be valid)
curl -I https://YOUR_REAL_DOMAIN/
```

Open `https://YOUR_REAL_DOMAIN/` in your browser. It will request the login and password. Once authenticated, generate a **non-AI** demo in both formats and download the ZIP; this verifies forms, the engine, and stored results. When a valid OpenAI API key and billing limits are configured, run one **small paid test** and check usage. The OpenAI call is not automatically run by the installer.

## Maintenance

```bash
cd /opt/promoeditor
./deploy/update.sh
# Show live logs
docker compose -f compose.vps.yaml logs -f --tail=100
# Restart services
docker compose -f compose.vps.yaml restart
# Stop services, keep all named volumes
docker compose -f compose.vps.yaml down
```

Do **not** use `down -v` unless you intend to delete generated files and Caddy's persisted TLS certificate state. Back up `deploy/app.env` and `deploy/caddy.env` securely outside the repository (not into GitHub). The `promo_results` volume is temporary user output, not an archive.

### Security and operating limits

- The whole interface, generated file URLs and APIs are protected by Caddy **HTTP Basic Auth over HTTPS**. This is suitable for a small trusted team, not an open multi-tenant SaaS. For public user accounts and quotas, add application-level authentication and persistent per-user billing controls first.
- Do not expose **8000** in your public firewall or Docker port mappings. `compose.vps.yaml` intentionally has only `expose` for the application.
- The application runs as non-root with a read-only filesystem, a dedicated writable output volume, restricted capabilities, memory/CPU limits, and log rotation.
- The built-in request limit is **per process**, not a hard OpenAI spending cap, and all requests arriving from Caddy can share one upstream IP. The default `PROMO_REQUESTS_PER_HOUR=10` should be considered a safety brake, not billing protection. Set account/project limits and usage alerts in OpenAI separately before enabling paid generation.
- Uploaded original files are not persisted by the app. Generated results may contain commercial or personal information and are stored in a server volume for up to 2 hours; the current application performs cleanup **when generating a new result**, not by a background timer. If strict data retention is necessary, add a scheduled cleanup service.
- If ports 80/443 are already owned by Nginx, Apache, Traefik or Caddy, do not start this Compose file as-is. Integrate the app as a private upstream behind the existing HTTPS/auth proxy instead.
- Installing Docker may update your server firewall routing. Double-check UFW and the hosting provider's firewall, and only open the required ports.

## Troubleshooting

**TLS not issued:** Check DNS `A`/`AAAA`, firewall ports 80/443, and `docker compose ... logs caddy`. Do not disable TLS or Basic Auth as a workaround.

**401 Unauthorized:** This is expected before entering credentials. If correct credentials fail, generate a new bcrypt hash, place it inside single quotes in `deploy/caddy.env`, and run `docker compose -f compose.vps.yaml up -d --force-recreate caddy`.

**503/502 or unhealthy app:** Inspect app logs, available RAM, the volume permissions and `docker compose -f compose.vps.yaml ps`. Python packages and fonts are included inside the Docker image.

**OpenAI generation unavailable:** The key may be empty or invalid, the model may be unavailable to the account, or billing may be disabled. Test the free demo first; never print the key to debug logs.
