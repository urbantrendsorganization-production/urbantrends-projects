# PLAN.md — OnboardKit Build Plan

Working checklist for Claude Code sessions. Read CLAUDE.md first — it is the source of truth for all specs and conventions. Update checkboxes at the end of every session. One branch per phase; merge to main only when the phase's vertical slice works end-to-end (fmt + clippy -D warnings + tests green).

Phases are a dependency sequence, not a schedule. Move to the next phase the moment the "Done when" gate passes — no waiting, no padding. Ship as fast as the gates allow.

**Current phase:** Phase 2/3/4 backend complete + core loop proven; Phase 3 office UI (queue/detail/review actions) done. Remaining: Phase 4 office UI (admin CRUD, reports, exports), Flutter stepper, Phase 5 hardening/deploy.
**Last session note:** 2026-07-05 — Stabilised the tree to green (fixed a
boot-blocking S3 sleep_impl panic, 3 clippy errors, stale tests; regenerated
`.sqlx`) and committed Phase 1 + the Phase 2 substrate. Wired the **Phase 2
backend** (clients/applications CRUD, PATCH progressive save, presign/confirm
with magic-byte MIME + tenant-scoped keys, OTP send/verify, consent, submit
completeness gate) and the **worker** (real dispatch loop, `process_image`
recompress≤300KB+EXIF-strip+thumbnail, `send_sms` via MockProvider). Wired the
**Phase 3 backend** review endpoint (start_review/approve/reject/return via the
core state machine, reviewer branch-scoped), atomic `record_transition` with
tenant-scoped `client_number` assignment, and notification SMS through the jobs
table. **72 backend tests green** (auth + 7 application/review/RBAC integration
tests), clippy `-D warnings`, fmt, `sqlx prepare --check`, offline build all
clean. **Proved the whole loop live** against postgres+minio+worker: onboard →
upload → image processing → OTP → consent → submit → approve → `JM-00001`.
Commits: `b33fa1a` (P1 baseline), `be1aeb4` (P2 backend), `5bb89f2` (P3 review),
ops compose tweak. NOT done: OpenAPI/utoipa, real SMS providers
(AfricasTalking/Infobip/Fallback — only trait+Mock), Phase 4 (admin CRUD,
reports, export), office UI beyond login, Flutter stepper (Flutter not installed
here — Dart uncompiled), Phase 5 hardening (rate limiting) + prod deploy push.
--- prior note ---
2026-07-03 — Phase 1 landed on branch `phase/1-schema-auth`.
All 10 tables migrated (sqlx, versions 0001–0003); `application_events` is
append-only via triggers on UPDATE/DELETE/TRUNCATE (verified live). `core` state
machine (`Status`/`StatusKind`/`apply_transition`) with 20 exhaustive tests
(every valid transition, all 24 invalid pairs, actor auth, mandatory
reason/notes). OTP service in `integrations` (getrandom CSPRNG + rejection
sampling, sha256, subtle constant-time, `phonenumber` E.164/KE, 5-min TTL,
single-use, 5-attempt lockout, 3-sends/hr) generic over `Clock`+`OtpStore`, 14
mock-clock tests; Postgres store deferred to Phase 2. Auth: argon2id
(`integrations::password`), login/refresh/logout with rotating sha256-hashed
refresh tokens + reuse detection, RBAC guards (`RequireAgent/Reviewer/Admin`),
`/me`, admin stub. `db` repos (users/refresh_tokens/tenants) via compile-checked
`query!`; `.sqlx` offline cache committed (10 queries). 53 backend tests green;
`cargo fmt`/`clippy --all-targets -D warnings`/`cargo test --all` clean; offline
build + `sqlx prepare --check` pass. Idempotent seed (`-p onboardkit-db --bin
seed`): Jubilant tenant, 3 branches, 6 users (1 admin/2 reviewers/3 agents),
shared demo password. Live end-to-end verified: admin login→200, `/me`, refresh
rotation (reuse→401), wrong-pw→401, agent→admin/overview→403. office login via
httpOnly-cookie proxy (login/refresh/logout/me route handlers + login page);
lint+build green. agent (Flutter) login via dio + `flutter_secure_storage`
(Riverpod `AuthController`); Dart committed, platform folders via `flutter
create` (CLI absent). Next: Phase 2 draft/upload/OTP/consent/submit + Flutter
stepper.

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

- [x] All migrations written per CLAUDE.md §5 (tenants, branches, users, refresh_tokens, clients, onboarding_applications, application_events, kyc_documents, otp_verifications, jobs)
- [x] DB trigger blocking UPDATE/DELETE on `application_events` (also blocks TRUNCATE)
- [x] `core`: `Status` enum + transition methods returning `Result<Transition, TransitionError>` per §6
- [x] `core`: exhaustive state machine tests — every valid transition, every invalid pair, actor authorization, reason/notes unrepresentable-when-missing
- [x] OTP service in `integrations` per §8 (CSPRNG, sha256, constant-time compare, E.164, TTL, attempt + send rate limits via a store trait) — Postgres store impl deferred to Phase 2 with the endpoints
- [x] OTP unit tests with mock clock (expiry, attempts, reuse rejection, rate limits)
- [x] Auth endpoints: login, refresh (rotation, hashed storage, revocation + reuse detection), logout
- [x] argon2id password hashing (`integrations::password`)
- [x] RBAC extractor/permission layer (agent / reviewer / admin scoping per §7)
- [x] RBAC denial tests (cross-role access attempts fail correctly)
- [x] Login flows working from both frontends (office: httpOnly cookie proxy; agent: secure storage)

**Done when:** `cargo test` green across core + integrations + api auth tests; a seeded user can log in from both apps.

---

## Phase 2 — Agent onboarding flow · branch `phase/2-agent-flow`

Backend:
- [x] `POST /clients`, `POST /applications` (draft creation)
- [x] `PATCH /applications/:id` progressive per-section save (Draft/Returned only; E.164 phone normalization)
- [x] Presign upload endpoint (PUT, 10 min expiry, size/content-type constrained)
- [x] Confirm endpoint: object existence + size + magic-byte MIME validation + tenant-scoped key → enqueue `process_image`
- [x] `process_image` job: recompress ≤300KB, strip EXIF (via re-encode), thumbnail, mark processed — idempotent
- [x] Jobs worker loop (`FOR UPDATE SKIP LOCKED`, backoff, max_attempts) — proven live (dedicated unit tests still TODO)
- [x] OTP send/verify endpoints (client's phone, stamps `otp_verified_at`)
- [x] Consent endpoint (terms_version + timestamp)
- [x] Submit endpoint: completeness validation (4 docs processed, OTP verified, consent recorded) → Draft→Submitted event
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
- [x] `GET /applications` role-scoped queue (agent=own, reviewer=branch non-draft, admin=tenant; status/branch/agent filters; pagination)
- [x] `GET /applications/:id` detail with short-expiry presigned GET URLs (≤5 min)
- [x] `POST /applications/:id/review` — start_review / approve / reject / return per state machine (reviewer branch-scoped)
- [x] Client number generation on approval (tenant-scoped, tenant-row-locked; prefix from tenant initials, e.g. `JM-00001`)
- [~] `SmsProvider` trait + MockProvider done; AfricasTalking + Infobip + FallbackProvider NOT yet implemented (§9)
- [~] `send_sms` job wired to approval/rejection/return events; provider-used-on-job-row NOT recorded yet

Office app:
- [x] Review queue table (status filters, badges, per_page=100; authed proxy)
- [x] Application detail: client data side-by-side with document viewer (presigned URLs + thumbnails) + history timeline
- [x] Action modals: start_review / approve / reject (reason required) / return (notes required)

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
- 2026-07-03 — **Enum columns are `TEXT` + `CHECK`, not native Postgres enums.**
  The domain enums live in `onboardkit-core`, which must never depend on sqlx
  (§3), so it cannot derive `sqlx::Type`. TEXT + CHECK keeps `query!` mappings
  trivial (plain `String`) while the db layer converts to/from core enums
  explicitly (`Role::from_db`, `StatusKind::from_db`).
- 2026-07-03 — **`tenants.export_column_mapping JSONB` added now.** §5's tenants
  columns omit it but §7 requires a per-tenant JSONB export-column spec on the
  tenant row. Added with default `'{}'` to reconcile the two; consumed in Phase 4.
- 2026-07-03 — **Authentication identity queries are the one exception to §4's
  tenant filter.** `users::find_active_by_email`/`find_by_id` and the
  refresh-token hash lookups run before any tenant is known (login/refresh must
  resolve the tenant *from* the user row). Email is globally unique and refresh
  tokens are per-user secrets, so these are safe. Every other query is
  tenant-scoped.
- 2026-07-03 — **OTP service is storage-agnostic; Postgres store lands in Phase
  2.** The service in `integrations` is generic over `Clock` + `OtpStore` and is
  fully unit-tested with an in-memory store + mock clock. The real Postgres
  `OtpStore` is written in Phase 2 where the OTP endpoints exercise it (avoids
  dead code and keeps `integrations` free of sqlx for now).
- 2026-07-03 — **Password hashing lives in `integrations::password`; the seed
  hashes independently.** `db` cannot depend on `integrations` (§2), so the
  `seed` binary hashes with argon2id directly. Both use `Argon2::default()`
  (argon2id) and emit self-describing PHC strings, so the hashes are
  interoperable — the api verifies seed-created users fine.
- 2026-07-03 — **Migrations are embedded (`sqlx::migrate!`) and run at
  api/worker/seed startup.** A fresh database self-provisions on boot; no
  separate `migrate` binary. Codifies the schema-source-of-truth in `db`.
- 2026-07-03 — **Refresh-token reuse is detected and rejected.** Rotation revokes
  the presented token and issues a new one in one transaction; if the presented
  token was already revoked, rotation returns `None` and the endpoint answers
  401 (possible token theft). Refresh cookies/tokens are cleared client-side.