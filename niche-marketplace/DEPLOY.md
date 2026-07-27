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

The box keeps the whole monorepo checked out at `/opt/urbantrends-projects/`
(same as onboarding-kit); deploy from the project directory inside it. Media
lives **outside** the checkout, so `git pull` — or a stray `git clean` — can
never touch user uploads.

```bash
sudo mkdir -p /opt/marketplace/media

git clone git@github.com:urbantrendsorganization-production/urbantrends-projects.git \
  /opt/urbantrends-projects
cd /opt/urbantrends-projects/niche-marketplace

cp .env.prod.example .env.prod
chmod 600 .env.prod
```

Edit `.env.prod`: `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `RESEND_API_KEY`,
`CORS_ALLOWED_ORIGINS` + `FRONTEND_URL` (the Vercel URL), and pin `IMAGE_TAG`
to the SHA tag you intend to run. Private packages need a GHCR login first:
`echo "$GHCR_PAT" | docker login ghcr.io -u <github-user> --password-stdin`.

### Preflight: check the config before starting

A malformed value in `.env.prod` fails Django's system checks, which run
*before* `migrate`. The container exits 1, `restart: unless-stopped` turns that
into a crash loop, and it surfaces as 502s from Caddy on every request —
including CORS preflights, which makes it look like a CORS problem. Catch it
first:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml run --rm api \
  python manage.py check --deploy
```

Non-zero exit on any ERROR. The one that has actually bitten:

```
(corsheaders.E014) Origin '…/api/v1/auth/login/' in CORS_ALLOWED_ORIGINS should not have path
```

An origin is **scheme + host + optional port only** — comma-separated, no path,
no trailing slash. It names where the *browser page* is served from (the Vercel
URL), never the API being called.

Then start it:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

### One-time: enable drop-in vhosts

The host Caddy originally kept every vhost in a single `/etc/caddy/Caddyfile`
with no `conf.d`. Adding the import once turns each stack's vhost into a
file-copy instead of an edit to the file serving all six sites:

```bash
TS=$(date +%F-%H%M%S)
sudo cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$TS
sudo mkdir -p /etc/caddy/conf.d
printf '\n# Per-service vhosts, one file per stack.\nimport /etc/caddy/conf.d/*.caddy\n' \
  | sudo tee -a /etc/caddy/Caddyfile >/dev/null
sudo caddy validate --config /etc/caddy/Caddyfile   # rejects a bad config before reload
```

If `validate` fails, restore `/etc/caddy/Caddyfile.bak.$TS` and add the vhost
below directly to `/etc/caddy/Caddyfile` instead. The failure to expect: a
Caddyfile written in single-site shorthand (bare directives, no
`example.com { … }` wrapper) parses a top-level `import` as a directive inside
that implicit site.

### Add the vhost

Drop-in — no restart, and the other stacks keep serving through the reload:
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
docker compose -f docker-compose.prod.yml exec api python manage.py seed_listings
```

### Verify media serving

`seed_listings` creates **no images** — the coloured tiles in the browse grid
are `ListingCard`'s placeholder for a listing with no photo, not a broken image
pipeline. Seeded data therefore proves nothing about media, and the only way to
exercise the path is a real upload:

1. Sign in on the site → **Sell** → post a listing with a photo.
2. The Celery `worker` generates the thumbnail; both files land under
   `/opt/marketplace/media/listings/`.

```bash
ls -R /opt/marketplace/media | head          # files present on the host
curl -sI https://marketplace.urbantrends.dev/media/listings/<file>.jpg | head -3
```

A `200` proves Caddy's `file_server` served it off disk: in production
`DEBUG=False`, and `config/urls.py` only routes `MEDIA_URL` through Django when
`DEBUG` is on — so if the request had fallen through to gunicorn it would 404.

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

   Leave **Sensitive** off. Neither is a secret — `NEXT_PUBLIC_*` is compiled
   into the client bundle by definition — and sensitive values can't be read
   back in the dashboard, which is exactly what you want to inspect when
   debugging a wrong URL.

   `NEXT_PUBLIC_*` is inlined at **build time**, so setting it does nothing to
   an already-built deployment. Redeploy with **"Use existing Build Cache"
   unchecked**. `lib/config.ts` fails the build outright if it is missing,
   rather than silently baking in the `localhost:8000` dev fallback.

3. **Deploy.** Already live at `https://urbantrends-projects.vercel.app`,
   rebuilding on every push to `main`. Confirm the value took:
   ```bash
   curl -s https://urbantrends-projects.vercel.app/ | grep -c 'localhost:8000'  # 0
   ```
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
- [ ] `manage.py check --deploy` passes against `.env.prod` before first `up -d`.
- [ ] `8088` is still free on the box (`ss -ltnp | grep 8088`).
- [ ] `import /etc/caddy/conf.d/*.caddy` present in `/etc/caddy/Caddyfile`.
- [ ] `/etc/caddy/conf.d/marketplace.caddy` installed; `caddy validate` passes.
- [ ] The other sites still answer after the reload (not just the new one).
- [ ] `docker compose ps` shows `api` **healthy**.
- [ ] `https://marketplace.urbantrends.dev/api/v1/health/` returns `ok`.
- [ ] Resend domain `urbantrends.dev` verified (SPF/DKIM) for outbound email.
- [ ] Vercel env vars set to the API domain, **rebuilt without build cache**;
      site loads listings and sign-in works.
- [ ] `CORS_ALLOWED_ORIGINS` + `FRONTEND_URL` match the Vercel URL — origins are
      scheme + host only, no path.
- [ ] A listing posted **with a photo** renders its image, and
      `curl -sI …/media/listings/<file>` returns `200`.
