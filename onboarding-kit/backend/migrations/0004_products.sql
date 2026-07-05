-- Products catalogue (CLAUDE.md §7 admin CRUD). §5 omits this table, but the
-- endpoint map requires admin CRUD on products and applications carry a
-- product_code; this reconciles the two. Tenant-scoped like every core table (§4).

CREATE TABLE products (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id),
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, code)
);

CREATE INDEX products_tenant_idx ON products (tenant_id);
