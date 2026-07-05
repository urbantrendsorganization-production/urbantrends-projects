-- Onboarding domain: clients, applications, the append-only event log, and KYC
-- documents (CLAUDE.md §5, §6).

CREATE TABLE clients (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES tenants(id),
    full_name          TEXT NOT NULL,
    phone              TEXT,               -- E.164, unique per tenant once set
    national_id_number TEXT,
    kra_pin            TEXT,
    date_of_birth      DATE,
    address            TEXT,
    next_of_kin        JSONB,              -- { name, phone, relationship }
    -- NULL until approved; tenant-scoped human id like `JMF-00042` (§5).
    client_number      TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX clients_tenant_idx ON clients (tenant_id);
-- Partial uniqueness: many draft clients may have no phone/number yet.
CREATE UNIQUE INDEX clients_tenant_phone_key
    ON clients (tenant_id, phone) WHERE phone IS NOT NULL;
CREATE UNIQUE INDEX clients_tenant_number_key
    ON clients (tenant_id, client_number) WHERE client_number IS NOT NULL;

CREATE TABLE onboarding_applications (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES tenants(id),
    client_id             UUID NOT NULL REFERENCES clients(id),
    agent_id              UUID NOT NULL REFERENCES users(id),
    branch_id             UUID NOT NULL REFERENCES branches(id),
    product_code          TEXT NOT NULL,
    -- Denormalized for indexing/query convenience ONLY; truth lives in the event
    -- log (§5). Kept in sync inside the same transaction as each event (§6).
    current_status        TEXT NOT NULL DEFAULT 'draft'
        CHECK (current_status IN (
            'draft', 'submitted', 'under_review',
            'approved', 'rejected', 'returned_for_correction'
        )),
    otp_verified_at       TIMESTAMPTZ,
    consent_at            TIMESTAMPTZ,
    consent_terms_version TEXT,
    submitted_at          TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX applications_tenant_status_idx
    ON onboarding_applications (tenant_id, current_status);
CREATE INDEX applications_tenant_agent_idx
    ON onboarding_applications (tenant_id, agent_id);
CREATE INDEX applications_tenant_branch_idx
    ON onboarding_applications (tenant_id, branch_id);
CREATE INDEX applications_client_idx ON onboarding_applications (client_id);

-- Keep updated_at fresh without relying on callers.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER applications_set_updated_at
    BEFORE UPDATE ON onboarding_applications
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Append-only audit log. Every state transition writes exactly one row (§6).
CREATE TABLE application_events (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id),
    application_id UUID NOT NULL REFERENCES onboarding_applications(id),
    actor_user_id  UUID NOT NULL REFERENCES users(id),
    -- NULL only for the initial creation event (no prior status).
    from_status    TEXT,
    to_status      TEXT NOT NULL,
    reason         TEXT,                   -- rejection reason / return notes
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX application_events_app_idx
    ON application_events (application_id, created_at);
CREATE INDEX application_events_tenant_idx ON application_events (tenant_id);

-- Enforce append-only at the database, not just by code discipline (§5, §13).
CREATE OR REPLACE FUNCTION prevent_application_events_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'application_events is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER application_events_no_update
    BEFORE UPDATE ON application_events
    FOR EACH ROW EXECUTE FUNCTION prevent_application_events_mutation();

CREATE TRIGGER application_events_no_delete
    BEFORE DELETE ON application_events
    FOR EACH ROW EXECUTE FUNCTION prevent_application_events_mutation();

-- TRUNCATE is a statement-level op that row triggers miss; guard it too so the
-- log cannot be wiped wholesale.
CREATE TRIGGER application_events_no_truncate
    BEFORE TRUNCATE ON application_events
    FOR EACH STATEMENT EXECUTE FUNCTION prevent_application_events_mutation();

CREATE TABLE kyc_documents (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenants(id),
    application_id    UUID NOT NULL REFERENCES onboarding_applications(id),
    doc_type          TEXT NOT NULL CHECK (doc_type IN (
        'id_front', 'id_back', 'selfie', 'address_proof'
    )),
    storage_key       TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    content_type      TEXT NOT NULL,
    size_bytes        BIGINT NOT NULL,
    processed         BOOLEAN NOT NULL DEFAULT FALSE,
    thumbnail_key     TEXT,
    uploaded_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX kyc_documents_app_idx ON kyc_documents (application_id);
-- One current document per (application, doc_type); re-upload replaces the row.
CREATE UNIQUE INDEX kyc_documents_app_type_key
    ON kyc_documents (application_id, doc_type);
