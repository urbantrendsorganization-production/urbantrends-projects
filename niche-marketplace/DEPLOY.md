# Deployment

Split deploy:

- **Frontend → Vercel** — live at `https://urbantrends-projects.vercel.app`,
  auto-deploying from `main`.
- **Backend → the shared UrbanTrends box** (Hetzner), behind the **host Caddy**
  at `https://marketplace.urbantrends.dev` — API, admin, media, Postgres,
  Redis, and the Celery worker.

```
Browser ──▶ Vercel (Next.js) ──▶ https://marketplace.urbantrends.dev
                                   host Caddy (systemd, shared by all stacks)
                                        ├── /media/*  → file_server (/opt/marketplace/media)
                                        └── /*        → 127.0.0.1:8088 (gunicorn)
                                                         └── Postgres · Redis · Celery
```

## How this stack fits the box

The box already runs onboardkit, keja, sitechat, rentflow and urbantrends. The
conventions they all follow — and this stack follows too:

| Convention                             | Why                                                     |
| -------------------------------------- | ------------------------------------------------------- |
| Images **pulled from GHCR**             | No source or build toolchain on the box                  |
| **No Caddy in the stack**               | A stack Caddy would collide with the host Caddy on :80/:443 |
| API published on **127.0.0.1 only**     | The host Caddy is the single public entry point          |
| Postgres/Redis **unpublished**          | Internal compose network only                            |
| `restart: unless-stopped`               | Survives reboots                                         |

Loopback ports in use: 3000-3002, 5000, 8000-8002, 8083, 8086 (onboardkit),
8087 (keja), 9100-9101. **Marketplace takes 8088.**

---

## 1. Backend on the box

### Prerequisites
- DNS: an **A record** for `marketplace.urbantrends.dev` → the box's public IP.
- The host Caddy is already installed and serving the other stacks. Ports 80
  and 443 are already open for it — this stack opens nothing.
- A GHCR image exists: push to `main` runs
  `.github/workflows/niche-marketplace.yml`, which publishes
  `ghcr.io/urbantrendsorganization-production/urbantrends-projects/marketplace-backend:main`.

### First deploy
```bash
sudo mkdir -p /opt/marketplace/media && cd /opt/marketplace

# Only the deploy files are needed on the box — not the source tree.
curl -O https://raw.githubusercontent.com/urbantrendsorganization-production/urbantrends-projects/main/niche-marketplace/docker-compose.prod.yml
curl -O https://raw.githubusercontent.com/urbantrendsorganization-production/urbantrends-projects/main/niche-marketplace/.env.prod.example
mv .env.prod.example .env.prod

# Edit .env.prod: DJANGO_SECRET_KEY, POSTGRES_PASSWORD, RESEND_API_KEY,
# CORS_ALLOWED_ORIGINS + FRONTEND_URL (your Vercel URL).

# The image is public? Skip this. Private packages need a GHCR login first:
#   echo "$GHCR_PAT" | docker login ghcr.io -u <github-user> --password-stdin

docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

Add the vhost to the host Caddy (drop-in, no restart of other stacks):
```bash
sudo cp infra/Caddyfile /etc/caddy/conf.d/marketplace.caddy
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```
Caddy provisions the Let's Encrypt certificate on first request. Verify:
```bash
# Straight at the container. Both headers are required: prod redirects plain
# HTTP to https (301), and the Host must be in DJANGO_ALLOWED_HOSTS or Django
# answers 400 — a bare `curl 127.0.0.1:8088` will NOT work.
curl -fsS http://127.0.0.1:8088/api/v1/health/ \
  -H 'Host: localhost' -H 'X-Forwarded-Proto: https'
# => {"status":"ok","version":"0.1.0","services":{"database":"up","redis":"up"}}

curl -fsS https://marketplace.urbantrends.dev/api/v1/health/  # public, via Caddy
docker compose -f docker-compose.prod.yml ps                  # api → healthy
```
Caddy passes the original `Host` and sets `X-Forwarded-Proto` itself, so the
public URL needs no special headers.

Seed the category tree and create an admin user:
```bash
docker compose -f docker-compose.prod.yml exec api python manage.py seed_catalog
docker compose -f docker-compose.prod.yml exec api python manage.py createsuperuser
```

### Redeploy
CI publishes a new `:main` image on every push to `main`. On the box:
```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```
Migrations and `collectstatic` run automatically on `api` start.

### Rollback
Every build is also tagged with its commit SHA. Pin it and re-up:
```bash
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=sha-<full-commit-sha>/' .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

### Notes
- **Static** files are served by WhiteNoise from inside the app. **Media**
  (uploads + thumbnails) is bind-mounted at `/opt/marketplace/media` and served
  directly by the host Caddy, so uploads never touch the gunicorn workers.
- The Celery `worker` shares that mount, so thumbnails appear under `/media/`.
- No `beat` service: nothing schedules periodic tasks yet. Phase 6 (listing
  expiry) is what will need one.
- Logs: `docker compose -f docker-compose.prod.yml logs -f api worker`, and
  `journalctl -u caddy -f` for the proxy.

---

## 2. Frontend on Vercel

1. **Import the repo** in Vercel → set **Root Directory** to
   `niche-marketplace/frontend` (framework auto-detects Next.js).
2. **Environment variables** (Production + Preview):

   | Key                   | Value                                   |
   | --------------------- | --------------------------------------- |
   | `NEXT_PUBLIC_API_URL` | `https://marketplace.urbantrends.dev`   |
   | `API_URL`             | `https://marketplace.urbantrends.dev`   |

3. **Deploy.** Already live at `https://urbantrends-projects.vercel.app`,
   rebuilding on every push to `main`.
4. Put that exact URL into the box's `.env.prod` as `CORS_ALLOWED_ORIGINS` and
   `FRONTEND_URL`, then redeploy the backend (step 1) so the browser is allowed
   to call the API and verification emails link back to the site.

Adding a custom frontend domain later? Just append it to `CORS_ALLOWED_ORIGINS`
(comma-separated) and update `FRONTEND_URL` — no code change.

---

## 3. Checklist

- [ ] DNS A record for `marketplace.urbantrends.dev` resolves to the box.
- [ ] `:main` image published to GHCR by CI.
- [ ] `.env.prod` filled in (secrets, Vercel URL) — never committed.
- [ ] `8088` is still free on the box (`ss -ltnp | grep 8088`).
- [ ] `/etc/caddy/conf.d/marketplace.caddy` installed; `caddy validate` passes.
- [ ] `docker compose ps` shows `api` **healthy**.
- [ ] `https://marketplace.urbantrends.dev/api/v1/health/` returns `ok`.
- [ ] Resend domain `urbantrends.dev` verified (SPF/DKIM) for outbound email.
- [ ] Vercel env vars set to the API domain; site loads listings.
- [ ] `CORS_ALLOWED_ORIGINS` + `FRONTEND_URL` match the Vercel URL.
