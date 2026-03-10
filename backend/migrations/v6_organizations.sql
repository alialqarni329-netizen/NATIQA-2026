-- ═══════════════════════════════════════════════════════════════
--  NATIQA — Migration: Add Organizations Table (Multi-Tenancy)
--  Run this ONCE to apply the Organization schema to the database.
-- ═══════════════════════════════════════════════════════════════

-- 1. Create organizations table
CREATE TABLE IF NOT EXISTS organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    document_type   documenttype,
    document_number VARCHAR(100) UNIQUE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_organizations_name            ON organizations(name);
CREATE INDEX IF NOT EXISTS ix_organizations_document_number ON organizations(document_number);

-- 2. Add organization_id FK column to users table
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS organization_id UUID
    REFERENCES organizations(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_users_organization_id ON users(organization_id);
