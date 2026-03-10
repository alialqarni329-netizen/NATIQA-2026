-- ╔══════════════════════════════════════════════════════════════════╗
-- ║  NATIQA — Migration v5: IAM / Departmental Access Control        ║
-- ║  يُطبَّق مرة واحدة على قاعدة البيانات الإنتاجية                  ║
-- ╚══════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── 1. إضافة دور hr_analyst لـ enum (PostgreSQL) ─────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumlabel = 'hr_analyst'
          AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'userrole')
    ) THEN
        ALTER TYPE userrole ADD VALUE 'hr_analyst' AFTER 'admin';
    END IF;
END $$;

-- ── 2. إضافة عمود allowed_depts لجدول users ──────────────────────────
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS allowed_depts JSONB DEFAULT NULL;

COMMENT ON COLUMN users.allowed_depts IS
    'قائمة JSON بأسماء الأقسام المسموح للمستخدم برؤيتها.
     NULL = يرى جميع الأقسام المتاحة لدوره.
     مثال: ["hr", "admin", "general"]';

-- ── 3. تعيين القيم الافتراضية للمستخدمين الحاليين ────────────────────
-- super_admin و admin  → يرون كل الأقسام (NULL)
UPDATE users
SET    allowed_depts = NULL
WHERE  role IN ('super_admin', 'admin');

-- analyst  → general فقط
UPDATE users
SET    allowed_depts = '["general"]'::jsonb
WHERE  role = 'analyst'
  AND  allowed_depts IS NULL;

-- viewer   → general فقط
UPDATE users
SET    allowed_depts = '["general"]'::jsonb
WHERE  role = 'viewer'
  AND  allowed_depts IS NULL;

-- ── 4. إضافة عمود dept_filter لجدول documents ────────────────────────
-- يُستخدم للتحقق السريع عند البحث في Chroma: هل يملك المستخدم حق الوصول؟
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS dept_access_level VARCHAR(20) DEFAULT 'internal';

COMMENT ON COLUMN documents.dept_access_level IS
    'مستوى الوصول: public | internal | restricted | confidential';

-- تعيين مستوى الوصول تلقائياً بناءً على القسم
UPDATE documents
SET    dept_access_level =
    CASE department
        WHEN 'hr'        THEN 'restricted'
        WHEN 'legal'     THEN 'restricted'
        WHEN 'financial' THEN 'internal'
        WHEN 'technical' THEN 'internal'
        WHEN 'sales'     THEN 'internal'
        WHEN 'admin'     THEN 'internal'
        ELSE 'public'
    END
WHERE  dept_access_level = 'internal';

-- ── 5. Index لتسريع فلترة الوثائق حسب القسم ─────────────────────────
CREATE INDEX IF NOT EXISTS ix_documents_department
    ON documents (department, dept_access_level);

CREATE INDEX IF NOT EXISTS ix_users_role_active
    ON users (role, is_active);

-- ── 6. View مساعدة: ملخص صلاحيات كل مستخدم ──────────────────────────
CREATE OR REPLACE VIEW v_user_permissions AS
SELECT
    u.id,
    u.email,
    u.full_name,
    u.role,
    u.is_active,
    COALESCE(
        u.allowed_depts,
        CASE u.role
            WHEN 'super_admin' THEN '["financial","hr","legal","technical","admin","sales","general"]'::jsonb
            WHEN 'admin'       THEN '["financial","hr","legal","technical","admin","sales","general"]'::jsonb
            WHEN 'hr_analyst'  THEN '["hr","admin","general"]'::jsonb
            WHEN 'analyst'     THEN '["general"]'::jsonb
            WHEN 'viewer'      THEN '["general"]'::jsonb
            ELSE '["general"]'::jsonb
        END
    ) AS effective_depts,
    CASE u.role
        WHEN 'super_admin' THEN TRUE
        WHEN 'admin'       THEN TRUE
        ELSE FALSE
    END AS can_admin,
    CASE u.role
        WHEN 'viewer' THEN FALSE
        ELSE TRUE
    END AS can_upload
FROM users u;

-- ── 7. Function: تحقق إذا كان المستخدم يملك حق الوصول لقسم معين ──────
CREATE OR REPLACE FUNCTION user_can_access_dept(
    p_user_id  UUID,
    p_dept     TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_role        TEXT;
    v_allowed     JSONB;
BEGIN
    SELECT role, allowed_depts
    INTO   v_role, v_allowed
    FROM   users
    WHERE  id = p_user_id AND is_active = TRUE;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- admin و super_admin يصلون لكل الأقسام
    IF v_role IN ('super_admin', 'admin') THEN
        RETURN TRUE;
    END IF;

    -- إذا لم تُعيَّن قائمة → استخدم افتراضي الدور
    IF v_allowed IS NULL THEN
        v_allowed := CASE v_role
            WHEN 'hr_analyst' THEN '["hr","admin","general"]'::jsonb
            ELSE '["general"]'::jsonb
        END;
    END IF;

    RETURN v_allowed @> to_jsonb(p_dept);
END;
$$;

COMMIT;

-- ── تحقق ────────────────────────────────────────────────────────────
DO $$
BEGIN
    RAISE NOTICE '✓ Migration v5 completed: allowed_depts + hr_analyst + dept_access_level';
END $$;
