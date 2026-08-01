# BookNasi

Appointment booking with M-Pesa deposits, for Kenyan salons and barbershops.

An [UrbanTrends](https://urbantrends.dev) product. Runs standalone at `booknasi.co.ke` and as the first vertical module behind `/site`.

---

## The problem

Salons already have a notebook, and the notebook works. What it doesn't solve:

1. **No-shows.** A three-hour braiding slot booked and not turned up for is a chair sitting empty and a stylist earning nothing.
2. **Phone tag.** Bookings arrive on WhatsApp and calls all day, mid-service, and get forgotten.
3. **No memory.** No record of who came, what they had done, or who hasn't been back in three months.

BookNasi takes an **M-Pesa deposit at booking time**. A no-show becomes partial payment instead of a total loss, and unserious bookings get filtered out before they occupy a slot. The calendar is table stakes; the deposit is the product.

---

## Features

**Booking**
- Public mobile-first booking page per shop
- Server-computed availability from opening hours, staff schedules, leave, buffers and per-staff service durations
- Database-enforced protection against double-booking
- Three-tap walk-in entry for staff

**Payments**
- M-Pesa STK push for deposits at confirmation
- Slot held pending payment with automatic release on timeout
- Idempotent callback handling
- Per-service deposit rules: flat, percentage, or none

**Operations**
- Staff day view built for speed
- Owner dashboard: today's bookings, no-show rate, revenue per staff, repeat client rate
- SMS/WhatsApp confirmations and reminders

**Multi-tenant**
- One organization, one subscription, unlimited shops beneath it
- Clients belong to the organization, so a regular visiting two branches keeps one history
- Embeddable widget + public API for white-label integration

---

## Stack

- **Backend** — Django, Django REST Framework, `uv`
- **Database** — PostgreSQL with `btree_gist`
- **Cache & queue** — Redis
- **Async** — Celery + Beat
- **Frontend** — Next.js, TypeScript
- **Payments** — Safaricom Daraja (M-Pesa STK push)
- **Infra** — Docker Compose, GitHub Actions → GHCR → Hetzner, Caddy

---

## Getting started

**Requires:** Docker + Compose, `uv`, Node 20+

```bash
git clone git@github.com:muchemiwamuyu/booknasi.git
cd booknasi

cp .env.example .env        # fill in DB, Redis, Daraja and SMS credentials

uv sync
docker compose up -d        # postgres, redis, api, worker, beat

uv run python manage.py migrate
uv run python manage.py createsuperuser
```

Frontend:

```bash
cd web
npm install
npm run dev
```

API on `http://localhost:8000`, web on `http://localhost:3000`.

### Tests

```bash
uv run python manage.py test
uv run ruff check . && uv run ruff format .
```

Concurrency tests around availability and payment callbacks are part of the suite, not optional extras.

---

## Environment

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django secret |
| `DEBUG` | `0` in anything but local |
| `DATABASE_URL` | Postgres connection string |
| `REDIS_URL` | Cache + Celery broker |
| `MPESA_CONSUMER_KEY` / `MPESA_CONSUMER_SECRET` | Daraja app credentials |
| `MPESA_SHORTCODE` / `MPESA_PASSKEY` | Till/paybill and STK passkey |
| `MPESA_CALLBACK_URL` | Public HTTPS callback endpoint |
| `SMS_API_KEY` / `SMS_SENDER_ID` | Messaging provider |
| `ALLOWED_HOSTS` | Comma-separated |

Never commit a filled `.env`. Sandbox credentials are still credentials.

---

## Architecture notes

**Availability is derived, never stored.** It's computed server-side from opening hours minus staff hours, leave, existing appointments, buffers and staff-specific service durations, then cached per staff-day in Redis and invalidated on any write that touches that day.

**Double-booking is prevented in Postgres, not Python.** An exclusion constraint on `(staff_id, time_range)` over active statuses makes overlapping appointments physically impossible to store, so two simultaneous confirmations can't both win.

**M-Pesa callbacks are idempotent.** Safaricom retries; a unique constraint on the checkout request ID means a retry can't double-charge or double-book.

**Times** are stored in UTC and rendered in EAT. Single zone, no DST.

See [`CLAUDE.md`](./CLAUDE.md) for the full engineering contract.

---

## Scope

**v1 ships salons and barbershops only.**

Not in v1: clinics, inventory, POS, payroll or commission, loyalty points, multi-currency, native mobile app, rescheduling chains, Google Calendar sync.

Clinics are deferred deliberately — appointment records tied to a medical practice edge into health data under the Kenya Data Protection Act 2019, which carries a materially higher compliance burden. That's a later phase with proper legal review, not the same product with a different label.

---

## Data protection

Client names, phone numbers and visit history are personal data under the Kenya Data Protection Act, 2019. BookNasi acts as a controller for its own users and a processor for its shops' clients. The deployment ships with a privacy policy, a stated retention period, export and delete paths, and a processor clause in the shop terms.

---

## How we know it's working

- Bookings per shop per week — the only real signal staff are using it
- Walk-ins recorded vs online bookings — if walk-ins are near zero, the calendar has drifted from reality
- No-show rate before vs after deposits — the number that sells the product to the next shop
- Deposit completion rate (STK started → paid)
- Month-three shop retention

---

## Licence

Proprietary. © Genmars Tech Limited (UrbanTrends). All rights reserved.
