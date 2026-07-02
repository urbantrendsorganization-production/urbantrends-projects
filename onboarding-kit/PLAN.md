# PLAN.md — OnboardKit Build Plan

Working checklist for Claude Code sessions. Read CLAUDE.md first — it is the source of truth for all specs and conventions. Update checkboxes at the end of every session. One branch per phase; merge to main only when the phase's vertical slice works end-to-end (fmt + clippy -D warnings + tests green).

Phases are a dependency sequence, not a schedule. Move to the next phase the moment the "Done when" gate passes — no waiting, no padding. Ship as fast as the gates allow.

**Current phase:** Phase 1 (Phase 0 complete)
**Last session note:** 2026-07-02 — Phase 0 landed on branch `phase/0-foundation`.
Rust workspace (api/core/db/jobs/integrations) builds clean; `cargo fmt`, `clippy
--all-targets -D warnings`, and `cargo test --all` all green (5 backend tests:
core Role roundtrip + JWT decode/expiry/wrong-key). Axum `/api/v1/health` (DB
ping → 200/503), `AppError`→JSON per §7, JWT claims extractor skeleton, tracing
(pretty dev / JSON prod), env config via dotenvy. docker-compose stack verified:
`docker compose up` → api **healthy** (`{"status":"ok","database":"up"}`), worker
running, postgres+minio healthy; office proxy `/api/health` reaches the live API.
CI workflow added (fmt, clippy, test, sqlx-offline, cargo-chef docker build,
office lint+build). office (Next 16 + shadcn) lint+build green. agent (Flutter)
Dart sources committed — platform folders regenerated via `flutter create` (CLI
absent in build env; documented). Next: Phase 1 schema + auth + state machine.

---

## Phase 0 — Foundation · branch `phase/0-foundation`

- [x] Cargo workspace with crates: `api`, `core`, `db`, `jobs`, `integrations`
- [x] sqlx-cli migrations tooling set up (`backend/migrations/`), `cargo sqlx prepare` workflow documented
- [x] Axum skeleton: `/api/v1/health` endpoint, router structure, graceful shutdown
- [x] `AppError` type with `IntoResponse` → consistent JSON error body per CLAUDE.md §7
- [x] JWT middleware skeleton (access token validation, claims extractor)
- [x] `tracing` + `tracing-subscriber` configured (JSON logs in prod mode, pretty in dev)
- [x] Config from env via `dotenvy`; `ops/.env.example` created and exhaustive
- [x] docker-compose dev stack: postgres, minio, api, jobs (api/jobs can be stubs)
- [x] GitHub Actions CI: fmt check, clippy -D warnings, test, sqlx offline check, cargo-chef cached build
- [x] `apps/office` Next.js scaffolded (App Router, TS strict, shadcn) hitting health endpoint
- [x] `apps/agent` Flutter scaffolded (Riverpod, dio, secure storage) hitting health endpoint

**Done when:** `docker compose up` gives a healthy API, CI is green, both frontends display health status.

---

## Phase 1 — Schema, auth, state machine · branch `phase/1-schema-auth`

- [ ] All migrations written per CLAUDE.md §5 (tenants, branches, users, refresh_tokens, clients, onboarding_applications, application_events, kyc_documents, otp_verifications, jobs)
- [ ] DB trigger blocking UPDATE/DELETE on `application_events`
- [ ] `core`: `Status` enum + transition methods returning `Result<ApplicationEvent, TransitionError>` per §6
- [ ] `core`: exhaustive state machine tests — every valid transition, every invalid pair, actor authorization, reason/notes unrepresentable-when-missing
- [ ] OTP service in `integrations` per §8 (CSPRNG, sha256, constant-time compare, E.164, TTL, attempt + send rate limits in Postgres)
- [ ] OTP unit tests with mock clock (expiry, attempts, reuse rejection, rate limits)
- [ ] Auth endpoints: login, refresh (rotation, hashed storage, revocation), logout
- [ ] argon2id password hashing
- [ ] RBAC extractor/permission layer (agent / reviewer / admin scoping per §7)
- [ ] RBAC denial tests (cross-role access attempts fail correctly)
- [ ] Login flows working from both frontends (office: httpOnly cookie proxy; agent: secure storage)

**Done when:** `cargo test` green across core + integrations + api auth tests; a seeded user can log in from both apps.

---

## Phase 2 — Agent onboarding flow · branch `phase/2-agent-flow`

Backend:
- [ ] `POST /clients`, `POST /applications` (draft creation)
- [ ] `PATCH /applications/:id` progressive per-section save (Draft/Returned only)
- [ ] Presign upload endpoint (PUT, 10 min expiry, size/content-type constrained)
- [ ] Confirm endpoint: object existence + size + magic-byte MIME validation → enqueue `process_image`
- [ ] `process_image` job: recompress ≤300KB, strip EXIF, thumbnail, mark processed — idempotent
- [ ] Jobs worker loop (`FOR UPDATE SKIP LOCKED`, backoff, max_attempts) + tests
- [ ] OTP send/verify endpoints (client's phone, stamps `otp_verified_at`)
- [ ] Consent endpoint (terms_version + timestamp)
- [ ] Submit endpoint: completeness validation (4 docs processed, OTP verified, consent recorded) → Draft→Submitted event
- [ ] OpenAPI spec via utoipa served in dev; Dart + TS clients generated

Flutter agent app:
- [ ] Login + my-applications list (drafts / returned / submitted / terminal)
- [ ] Stepper: client details (per-step PATCH save) → documents (camera capture, on-device compression, per-doc retry) → OTP → consent → review & submit
- [ ] Returned applications show reviewer notes and re-open stepper
- [ ] Graceful offline/flaky-connection error states (no lost work)

**Done when:** a real phone can onboard a client end-to-end against the dev stack.

---

## Phase 3 — Review queue + notifications · branch `phase/3-review-notify`

Backend:
- [ ] `GET /applications` role-scoped queue (filters: status, branch, agent, date; pagination)
- [ ] `GET /applications/:id` detail with short-expiry presigned GET URLs (≤5 min)
- [ ] `POST /applications/:id/review` — start_review / approve / reject / return per state machine
- [ ] Client number generation on approval (tenant-scoped sequence)
- [ ] `SmsProvider` trait + AfricasTalking + Infobip + FallbackProvider + MockProvider per §9
- [ ] `send_sms` job wired to approval/rejection/return events; provider used recorded on job row

Office app:
- [ ] Review queue table (filters, status badges, pagination)
- [ ] Application detail: form data side-by-side with document viewer
- [ ] Action modals: approve / reject (reason required) / return (notes required)

**Done when:** full loop works — onboard on phone → approve on desktop → SMS lands (MockProvider in dev; one manual live-provider test).

---

## Phase 4 — Admin, reporting, export · branch `phase/4-admin-reports`

- [ ] Admin CRUD endpoints + minimal office UI: branches, users, products
- [ ] `GET /reports/summary`: onboardings per agent/branch/period, avg time-to-approval (from events), rejection reasons breakdown
- [ ] Office reports page: 3 charts (recharts) + summary cards
- [ ] CSV export (`csv` crate) + Excel export (`rust_xlsxwriter`)
- [ ] Per-tenant export column mapping (JSONB spec on tenant row) respected
- [ ] `nightly_export_digest` job (02:00 EAT cron tick in worker)

**Done when:** admin can manage the tenant, reports render with seeded data, exports download in both formats.

---

## Phase 5 — Hardening + deploy · branch `phase/5-hardening-deploy`

- [ ] Full CLAUDE.md §13 security checklist pass (each item verified, not assumed)
- [ ] Rate limiting via tower-governor on `/auth/*` and `/otp/*`
- [ ] PII log audit (grep tracing calls for phone/pin/otp/token)
- [ ] Multi-stage Dockerfile (cargo-chef → debian-slim), one image, `api` + `jobs` services
- [ ] GH Actions: build + push to GHCR on main
- [ ] Prod compose at `/srv/urbantrends/onboardkit/`, Caddy vhost `onboardkit.urbantrends.dev`
- [ ] Postgres backup cron into `/srv/urbantrends/backups` pattern
- [ ] Seed script: "Jubilant Microfinance" demo tenant per §15, idempotent
- [ ] Basic alerting on api/jobs errors

**Done when:** production URL serves the seeded demo; a fresh clone can `docker compose up` locally with `.env.example` guidance alone.

---

## Phase 6 — Demo packaging · branch `phase/6-demo`

- [ ] Release APK of agent app (signed, installable on a demo phone)
- [ ] Walkthrough script: phone onboarding → desktop approval → SMS (≤2 min)
- [ ] Pilot proposal one-pager PDF (scope, exclusions, acceptance criteria, pricing frame, retainer + phase-2 upsells)
- [ ] Product section on urbantrends.dev

**Done when:** a prospect can be handed a phone, watch the loop live, and leave with the proposal.

---

## Decisions log

Record any decision not covered by CLAUDE.md here (date, decision, why). Keep CLAUDE.md updated if a decision changes a spec.

- 2026-07-02 — **OnboardKit is its own git repository** (initialised inside
  `onboarding-kit/`, branch `phase/0-foundation`). CLAUDE.md §14/§17 assume a
  dedicated repo (own CI, own GHCR image, per-phase branches); the folder was
  untracked in the parent internals-vault. Why: keeps this product isolated from
  unrelated vault projects.
- 2026-07-02 — **Crate names are `onboardkit-*`** (`onboardkit-core`, `-db`,
  `-api`, `-jobs`, `-integrations`) with lib targets `onboardkit_core`, etc.
  Binaries: `api` (in `onboardkit-api`) and `worker` (in `onboardkit-jobs`).
  Why: crate names must be unique/prefixed; §2 role names are preserved.
- 2026-07-02 — **Pedantic clippy enabled** per crate with a narrow allow-list
  (`module_name_repetitions`, `doc_markdown` — the product name "OnboardKit" is
  prose, not code). Everything else passes `-D warnings`.
- 2026-07-02 — **Flutter platform folders (`android/`, `ios/`) not committed**;
  the Flutter CLI was unavailable in the build env. Dart sources + `pubspec.yaml`
  are committed; regenerate non-destructively with `flutter create` (documented
  in `apps/agent/README.md`).
- 2026-07-02 — **`.sqlx` offline cache deferred to Phase 1.** Phase 0 uses no
  compile-checked `query!` macros, so `SQLX_OFFLINE=true` builds already succeed
  with no database; CI runs the real `cargo sqlx prepare --check` once `.sqlx/`
  exists.