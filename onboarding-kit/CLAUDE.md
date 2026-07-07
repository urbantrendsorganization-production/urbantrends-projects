# CLAUDE.md — OnboardKit

Source of truth for this repository. Read this fully before writing or modifying any code. If code and this document disagree, this document wins — flag the discrepancy, then fix the code.

## 1. What this is

OnboardKit is a client onboarding & KYC portal for insurance agencies and microfinance institutions (MFIs) in Kenya.

- **Field agents** onboard clients on a **Flutter mobile app**: personal details → KYC document capture (ID front/back, selfie, proof of address) → client phone OTP verification → digital consent → submit.
- **Reviewers** approve/reject/return applications on a **Next.js office app** (desktop).
- **Admins** manage branches, users, products, reports, and exports.
- Backend is **Rust** (Axum + SQLx + Tokio + Postgres).

Built by UrbanTrends (urbantrends.dev). MVP is a portfolio-grade demo product with a seeded demo tenant, designed to be sold as a fixed-price pilot afterward.

### Explicitly OUT of scope for MVP (do not build, do not scaffold)
- Integration with any core banking/insurance system (CSV/Excel export only)
- Offline mode in the agent app (phase 2)
- Automated ID verification against IPRS / e-KYC providers (manual human review only)
- Biometrics beyond a selfie photo
- Multi-tenant *behavior* (schema is tenant-aware, runtime is single-tenant — see §4)

## 2. Repository layout

```
onboardkit/
├── CLAUDE.md                 # this file
├── PLAN.md                   # phase checklist — update after every work session
├── backend/
│   ├── Cargo.toml            # workspace
│   ├── migrations/           # sqlx migrations (source of truth for schema)
│   └── crates/
│       ├── api/              # axum: routes, handlers, extractors, middleware, AppError
│       ├── core/             # domain types, state machine, validation. NO sqlx, NO axum imports.
│       ├── db/               # sqlx queries, repositories
│       ├── jobs/             # Postgres-backed background worker
│       └── integrations/     # sms providers, s3/object storage, otp service
├── apps/
│   ├── office/               # Next.js 15+ App Router, TypeScript, shadcn/ui, recharts
│   └── agent/                # Flutter
└── ops/                      # docker-compose, Caddyfile snippet, deploy scripts, seed
```

Crate dependency rule: `api → {core, db, jobs, integrations}`, `db → core`, `jobs → {core, db, integrations}`, `integrations → core`. `core` depends on nothing internal. Never import axum or sqlx inside `core`.

## 3. Rust rules (enforced — reviewer must reject violations)

- Edition 2024. `cargo clippy --all-targets -- -D warnings` must pass. Pedantic lints on per-crate where practical.
- **No `.unwrap()` / `.expect()` outside `#[cfg(test)]` code.** No `panic!` in any handler, job, or integration path.
- All fallible paths return `Result<T, AppError>` (api) or domain error enums (core/integrations) via `thiserror`. `AppError` implements `IntoResponse` and maps to consistent JSON error bodies (§7).
- Use `sqlx::query!` / `query_as!` compile-time-checked macros wherever possible. Hand-written SQL over ORM-style query builders.
- Every DB write that must be atomic runs in an explicit transaction.
- `tracing` for all logging. No `println!`. Instrument handlers with `#[tracing::instrument(skip(...))]`, skipping secrets and request bodies containing PII.
- Never log: OTP codes, tokens, passwords, KRA PINs, full phone numbers (mask to last 3 digits), document URLs.
- Secrets/config via environment only (`dotenvy` in dev). No secrets in code, compose files committed with placeholders only.
- Timestamps: `chrono::DateTime<Utc>` everywhere. Postgres `timestamptz`.
- IDs: `uuid::Uuid` v4 on every externally visible entity.

## 4. Tenancy model

- Every core table carries `tenant_id UUID NOT NULL REFERENCES tenants(id)`.
- MVP runs **single-tenant**: one seeded tenant, `tenant_id` resolved from the authenticated user's row — never from client input.
- Every query in `db` must filter by `tenant_id`. No exceptions. Repository functions take `tenant_id` as an explicit parameter.
- Do not build tenant switching, tenant signup, or per-tenant config UI. The schema is future-proofing only.

## 5. Database schema

Migrations in `backend/migrations/` are authoritative. Target schema:

- **tenants** — id, name, created_at
- **branches** — id, tenant_id, name, code
- **users** — id, tenant_id, branch_id (nullable for admins), full_name, phone (E.164), email, password_hash (argon2id), role (`agent` | `reviewer` | `admin`), is_active, created_at
- **refresh_tokens** — id, user_id, token_hash (sha256), expires_at, revoked_at, created_at
- **clients** — id, tenant_id, full_name, phone (E.164, unique per tenant), national_id_number, kra_pin, date_of_birth, address, next_of_kin JSONB (`{name, phone, relationship}`), client_number (nullable until approved; tenant-scoped sequence like `JMF-00042`), created_at
- **onboarding_applications** — id, tenant_id, client_id, agent_id, branch_id, product_code, current_status (denormalized, index/query convenience ONLY — truth lives in events), otp_verified_at, consent_at, consent_terms_version, submitted_at, created_at, updated_at
- **application_events** — id, tenant_id, application_id, actor_user_id, from_status, to_status, reason (nullable), created_at. **Append-only: no UPDATE, no DELETE, ever.** Add a DB trigger or rely on code discipline + reviewer enforcement — prefer the trigger.
- **kyc_documents** — id, tenant_id, application_id, doc_type (`id_front` | `id_back` | `selfie` | `address_proof`), storage_key, original_filename, content_type, size_bytes, processed (bool), thumbnail_key (nullable), uploaded_at
- **otp_verifications** — id, tenant_id, phone (E.164), code_hash (sha256), purpose (`client_onboarding`), attempts, max_attempts (default 5), expires_at, verified_at (nullable), created_at
- **jobs** — id, job_type, payload JSONB, status (`pending` | `running` | `done` | `failed`), attempts, max_attempts, run_at, locked_at, locked_by, last_error, created_at

## 6. State machine (heart of the product)

Lives in `core`. Statuses:

```rust
pub enum Status {
    Draft,
    Submitted,
    UnderReview,
    Approved,
    Rejected { reason: String },
    ReturnedForCorrection { notes: String },
}
```

Valid transitions — everything else is a `TransitionError`:

| From | To | Actor | Side effects |
|---|---|---|---|
| Draft | Submitted | agent (owner) | validates completeness: all 4 doc types uploaded+processed, otp_verified_at set, consent_at set |
| Submitted | UnderReview | reviewer | — |
| UnderReview | Approved | reviewer | assign client_number, enqueue approval SMS |
| UnderReview | Rejected { reason } | reviewer | reason mandatory (non-empty), enqueue rejection SMS |
| UnderReview | ReturnedForCorrection { notes } | reviewer | notes mandatory, application editable by agent again |
| ReturnedForCorrection | Submitted | agent (owner) | re-validates completeness |

Rules:
- Rejection without a reason and return without notes must be **unrepresentable** (data carried in the enum variant), not merely validated.
- Every transition produces exactly one `application_events` row (actor, from, to, reason) and updates the denormalized `current_status` **in the same transaction**.
- `Approved` and `Rejected` are terminal.
- Exhaustive unit tests: every valid transition, every invalid pair, actor authorization per transition.

## 7. API conventions (crate `api`)

- Base path `/api/v1`. JSON everywhere.
- Errors: consistent body `{ "error": { "code": "string_snake_case", "message": "human readable" } }` with correct HTTP status. Never leak internal error text, SQL, or stack traces to clients.
- Auth: `Authorization: Bearer <access_jwt>`. Access token TTL 15 min; refresh token TTL 14 days, rotated on every refresh, stored hashed, revocable.
- RBAC enforced in an extractor/permission layer, not ad hoc in handlers:
  - **agent**: sees/edits only own applications; can create clients/applications; can trigger OTP for own drafts
  - **reviewer**: sees applications in own branch in `Submitted`/`UnderReview`/terminal states; performs review transitions
  - **admin**: tenant-wide read + CRUD on branches/users/products; reports; exports
- Pagination: `?page=&per_page=` (max 100), response `{ data: [...], meta: { page, per_page, total } }`.
- OpenAPI generated with `utoipa`, served at `/api/v1/openapi.json` in dev. Frontends generate clients from it (`openapi-typescript` for office, `openapi-generator` dart-dio for agent). Never hand-write API types in the frontends.

### Endpoint map (MVP)

- `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`
- `POST /clients` (agent) — create client shell
- `POST /applications` (agent) — create draft for a client
- `PATCH /applications/:id` (agent, Draft/Returned only) — progressive per-section save
- `POST /applications/:id/documents/presign` — returns presigned PUT URL + storage_key for a doc_type
- `POST /applications/:id/documents/confirm` — client confirms upload; enqueues `process_image` job
- `POST /applications/:id/otp/send` — OTP to the **client's** phone
- `POST /applications/:id/otp/verify`
- `POST /applications/:id/consent` — terms_version + acceptance
- `POST /applications/:id/submit`
- `GET /applications` — role-scoped queue with filters (status, branch, agent, date range)
- `GET /applications/:id` — detail incl. short-expiry presigned GET URLs for documents
- `POST /applications/:id/review` — body `{ action: "start_review" | "approve" | "reject" | "return", reason?, notes? }`
- Admin: CRUD `/branches`, `/users`, `/products`
- `GET /reports/summary` — onboardings per agent/branch/period, avg time-to-approval (derived from events), rejection reasons breakdown
- `GET /exports/approved-clients?format=csv|xlsx` — respects tenant column mapping (JSONB spec on tenant row)

## 8. OTP service (crate `integrations`)

Port of UrbanTrends' hardened Django OTP design:

- 6-digit numeric code from `rand::rngs::OsRng` (CSPRNG). Never `rand::thread_rng` for codes.
- Stored as SHA-256 hash only. Verify with constant-time comparison (`subtle`).
- Phone normalization to E.164 via `phonenumber` crate (default region KE).
- TTL 5 minutes. Single-use: set `verified_at`, reject reuse.
- Max 5 verify attempts per OTP; max 3 sends per phone per hour (Postgres counters, not in-memory).
- Generic error messages — never reveal whether a phone exists or which check failed.
- OTP codes never logged, never returned in API responses (dev seed mode may log to a dev-only table, gated by env flag `DEV_EXPOSE_OTP=true`, which must default off).

## 9. SMS providers (crate `integrations`)

```rust
#[async_trait]
pub trait SmsProvider {
    async fn send(&self, to: &Phone, message: &str) -> Result<SmsReceipt, SmsError>;
}
```

- `AfricasTalkingProvider` (primary), `InfobipProvider` (fallback), `FallbackProvider` wrapping both: try primary, on failure log + try fallback, record which provider succeeded on the job row.
- All SMS sends go through the jobs table — handlers never call providers inline.
- `MockProvider` for tests and seed/demo mode.

## 10. Background jobs (crate `jobs`)

No Redis, no Celery. Postgres-backed queue:

- Worker loop polls with `SELECT ... FOR UPDATE SKIP LOCKED WHERE status='pending' AND run_at <= now()`, marks `running`, executes, marks `done`/`failed` with backoff (`run_at = now() + interval` on retry, attempts+1, respect max_attempts).
- Job types (MVP): `process_image` (download → recompress ≤ 300KB → strip EXIF via kamadak-exif → thumbnail → upload → mark document processed), `send_sms`, `nightly_export_digest` (cron tick inside the worker; runs 02:00 EAT).
- Worker runs as a second binary target in the workspace (`cargo run -p jobs`), same Docker image, separate compose service.
- Jobs must be idempotent — assume at-least-once execution.

## 11. Object storage

- S3-compatible: MinIO in dev (compose service), Hetzner Object Storage in prod. `aws-sdk-s3` with custom endpoint.
- Uploads: presigned PUT, 10-minute expiry, content-type and max size (10MB) constrained in the presign.
- Reads: presigned GET, 5-minute expiry. **No KYC document is ever publicly accessible or served through the API as a proxy stream.**
- Server-side validation on confirm: verify object exists, size, and sniff MIME (magic bytes, not extension). Reject non-image for photo doc types (PDF allowed for address_proof).
- Key layout: `tenants/{tenant_id}/applications/{application_id}/{doc_type}/{uuid}.{ext}`.

## 12. Frontends

### apps/office (Next.js)
- App Router, TypeScript strict, shadcn/ui, recharts for reports.
- Auth: tokens in httpOnly cookies via a thin route-handler proxy for login/refresh; API types generated from OpenAPI — never hand-written.
- Screens: login → review queue (filter/paginate, status badges) → application detail (form data side-by-side with document viewer using presigned URLs) → action modals (approve / reject-with-reason / return-with-notes) → admin CRUD (branches, users, products; plain tables, minimal) → reports (3 charts + summary cards) → export page.
- Keep admin UI deliberately minimal. No gold-plating.

### apps/agent (Flutter)
- Targets Android first (demo APK is a deliverable). Riverpod for state, dio for HTTP with generated client, flutter_secure_storage for tokens.
- Flow: login → my applications list (drafts, returned, submitted, terminal) → onboarding stepper:
  1. Client details (progressive PATCH save per step — a dropped connection must never lose work)
  2. Documents (native camera capture, on-device compression before upload, per-doc upload status with retry)
  3. Phone verification (send OTP to client's phone, verify)
  4. Consent (render terms, checkbox, record)
  5. Review & submit (completeness checklist mirrors backend validation)
- Returned applications show reviewer notes prominently and re-open the stepper.
- Polish budget lives here — this app is the demo centerpiece.

## 13. Security checklist (verify before any phase merges)

- [ ] Rate limiting (`tower-governor`) on `/auth/*` and `/otp/*`
- [ ] All queries tenant-filtered; RBAC tests for cross-role access attempts
- [ ] Upload validation server-side (size, magic-byte MIME)
- [ ] No PII/secrets in logs (grep for phone/pin/otp/token in tracing calls)
- [ ] Presigned URL expiries: PUT ≤ 10 min, GET ≤ 5 min
- [ ] argon2id for passwords, sha256 for refresh tokens and OTP codes
- [ ] Application events table cannot be updated/deleted (trigger in place)
- [ ] Error responses leak no internals

## 14. Deployment

- Multi-stage Docker: cargo-chef planner/builder → debian-slim runtime. Two services from one image: `api` and `jobs`. Compose also runs postgres, minio (dev only).
- CI: GitHub Actions — fmt, clippy (-D warnings), test, sqlx offline check (`cargo sqlx prepare` committed), build, push to GHCR on main.
- Prod: `/opt/onboardkit/` on the Hetzner box (one dir per stack under `/opt`). A shared **host-level** Caddy (not a per-stack container) fronts every stack; add an `onboardkit.urbantrends.dev` vhost that reverse-proxies to the api on `127.0.0.1:8086`. Postgres backup cron into `/opt/backups`.
- Env vars documented in `ops/.env.example` — keep it exhaustive and current.

## 15. Seed / demo data (`ops/seed`)

Demo tenant **"Jubilant Microfinance"**: 3 branches (Kilimani, Thika, Nakuru), 1 admin, 2 reviewers, 5 agents, ~40 applications spread across all statuses with realistic Kenyan names, E.164 +254 phones, synthetic generated ID images (never real people), events history consistent with each status. Seed runs idempotently (`cargo run -p db --bin seed`).

## 16. Testing standards

- `core`: exhaustive state machine + validation unit tests. This crate should approach 100% branch coverage on transitions.
- `integrations`: OTP service fully unit tested (expiry, attempts, constant-time path, rate limits) with a mock clock; SMS via MockProvider.
- `api`: integration tests per endpoint group against a test Postgres (sqlx test fixtures), covering RBAC denial cases explicitly.
- `jobs`: idempotency + retry/backoff tests.
- No merge to main with failing tests or clippy warnings.

## 17. Workflow for Claude Code sessions

1. Read this file and PLAN.md first.
2. Work one phase at a time, one branch per phase (`phase/1-schema-auth`, etc.). A phase merges only when its vertical slice works end-to-end.
3. Run `cargo fmt`, `cargo clippy --all-targets -- -D warnings`, `cargo test` before declaring anything done.
4. Update PLAN.md checkboxes at the end of every session.
5. If a decision isn't covered here, choose the simplest option consistent with §3 and §13, and record the decision in a `## Decisions log` section appended to this file.
6. Never expand scope into the §1 exclusions list, even if it seems easy.

## 18. Phase plan (mirror in PLAN.md as checkboxes)

- **Phase 0:** workspace, migrations tooling, Axum skeleton + health, AppError, JWT middleware, CI with cargo-chef, both frontends scaffolded against health endpoint
- **Phase 1:** full schema migrations, state machine in core (+tests), OTP service (+tests), auth (login/refresh/logout), RBAC layer, admin panel endpoints stubbed
- **Phase 2:** draft application CRUD, presign/confirm upload flow, process_image job, OTP endpoints, consent, submit validation; Flutter stepper end-to-end
- **Phase 3:** review queue + detail + review actions, SMS providers + fallback, notification jobs; office app queue/detail/actions
- **Phase 4:** admin CRUD, reports (SQL aggregations + charts), CSV/xlsx export with tenant column mapping, nightly digest
- **Phase 5:** security checklist pass, Docker/CI/deploy to Hetzner, seed script, tracing/alerting, backups
- **Phase 6:** demo APK, walkthrough video script, pilot proposal PDF, landing section

## Decisions log

- **`GET /products` is readable by any authenticated tenant user** (create/update
  stay admin-only). Agents need the product list to pick a `product_code` when
  opening an application (§7), so the agent app fetches it live via
  `productsProvider` instead of a hardcoded constant — admin-added products now
  appear in the mobile app. `AppConfig.products` in the Flutter app is retained
  only as an offline fallback. Handler: `routes/admin.rs::list_products`
  (extractor `AuthUser`, not `RequireAdmin`).