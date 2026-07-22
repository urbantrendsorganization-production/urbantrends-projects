# CLAUDE.md — Marketplace (Portfolio Project)

## What this is

A general-purpose classifieds marketplace (Jiji/Facebook Marketplace style): buyers and sellers of physical goods, listing-scoped chat, price negotiation, category-driven search. **This is a portfolio project** — prioritize clean architecture, readable code, and demonstrable features over exhaustive edge-case handling or premature scale work.

## Stack

- **Backend:** Django + DRF, PostgreSQL, Redis, Celery
- **Frontend:** Next.js (App Router) + TypeScript, Tailwind CSS, mobile-first
- **Infra:** Docker Compose (dev + prod), Caddy reverse proxy, GitHub Actions CI/CD, images pushed to GHCR
- **Auth:** JWT (SimpleJWT) with refresh rotation; email verification via signed one-time link (send through Django's email backend — console backend in dev, SMTP in prod behind an interface)

## Conventions

- Business logic lives in a `services/` layer per app — views/serializers stay thin. State transitions (listing status, offer status) are enforced in ONE place, never scattered across views.
- All models get `created_at` / `updated_at`. Soft-delete only where user-facing (listings), hard-delete elsewhere.
- Every list endpoint is paginated and uses `select_related` / `prefetch_related`. Assume any unoptimized queryset is a bug.
- API is versioned under `/api/v1/`. Consistent error envelope: `{"detail": ..., "code": ...}`.
- Frontend: server components by default, client components only where interactivity requires. No component libraries — Tailwind only (this is a design showcase too).
- Write tests for the state machines and the search filters. Skip testing trivial CRUD.
- Commit per logical unit, conventional commits (`feat:`, `fix:`, `refactor:`).

## Phase rules

- Work strictly in phase order. Do not start a phase until the previous phase's **Done means** criteria all pass.
- Each phase ends with: migrations applied cleanly from scratch, tests green, and the feature demonstrable in the UI.
- If a task reveals missing work from an earlier phase, fix it there first — don't pile workarounds into the current phase.

---

## Phase 0 — Skeleton

Monorepo layout (`backend/`, `frontend/`, `docker-compose.yml`), Django project with split settings (base/dev/prod), custom User model (email as username field, optional phone on profile), Next.js app with Tailwind configured, Postgres + Redis in compose, CI running lint + tests on push.

**Done means:** `docker compose up` gives a working API healthcheck endpoint and a Next.js page consuming it. CI is green.

## Phase 1 — Auth & profiles

Registration, login, JWT refresh, email verification (signed token link with expiry + resend endpoint; console email backend in dev), user profile (display name, avatar, location, joined date). Public profile page.

**Done means:** a user can register, verify, log in, edit their profile, and view another user's public profile. Unverified users cannot post listings.

## Phase 2 — Categories & listings

- `Category` tree (self-FK, max 3 levels) with per-category attribute schemas (JSONB on Category defining fields; JSONB `attributes` on Listing validated against it).
- `Listing`: title, description, price, currency, condition, location, category FK, status enum (`draft / active / reserved / sold / expired`), multi-image upload with ordering and thumbnail generation (Celery task).
- Seller CRUD for own listings; status transitions enforced in the service layer.

**Done means:** a verified user can create a listing with photos and category-specific attributes, edit it, and mark it sold. Invalid attributes for a category are rejected with clear errors. Seed script creates a realistic category tree.

## Phase 3 — Search & browse

- Directory: keyword search (Postgres FTS with `SearchVector` + GIN index), filters for category (including descendants), price range, condition, location, and category-specific attributes (GIN on JSONB).
- Sort: newest, price asc/desc. Cursor pagination.
- Frontend: mobile-first browse grid, filter drawer, listing detail page, category navigation.

**Done means:** browsing 1,000+ seeded listings is fast (no N+1s — verify with `django-debug-toolbar` / query counts in tests), filters combine correctly, and the mobile layout is polished. This phase is the portfolio centerpiece — spend design effort here.

## Phase 4 — Messaging

- `Conversation` scoped to (listing, buyer) — one thread per buyer per listing. `Message` with `read_at`.
- Polling-based frontend chat (SWR revalidation) — no websockets in this phase.
- Unread counts in the navbar; block/report user.

**Done means:** a buyer can message a seller from a listing, both sides see the thread with read state and unread counts, and a reported/blocked user cannot continue messaging.

## Phase 5 — Offers & negotiation

- `Offer` belongs to a conversation: amount, status (`open / countered / accepted / declined / expired`), counter-offer chain.
- Accepting an offer sets the listing to `reserved`; seller marks `sold` to complete. All transitions in the service layer with tests for every allowed/forbidden edge.

**Done means:** full negotiation flow works end-to-end in the UI, and the state machine test suite covers every transition.

## Phase 6 — Trust & polish

- Ratings/reviews (only between users who completed a transaction), report listing, admin moderation queue (Django admin is fine).
- Listing expiry via Celery beat (auto-expire after N days, renewable).
- Empty states, loading skeletons, error pages, OG tags on listing pages, seed data that makes the demo look alive.

**Done means:** the app feels like a finished product in a 5-minute demo: realistic data, no dead ends, reviews visible on profiles.

## Phase 7 — Ship

Production compose file, Caddy config with TLS, GitHub Actions deploy job to Hetzner via GHCR pull, environment docs, README with screenshots and architecture diagram.

**Done means:** live at a public URL, deploys on push to `main`, README good enough that a hiring manager or client understands the project in two minutes.

---

## Out of scope (do not build)

Payments/escrow, websockets, mobile app, i18n, Elasticsearch, microservices. If tempted, add a "future work" note to the README instead.
