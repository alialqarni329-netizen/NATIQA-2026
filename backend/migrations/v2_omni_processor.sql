-- ══════════════════════════════════════════════════════════════════════════
--  NATIQA — Migration v2: Omni-Document Processor
--  التاريخ: فبراير 2025
--
--  التشغيل:
--    docker compose exec db psql -U natiqa_admin -d natiqa -f /migrations/v2_omni_processor.sql
--
--  أو من خارج الـ container:
--    psql $DATABASE_URL -f migrations/v2_omni_processor.sql
-- ══════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. تحديث Enums ───────────────────────────────────────────────────────

-- DocumentStatus: queued + wiped
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'documentstatus'::regtype AND enumlabel = 'queued') THEN
        ALTER TYPE documentstatus ADD VALUE 'queued';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'documentstatus'::regtype AND enumlabel = 'wiped') THEN
        ALTER TYPE documentstatus ADD VALUE 'wiped';
    END IF;
END $$;

-- UserRole: hr_analyst
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'userrole'::regtype AND enumlabel = 'hr_analyst') THEN
        ALTER TYPE userrole ADD VALUE 'hr_analyst';
    END IF;
END $$;

-- AuditAction: أحداث RBAC الجديدة
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'auditaction'::regtype AND enumlabel = 'file_access') THEN
        ALTER TYPE auditaction ADD VALUE 'file_access';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'auditaction'::regtype AND enumlabel = 'file_access_denied') THEN
        ALTER TYPE auditaction ADD VALUE 'file_access_denied';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'auditaction'::regtype AND enumlabel = 'file_wipe') THEN
        ALTER TYPE auditaction ADD VALUE 'file_wipe';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'auditaction'::regtype AND enumlabel = 'query_rbac_block') THEN
        ALTER TYPE auditaction ADD VALUE 'query_rbac_block';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'auditaction'::regtype AND enumlabel = 'permission_change') THEN
        ALTER TYPE auditaction ADD VALUE 'permission_change';
    END IF;
END $$;

COMMIT;

-- Enum changes must be committed before use
BEGIN;

-- ── 2. أعمدة جديدة في documents ─────────────────────────────────────────

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS file_type           VARCHAR(20)   DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS sensitivity         VARCHAR(20)   DEFAULT 'internal',
    ADD COLUMN IF NOT EXISTS masked_fields_count INTEGER       DEFAULT 0,
    ADD COLUMN IF NOT EXISTS processing_time_ms  INTEGER       DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tabular_rows        INTEGER       DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tabular_cols        INTEGER       DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tabular_stats       JSONB,
    ADD COLUMN IF NOT EXISTS wipe_requested_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS wipe_completed_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS wipe_passes         SMALLINT      DEFAULT 0,
    ADD COLUMN IF NOT EXISTS updated_at          TIMESTAMPTZ   DEFAULT NOW();

-- استنتاج file_type من original_name للملفات الحالية
UPDATE documents
SET file_type = LOWER(
    REGEXP_REPLACE(original_name, '^.*\.', '', 'g')
)
WHERE file_type = 'unknown' AND original_name IS NOT NULL;

-- ── 3. تحديث sensitivity للملفات الحالية ────────────────────────────────

UPDATE documents SET sensitivity =
    CASE
        WHEN LOWER(department) = 'payroll'    THEN 'confidential'
        WHEN LOWER(department) = 'hr'         THEN 'restricted'
        WHEN LOWER(department) = 'legal'      THEN 'restricted'
        WHEN LOWER(department) = 'financial'  THEN 'internal'
        WHEN LOWER(department) = 'technical'  THEN 'internal'
        WHEN LOWER(department) = 'admin'      THEN 'internal'
        WHEN LOWER(department) = 'general'    THEN 'public'
        ELSE 'internal'
    END
WHERE sensitivity = 'internal' OR sensitivity IS NULL;

-- ── 4. أعمدة جديدة في messages ──────────────────────────────────────────

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS masked_fields INTEGER DEFAULT 0;

-- ── 5. إنشاء جدول processing_jobs ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS processing_jobs (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id         UUID        REFERENCES documents(id) ON DELETE CASCADE,
    project_id          UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','running','completed','failed','cancelled')),
    stage               VARCHAR(50),
    progress_pct        SMALLINT    DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    chunks_extracted    INTEGER     DEFAULT 0,
    chunks_embedded     INTEGER     DEFAULT 0,
    masked_fields       INTEGER     DEFAULT 0,
    file_type_detected  VARCHAR(20),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    elapsed_ms          INTEGER     DEFAULT 0,
    error_message       TEXT,
    retry_count         SMALLINT    DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE processing_jobs IS
    'تتبع دقيق لكل عملية معالجة وثيقة — يُتيح إعادة المحاولة والمراقبة';

-- ── 6. إنشاء جدول document_access_logs ───────────────────────────────────

CREATE TABLE IF NOT EXISTS document_access_logs (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id      UUID        REFERENCES documents(id) ON DELETE SET NULL,
    user_id          UUID        REFERENCES users(id)     ON DELETE SET NULL,
    user_role        VARCHAR(50) NOT NULL,
    doc_sensitivity  VARCHAR(50) NOT NULL,
    access_granted   BOOLEAN     NOT NULL,
    access_type      VARCHAR(50) NOT NULL
                         CHECK (access_type IN ('rag_query','direct','download','preview')),
    query_text       TEXT,       -- السؤال (مُعالَج بـ masking إذا كان من RAG)
    ip_address       VARCHAR(45),
    user_agent       VARCHAR(200),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE document_access_logs IS
    'سجل تدقيق RBAC — كل محاولة وصول لوثيقة (مسموحة أو مرفوضة)';

-- ── 7. Indexes ────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS ix_docs_project_sensitivity  ON documents(project_id, sensitivity);
CREATE INDEX IF NOT EXISTS ix_docs_project_status       ON documents(project_id, status);
CREATE INDEX IF NOT EXISTS ix_docs_dept_sensitivity     ON documents(department, sensitivity);
CREATE INDEX IF NOT EXISTS ix_docs_file_type            ON documents(file_type);
CREATE INDEX IF NOT EXISTS ix_jobs_document             ON processing_jobs(document_id);
CREATE INDEX IF NOT EXISTS ix_jobs_project_status       ON processing_jobs(project_id, status);
CREATE INDEX IF NOT EXISTS ix_jobs_created              ON processing_jobs(created_at);
CREATE INDEX IF NOT EXISTS ix_access_doc_user           ON document_access_logs(document_id, user_id);
CREATE INDEX IF NOT EXISTS ix_access_granted_date       ON document_access_logs(access_granted, created_at);
CREATE INDEX IF NOT EXISTS ix_access_user_date          ON document_access_logs(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_audit_action_date         ON audit_logs(action, created_at);
CREATE INDEX IF NOT EXISTS ix_audit_user_date           ON audit_logs(user_id, created_at);

-- ── 8. Views مفيدة ───────────────────────────────────────────────────────

-- ملخص الوصول المحجوب (لمراقبة RBAC)
CREATE OR REPLACE VIEW v_rbac_violations AS
SELECT
    u.email                    AS user_email,
    u.role                     AS user_role,
    d.original_name            AS doc_name,
    d.department               AS doc_dept,
    al.doc_sensitivity,
    COUNT(*)                   AS denied_attempts,
    MAX(al.created_at)         AS last_attempt
FROM document_access_logs al
LEFT JOIN users     u ON u.id = al.user_id
LEFT JOIN documents d ON d.id = al.document_id
WHERE al.access_granted = FALSE
GROUP BY u.email, u.role, d.original_name, d.department, al.doc_sensitivity
ORDER BY denied_attempts DESC, last_attempt DESC;

COMMENT ON VIEW v_rbac_violations IS
    'محاولات الوصول المرفوضة — لاكتشاف الاستخدام غير المصرّح به';

-- إحصائيات المعالجة
CREATE OR REPLACE VIEW v_processing_stats AS
SELECT
    p.name                           AS project_name,
    COUNT(d.id)                      AS total_docs,
    SUM(d.chunks_count)              AS total_chunks,
    SUM(d.masked_fields_count)       AS total_masked_fields,
    SUM(d.tabular_rows)              AS total_tabular_rows,
    AVG(d.processing_time_ms)::INT   AS avg_processing_ms,
    COUNT(d.id) FILTER (WHERE d.sensitivity = 'confidential') AS confidential_docs,
    COUNT(d.id) FILTER (WHERE d.sensitivity = 'restricted')   AS restricted_docs,
    COUNT(d.id) FILTER (WHERE d.status = 'ready')             AS ready_docs,
    COUNT(d.id) FILTER (WHERE d.status = 'failed')            AS failed_docs
FROM projects p
LEFT JOIN documents d ON d.project_id = p.id
GROUP BY p.id, p.name;

COMMENT ON VIEW v_processing_stats IS
    'إحصائيات المعالجة لكل مشروع';

COMMIT;

-- ══════════════════════════════════════════════════════════════════════════
--  التحقق من نجاح التطبيق
-- ══════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    col_count INT;
    tbl_count INT;
BEGIN
    -- تحقق من الأعمدة الجديدة في documents
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'documents'
      AND column_name IN ('sensitivity','file_type','tabular_rows','masked_fields_count');

    -- تحقق من الجداول الجديدة
    SELECT COUNT(*) INTO tbl_count
    FROM information_schema.tables
    WHERE table_name IN ('processing_jobs','document_access_logs');

    IF col_count = 4 AND tbl_count = 2 THEN
        RAISE NOTICE '✅ Migration v2 تم بنجاح — % أعمدة جديدة، % جداول جديدة', col_count, tbl_count;
    ELSE
        RAISE WARNING '⚠️  Migration قد يكون ناقصاً — تحقق يدوياً';
    END IF;
END $$;
