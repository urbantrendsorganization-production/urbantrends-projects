-- Core identity: tenants, branches, users, refresh tokens (CLAUDE.md §5).
--
-- Enumerated columns use TEXT + CHECK rather than native Postgres enums: the
-- domain enums live in `onboardkit-core`, which must never depend on sqlx
-- (§3), so the db layer maps String <-> enum explicitly. TEXT + CHECK keeps
-- `sqlx::query!` mappings trivial while still constraining values in the DB.

CREATE TABLE tenants (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT NOT NULL,
    -- Per-tenant CSV/XLSX export column mapping (§7). Reconciles §5 (which omits
    -- it) with §7 (which requires a JSONB spec on the tenant row); see Decisions.
    export_column_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE branches (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id),
    name       TEXT NOT NULL,
    code       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, code)
);

CREATE INDEX branches_tenant_idx ON branches (tenant_id);

CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id),
    -- NULL for admins, who are tenant-wide and not bound to a branch (§5).
    branch_id     UUID REFERENCES branches(id),
    full_name     TEXT NOT NULL,
    phone         TEXT NOT NULL,            -- E.164
    email         TEXT NOT NULL,
    password_hash TEXT NOT NULL,            -- argon2id
    role          TEXT NOT NULL CHECK (role IN ('agent', 'reviewer', 'admin')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Login resolves the tenant from the user row (§4), so email must identify a
    -- single user across the deployment: globally unique, not per-tenant.
    UNIQUE (email)
);

CREATE INDEX users_tenant_idx ON users (tenant_id);
CREATE INDEX users_tenant_branch_idx ON users (tenant_id, branch_id);

CREATE TABLE refresh_tokens (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,        -- sha256 of the opaque token
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX refresh_tokens_user_idx ON refresh_tokens (user_id);
