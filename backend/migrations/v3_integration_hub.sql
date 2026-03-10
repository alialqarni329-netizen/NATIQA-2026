-- ══════════════════════════════════════════════════════════════════════════
--  NATIQA — Migration v3: Integration Hub + Secure Vault
--  التشغيل:
--    docker compose exec db psql -U natiqa_admin -d natiqa -f /migrations/v3_integration_hub.sql
-- ══════════════════════════════════════════════════════════════════════════
BEGIN;

-- ── 1. Vault Secrets ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vault_secrets (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    system_id   VARCHAR(100) NOT NULL,
    key_name    VARCHAR(100) NOT NULL,
    ciphertext  TEXT         NOT NULL,   -- hex-encoded AES-256-GCM ciphertext
    nonce       VARCHAR(64)  NOT NULL,   -- hex-encoded 12-byte nonce
    salt        VARCHAR(128) NOT NULL,   -- hex-encoded 32-byte PBKDF2 salt
    version     SMALLINT     DEFAULT 1,
    is_active   BOOLEAN      DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ,
    created_by  VARCHAR(100) DEFAULT 'system',
    CONSTRAINT uq_vault_system_key UNIQUE (system_id, key_name, version)
);

COMMENT ON TABLE vault_secrets IS
    'خزنة الأسرار — API Keys وTokens مشفّرة بـ PBKDF2 + AES-256-GCM';
COMMENT ON COLUMN vault_secrets.ciphertext IS 'نص مشفّر بـ AES-256-GCM — hex encoded';
COMMENT ON COLUMN vault_secrets.nonce      IS '12-byte GCM nonce — فريد لكل تشفير';
COMMENT ON COLUMN vault_secrets.salt       IS '32-byte PBKDF2 salt — فريد لكل سر';

-- ── 2. Integration Systems Registry ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS integration_systems (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    system_id       VARCHAR(100) UNIQUE NOT NULL,
    display_name    VARCHAR(200) NOT NULL,
    system_type     VARCHAR(50)  NOT NULL,  -- erp_finance / hr_core / hr_leaves ...
    base_url        TEXT,
    auth_method     VARCHAR(50)  DEFAULT 'api_key',
    is_active       BOOLEAN      DEFAULT TRUE,
    use_mock        BOOLEAN      DEFAULT FALSE,
    timeout_sec     INTEGER      DEFAULT 30,
    last_health_at  TIMESTAMPTZ,
    health_status   VARCHAR(20)  DEFAULT 'unknown',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE integration_systems IS
    'سجل الأنظمة الخارجية المتكاملة (ERP / HR ...) — بدون أسرار';

-- ── 3. Integration Audit Log ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS integration_calls (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID        REFERENCES users(id) ON DELETE SET NULL,
    system_id      VARCHAR(100) NOT NULL,
    intent         VARCHAR(50),
    endpoint       VARCHAR(200),
    success        BOOLEAN     NOT NULL,
    response_ms    INTEGER     DEFAULT 0,
    tokens_used    INTEGER     DEFAULT 0,
    masked_fields  INTEGER     DEFAULT 0,
    error_message  TEXT,
    ip_address     VARCHAR(45),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE integration_calls IS
    'سجل كل استدعاء لنظام خارجي — للتدقيق والمراقبة';

-- ── 4. Indexes ────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_vault_system_active   ON vault_secrets(system_id, is_active);
CREATE INDEX IF NOT EXISTS ix_vault_expires         ON vault_secrets(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_int_calls_user_date   ON integration_calls(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_int_calls_system_date ON integration_calls(system_id, created_at);
CREATE INDEX IF NOT EXISTS ix_int_calls_intent      ON integration_calls(intent, created_at);

-- ── 5. Default Mock Systems ───────────────────────────────────────────────
INSERT INTO integration_systems
    (system_id, display_name, system_type, use_mock, is_active)
VALUES
    ('mock_erp', 'ERP مالي (وهمي للتطوير)',  'erp_finance', TRUE, TRUE),
    ('mock_hr',  'نظام HR  (وهمي للتطوير)',  'hr_leaves',   TRUE, TRUE)
ON CONFLICT (system_id) DO NOTHING;

-- ── 6. View: Integration Health Dashboard ────────────────────────────────
CREATE OR REPLACE VIEW v_integration_health AS
SELECT
    s.system_id,
    s.display_name,
    s.system_type,
    s.health_status,
    s.use_mock,
    s.last_health_at,
    COUNT(c.id)                                          AS total_calls_24h,
    SUM(CASE WHEN c.success = TRUE  THEN 1 ELSE 0 END)  AS success_24h,
    SUM(CASE WHEN c.success = FALSE THEN 1 ELSE 0 END)  AS failure_24h,
    AVG(c.response_ms)::INT                              AS avg_response_ms,
    SUM(c.tokens_used)                                   AS tokens_24h
FROM integration_systems s
LEFT JOIN integration_calls c
    ON c.system_id = s.system_id
    AND c.created_at >= NOW() - INTERVAL '24 hours'
GROUP BY s.system_id, s.display_name, s.system_type,
         s.health_status, s.use_mock, s.last_health_at;

COMMIT;

-- تحقق
DO $$ BEGIN
    RAISE NOTICE '✅ Migration v3 (Integration Hub) تم بنجاح';
END $$;
