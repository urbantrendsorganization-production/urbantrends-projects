# Deployment

Split deploy:

- **Frontend → Vercel** (`https://<project>.vercel.app`)
- **Backend → the box** (Hetzner/VPS) behind Caddy at
  `https://marketplace.urbantrends.dev` — API, admin, media, Postgres, Redis,
  and the Celery worker.

```
Browser ──▶ Vercel (Next.js) ──▶ https://marketplace.urbantrends.dev (Caddy)
                                        ├── /media/*  → file_server (volume)
                                        └── /*        → gunicorn (Django)
                                                         └── Postgres · Redis · Celery
```

---

## 1. Backend on the box

### Prerequisites
- Docker + Docker Compose plugin installed.
- DNS: an **A record** for `marketplace.urbantrends.dev` → the box's public IP.
- Ports **80** and **443** open (Caddy needs both for automatic TLS).

### First deploy
```bash
git clone <repo> marketplace && cd marketplace

cp .env.prod.example .env.prod
# Edit .env.prod: set DJANGO_SECRET_KEY, POSTGRES_PASSWORD, RESEND_API_KEY,
# CORS_ALLOWED_ORIGINS + FRONTEND_URL (your Vercel URL).

docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```
Caddy provisions a Let's Encrypt certificate on first boot. Verify:
```bash
curl https://marketplace.urbantrends.dev/api/v1/health/
```

Seed the category tree and create an admin user:
```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py seed_catalog
docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

### Redeploy (build-on-box)
```bash
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```
Migrations and `collectstatic` run automatically on backend start.

### Notes
- **Static** files are served by WhiteNoise from inside the app; **media**
  (uploads + thumbnails) live on the `mediafiles` volume and are served by Caddy.
- The Celery `worker` shares that volume, so thumbnails appear under `/media/`.
- Logs: `docker compose -f docker-compose.prod.yml logs -f backend caddy worker`.

---

## 2. Frontend on Vercel

1. **Import the repo** in Vercel → set **Root Directory** to `frontend`
   (framework auto-detects Next.js).
2. **Environment variables** (Production + Preview):

   | Key                   | Value                                   |
   | --------------------- | --------------------------------------- |
   | `NEXT_PUBLIC_API_URL` | `https://marketplace.urbantrends.dev`   |
   | `API_URL`             | `https://marketplace.urbantrends.dev`   |

3. **Deploy.** Vercel builds and hosts on `https://<project>.vercel.app`.
4. Put that exact URL into the box's `.env.prod` as `CORS_ALLOWED_ORIGINS` and
   `FRONTEND_URL`, then redeploy the backend (step 1) so the browser is allowed
   to call the API and verification emails link back to the site.

Adding a custom frontend domain later? Just append it to `CORS_ALLOWED_ORIGINS`
(comma-separated) and update `FRONTEND_URL` — no code change.

---

## 3. Checklist

- [ ] DNS A record for `marketplace.urbantrends.dev` resolves to the box.
- [ ] `.env.prod` filled in (secrets, Vercel URL) — never committed.
- [ ] `https://marketplace.urbantrends.dev/api/v1/health/` returns `ok`.
- [ ] Resend domain `urbantrends.dev` verified (SPF/DKIM) for outbound email.
- [ ] Vercel env vars set to the API domain; site loads listings.
- [ ] `CORS_ALLOWED_ORIGINS` + `FRONTEND_URL` match the Vercel URL.
