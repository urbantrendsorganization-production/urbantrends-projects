# Marketplace

A general-purpose classifieds marketplace (Jiji / Facebook Marketplace style):
buyers and sellers of physical goods, listing-scoped chat, price negotiation,
and category-driven search. Portfolio project — clean architecture over scale.

## Stack

- **Backend:** Django + DRF, PostgreSQL, Redis, Celery
- **Frontend:** Next.js (App Router) + TypeScript, Tailwind CSS (mobile-first)
- **Infra:** Docker Compose (dev + prod), Caddy, GitHub Actions CI/CD → GHCR

## Layout

```
backend/    Django project (split settings, services/ layer, custom User model)
frontend/   Next.js App Router app
docker-compose.yml   Dev stack: backend, frontend, postgres, redis
```

## Quickstart (dev)

```bash
docker compose up --build
```

- API:       http://localhost:8000/api/v1/health/
- Frontend:  http://localhost:3000  (renders the live API health)

The backend service applies migrations on startup; both apps hot-reload from
the mounted source.

## Running checks locally

Backend:

```bash
cd backend
pip install -r requirements-dev.txt
ruff check .
pytest
```

Frontend:

```bash
cd frontend
npm install
npm run lint
npm run build
```

## Project phases

Built in phases (see `CLAUDE.md`). **Phase 0 — Skeleton** is complete:
monorepo layout, split Django settings, custom email-as-username User model,
Tailwind-configured Next.js app, the four-service compose stack, CI, and a
healthcheck at `/api/v1/health/` rendered by the frontend home page.
