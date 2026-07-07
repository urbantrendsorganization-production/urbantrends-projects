# OnboardKit — Deployment (CLAUDE.md §14)

Prod runs on the Hetzner box at `/srv/urbantrends/onboardkit/`, behind Caddy at
`onboardkit.urbantrends.dev`. Two services (`api`, `worker`) run from a single
GHCR image; Postgres is a compose service; object storage is Hetzner Object
Storage (S3-compatible). No MinIO in prod.

## First deploy

```bash
ssh hetzner
mkdir -p /srv/urbantrends/onboardkit && cd /srv/urbantrends/onboardkit
git clone <repo> .            # or copy ops/ + backend/migrations
cp ops/.env.example ops/.env  # then fill in real secrets (never commit ops/.env)
cd ops

# Log in to GHCR to pull the private image (PAT with read:packages).
echo "$GHCR_PAT" | docker login ghcr.io -u <user> --password-stdin

docker compose -f docker-compose.prod.yml --env-file .env pull
docker compose -f docker-compose.prod.yml --env-file .env up -d
```

Migrations run automatically at api/worker startup (`sqlx::migrate!` embedded),
so a fresh database self-provisions on boot.

Seed the demo tenant (optional, demo box only):

```bash
docker compose -f docker-compose.prod.yml run --rm api seed   # if seed bin is shipped
# or run `cargo run -p onboardkit-db --bin seed` against DATABASE_URL
```

## Updates (CD)

CI builds and pushes `ghcr.io/<repo>/backend:latest` (and a `sha-…` tag) on
every push to `main`. To roll forward:

```bash
cd /srv/urbantrends/onboardkit/ops
docker compose -f docker-compose.prod.yml --env-file .env pull
docker compose -f docker-compose.prod.yml --env-file .env up -d
```

Pin `IMAGE_TAG=sha-<commit>` in `.env` to deploy a specific build; to roll back,
set it to a previous sha and `up -d` again.

## Backups

`ops/backup.sh` dumps Postgres into `/srv/urbantrends/backups` (gzip) and prunes
past the retention window. Install as a daily cron:

```cron
0 3 * * *  /srv/urbantrends/onboardkit/ops/backup.sh >> /var/log/onboardkit-backup.log 2>&1
```

## Mobile app (agent APK / Play Store)

The Flutter agent app is **not** part of the server stack — it's built and
distributed separately. The API base URL is compiled in at build time, so the
build must target the deployed backend, not localhost.

Build the release AAB for Google Play:

```bash
cd apps/agent
flutter build appbundle --release \
  --dart-define=API_BASE_URL=https://onboardkit.urbantrends.dev \
  --dart-define=CONSENT_TERMS_VERSION=v1     # must match the server's CONSENT_TERMS_VERSION
```

For a sideloadable demo APK, swap `appbundle` for `apk`.

`CONSENT_TERMS_VERSION` must equal the server value (`ops/.env`) or the consent
endpoint rejects submissions. Bump `version:` in `apps/agent/pubspec.yaml`
(`x.y.z+build`) for every Play upload — the `+build` number must increase.

### Release signing (one-time setup)

Play uploads must be signed with a real upload key, not the debug key. Signing
is driven by `apps/agent/android/key.properties` (gitignored):

1. Generate an upload keystore, stored **outside** the repo:
   ```bash
   keytool -genkey -v -keystore ~/keys/onboardkit/upload-keystore.jks \
     -keyalg RSA -keysize 2048 -validity 10000 -alias upload
   ```
2. `cp android/key.properties.example android/key.properties` and fill in the
   passwords, alias, and absolute `storeFile` path.
3. Enable **Play App Signing** in the Play Console (Google holds the real app
   signing key; `key.properties` is only your upload key — recoverable if lost).

When `key.properties` is absent, the release build falls back to debug signing
(so `flutter run --release` works for devs) — that build is **not** publishable.

App id: `dev.urbantrends.agent`. Never commit `key.properties`, `*.jks`, or
`*.keystore` — all gitignored.

## Alerting (baseline)

The api/worker log JSON in prod (`APP_ENV=production`). Minimum viable alerting
until a full stack is wired:

- **Uptime:** external check on `https://onboardkit.urbantrends.dev/api/v1/health`
  (e.g. UptimeRobot / healthchecks.io) — page on non-200.
- **Error logs:** ship container logs (`docker compose logs`) to the box's
  journal; alert on `level":"ERROR"` frequency. Worker job failures surface as
  `job failed` warnings and, after `max_attempts`, a `failed` row in `jobs`.
- **Stuck jobs:** cron query
  `SELECT count(*) FROM jobs WHERE status='failed'` — alert if non-zero.
- **Backups:** healthchecks.io ping appended to the cron line above; alert if the
  daily ping is missed.

These are deliberately lightweight (§ "no gold-plating"); a fuller
Prometheus/Grafana stack is a post-pilot item.
