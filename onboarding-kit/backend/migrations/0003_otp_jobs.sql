-- OTP verifications and the Postgres-backed job queue (CLAUDE.md §5, §8, §10).

CREATE TABLE otp_verifications (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id),
    phone        TEXT NOT NULL,            -- E.164
    code_hash    TEXT NOT NULL,            -- sha256 of the 6-digit code
    purpose      TEXT NOT NULL DEFAULT 'client_onboarding'
        CHECK (purpose IN ('client_onboarding')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    expires_at   TIMESTAMPTZ NOT NULL,
    verified_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Send-rate limiting (max 3 sends/phone/hour, §8) counts recent rows by phone.
CREATE INDEX otp_verifications_phone_created_idx
    ON otp_verifications (tenant_id, phone, purpose, created_at);

CREATE TABLE jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type     TEXT NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    status       TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'failed')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    run_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at    TIMESTAMPTZ,
    locked_by    TEXT,
    last_error   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Worker dequeue: pending jobs whose run_at has arrived, oldest first (§10).
CREATE INDEX jobs_pending_run_at_idx
    ON jobs (run_at) WHERE status = 'pending';
