-- ══════════════════════════════════════════════════════════════════════════
--  NATIQA — Migration v4: Multi-Agent System + Audit Trail
--  التشغيل:
--    docker compose exec db psql -U natiqa_admin -d natiqa \
--      -f /migrations/v4_agent_orchestration.sql
-- ══════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. Agent Audit Logs (سجل التدقيق الموسّع) ────────────────────────────
--
--  يختلف عن audit_logs الأصلي بـ:
--    • record_hash + prev_hash  → Immutable Chaining
--    • sequence_num             → ترتيب لا يُنقض
--    • ai_decision              → القرار الصريح للـ AI
--    • tool_calls               → جميع استدعاءات الأدوات
--    • workflow_id              → ربط بالـ Workflows

CREATE TABLE IF NOT EXISTS agent_audit_logs (
    -- Identity
    record_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    sequence_num    BIGINT      NOT NULL,
    prev_hash       VARCHAR(64) NOT NULL DEFAULT '',
    record_hash     VARCHAR(64) NOT NULL,

    -- Classification
    action          VARCHAR(80) NOT NULL,
    category        VARCHAR(50) NOT NULL DEFAULT 'data_access',
    severity        VARCHAR(20) NOT NULL DEFAULT 'low'
                        CHECK (severity IN ('low','medium','high','critical')),

    -- Actors
    actor_id        VARCHAR(100),
    actor_type      VARCHAR(20) NOT NULL DEFAULT 'user'
                        CHECK (actor_type IN ('user','agent','system')),
    actor_role      VARCHAR(50),
    actor_name      VARCHAR(200),

    -- Targets
    target_type     VARCHAR(50),
    target_id       VARCHAR(200),
    target_name     VARCHAR(200),

    -- Event Details
    description     TEXT        NOT NULL DEFAULT '',
    request_text    TEXT,                           -- ما طلبه المستخدم
    ai_response     TEXT,                           -- ما ردّ به AI (مُقتطع)
    ai_decision     TEXT,                           -- القرار الصريح
    tool_calls      JSONB       DEFAULT '[]',       -- استدعاءات الأدوات
    masked_fields   INTEGER     DEFAULT 0,
    tokens_used     INTEGER     DEFAULT 0,

    -- Network
    ip_address      VARCHAR(45),
    user_agent      VARCHAR(300),
    session_id      VARCHAR(100),

    -- Outcome
    success         BOOLEAN     NOT NULL DEFAULT TRUE,
    error_message   TEXT,
    response_ms     INTEGER     DEFAULT 0,

    -- Workflow
    workflow_id     VARCHAR(50),
    workflow_type   VARCHAR(50),

    -- Extra
    metadata        JSONB       DEFAULT '{}',

    -- Timestamp (immutable)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE agent_audit_logs IS
    'سجل التدقيق الموسّع للـ AI Agents — غير قابل للتعديل (Immutable Chain)';
COMMENT ON COLUMN agent_audit_logs.record_hash IS
    'HMAC-SHA256 لكشف أي تلاعب بالسجل';
COMMENT ON COLUMN agent_audit_logs.prev_hash IS
    'Hash السجل السابق — يُشكّل سلسلة لا تنكسر مثل Blockchain';
COMMENT ON COLUMN agent_audit_logs.ai_decision IS
    'القرار الصريح الذي اتخذه الـ AI: approve/reject/escalate/...';

-- ── 2. Workflow Events (أحداث سير العمل) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_events (
    event_id        VARCHAR(30) PRIMARY KEY,
    workflow_type   VARCHAR(50) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','processing','awaiting',
                                          'approved','rejected','completed','failed','expired')),
    source_agent    VARCHAR(50) NOT NULL DEFAULT '',
    target_agent    VARCHAR(50) NOT NULL DEFAULT '',
    initiator_id    VARCHAR(100),
    initiator_role  VARCHAR(50),
    payload         JSONB       DEFAULT '{}',
    result          JSONB,
    audit_chain     JSONB       DEFAULT '[]',   -- سلسلة التدقيق الداخلية
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    processed_at    TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

COMMENT ON TABLE workflow_events IS
    'سجل دائم لـ Cross-Agent Workflows (طلبات الشراء، الإجازات، التصعيد)';

-- ── 3. Agent Sessions (جلسات الوكلاء) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        REFERENCES users(id) ON DELETE SET NULL,
    agent_type      VARCHAR(30) NOT NULL,
    user_role       VARCHAR(30) NOT NULL,
    turn_count      SMALLINT    DEFAULT 0,
    total_tokens    INTEGER     DEFAULT 0,
    total_ms        INTEGER     DEFAULT 0,
    routing_method  VARCHAR(20) DEFAULT 'keyword',
    routing_confidence NUMERIC(4,3),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    metadata        JSONB       DEFAULT '{}'
);

-- ── 4. Indexes ────────────────────────────────────────────────────────────

-- Audit indexes للبحث السريع
CREATE INDEX IF NOT EXISTS ix_audit_action_ts      ON agent_audit_logs(action, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_actor_ts       ON agent_audit_logs(actor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_severity_ts    ON agent_audit_logs(severity, created_at DESC) WHERE severity IN ('high','critical');
CREATE INDEX IF NOT EXISTS ix_audit_category_ts    ON agent_audit_logs(category, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_workflow       ON agent_audit_logs(workflow_id) WHERE workflow_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_audit_sequence       ON agent_audit_logs(sequence_num);
CREATE INDEX IF NOT EXISTS ix_audit_success        ON agent_audit_logs(success, created_at DESC);

-- Workflow indexes
CREATE INDEX IF NOT EXISTS ix_wf_status_ts         ON workflow_events(status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_wf_type_status       ON workflow_events(workflow_type, status);
CREATE INDEX IF NOT EXISTS ix_wf_initiator         ON workflow_events(initiator_id, created_at DESC);

-- ── 5. Compliance Views ───────────────────────────────────────────────────

-- ملخص يومي للامتثال
CREATE OR REPLACE VIEW v_audit_daily_summary AS
SELECT
    DATE(created_at)                                            AS audit_date,
    COUNT(*)                                                    AS total_events,
    SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END)     AS critical_count,
    SUM(CASE WHEN severity = 'high'     THEN 1 ELSE 0 END)     AS high_count,
    SUM(CASE WHEN success = FALSE       THEN 1 ELSE 0 END)     AS failure_count,
    SUM(CASE WHEN action  = 'access_denied' THEN 1 ELSE 0 END) AS access_denied_count,
    SUM(CASE WHEN category = 'ai_decision'  THEN 1 ELSE 0 END) AS ai_decisions_count,
    SUM(CASE WHEN category = 'vault_access' THEN 1 ELSE 0 END) AS vault_access_count,
    COUNT(DISTINCT actor_id)                                    AS unique_actors,
    SUM(tokens_used)                                            AS total_tokens,
    AVG(response_ms)::INT                                       AS avg_response_ms
FROM agent_audit_logs
GROUP BY DATE(created_at)
ORDER BY audit_date DESC;

COMMENT ON VIEW v_audit_daily_summary IS 'ملخص يومي لسجل التدقيق — للتقارير الدورية';

-- قرارات AI الأخيرة
CREATE OR REPLACE VIEW v_ai_decisions AS
SELECT
    record_id,
    created_at,
    actor_id        AS agent_name,
    target_id       AS workflow_ref,
    ai_decision,
    description,
    severity,
    record_hash,
    prev_hash
FROM agent_audit_logs
WHERE category = 'ai_decision'
  AND ai_decision IS NOT NULL
ORDER BY created_at DESC;

COMMENT ON VIEW v_ai_decisions IS 'جميع قرارات الـ AI مرتّبة حسب الحداثة';

-- ── 6. Retention Policy ──────────────────────────────────────────────────
-- سياسة الاحتفاظ: 7 سنوات للسجلات ذات الأهمية العالية (SAMA)
-- 90 يوم للسجلات العادية

CREATE OR REPLACE FUNCTION archive_old_audit_logs()
RETURNS INTEGER AS $$
DECLARE
    archived_count INTEGER := 0;
BEGIN
    -- نقل السجلات القديمة العادية إلى جدول الأرشيف
    INSERT INTO agent_audit_logs_archive
        SELECT * FROM agent_audit_logs
        WHERE created_at < NOW() - INTERVAL '90 days'
          AND severity NOT IN ('high', 'critical')
          AND category NOT IN ('vault_access', 'authorization');

    GET DIAGNOSTICS archived_count = ROW_COUNT;

    -- حذفها من الجدول الرئيسي
    DELETE FROM agent_audit_logs
    WHERE created_at < NOW() - INTERVAL '90 days'
      AND severity NOT IN ('high', 'critical')
      AND category NOT IN ('vault_access', 'authorization');

    RETURN archived_count;
END;
$$ LANGUAGE plpgsql;

-- جدول الأرشيف (نفس البنية)
CREATE TABLE IF NOT EXISTS agent_audit_logs_archive
    (LIKE agent_audit_logs INCLUDING ALL);

-- ── 7. Celery Queue Tables (اختياري — لـ Beat Scheduler) ─────────────────
-- هذه الجداول تُستخدم إذا قررت تخزين Celery results في PostgreSQL
-- بدلاً من Redis

CREATE TABLE IF NOT EXISTS celery_taskmeta (
    id          SERIAL      PRIMARY KEY,
    task_id     VARCHAR(255) UNIQUE,
    status      VARCHAR(50),
    result      BYTEA,
    date_done   TIMESTAMPTZ,
    traceback   TEXT,
    name        VARCHAR(255),
    args        BYTEA,
    kwargs      BYTEA,
    worker      VARCHAR(100),
    retries     INTEGER,
    queue       VARCHAR(200)
);

-- ── 8. Seed: Audit Sequence ───────────────────────────────────────────────
CREATE SEQUENCE IF NOT EXISTS audit_sequence_seq
    START WITH 1
    INCREMENT BY 1
    NO MAXVALUE
    CACHE 10;

COMMENT ON SEQUENCE audit_sequence_seq IS
    'رقم تسلسلي متصاعد لسجلات التدقيق — يضمن ترتيباً لا يُعاد';

COMMIT;

-- ── Verification ─────────────────────────────────────────────────────────
DO $$
DECLARE tbl_count INT;
BEGIN
    SELECT COUNT(*) INTO tbl_count
    FROM information_schema.tables
    WHERE table_name IN (
        'agent_audit_logs', 'workflow_events',
        'agent_sessions', 'agent_audit_logs_archive'
    );

    IF tbl_count = 4 THEN
        RAISE NOTICE '✅ Migration v4 (Agent Orchestration) تم بنجاح — 4 جداول جديدة';
    ELSE
        RAISE WARNING '⚠️  Migration ناقص — تحقق يدوياً (وجد % جداول من 4)', tbl_count;
    END IF;
END $$;
