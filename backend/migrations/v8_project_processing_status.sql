-- ═══════════════════════════════════════════════════════════════
--  NATIQA — Migration v8: Project Processing Status
--  Adds 'processing' to projectstatus ENUM
-- ═══════════════════════════════════════════════════════════════

BEGIN;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'projectstatus'::regtype AND enumlabel = 'processing') THEN
        ALTER TYPE projectstatus ADD VALUE 'processing';
    END IF;
END $$;

COMMIT;

-- Verification
DO $$
DECLARE
    status_exists BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'projectstatus'::regtype AND enumlabel = 'processing') INTO status_exists;

    IF status_exists THEN
        RAISE NOTICE '✅ Migration v8 تم بنجاح — الحالة "processing" تمت إضافتها';
    ELSE
        RAISE WARNING '⚠️ Migration v8 قد يكون ناقصاً';
    END IF;
END $$;
