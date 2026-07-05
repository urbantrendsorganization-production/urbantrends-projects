-- Nightly export digest archive (§10). One row per tenant per EAT calendar date,
-- recording the object-storage key of the archived approved-clients export. The
-- UNIQUE (tenant_id, digest_date) constraint is the idempotency guard: the
-- worker's cron tick and the digest job handler are both at-least-once.
CREATE TABLE export_digests (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id),
    digest_date DATE NOT NULL,
    storage_key TEXT NOT NULL,
    row_count   INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, digest_date)
);

CREATE INDEX export_digests_tenant_date_idx
    ON export_digests (tenant_id, digest_date DESC);
