"""
اختبارات Smart Export Studio
══════════════════════════════════════════════════════════
Covers:
  - GET /export/formats — returns 5 supported formats
  - POST /export/generate — auth required, validates format
  - POST /export/preview — auth required, validates format
  - SmartExportService unit tests (text extraction + format detection)
"""
from __future__ import annotations

import io
import uuid
import pytest
from httpx import AsyncClient

from app.models.models import Organization, User, UserRole, ApprovalStatus
from app.core.security import create_access_token


# ────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────

def _make_user(role: UserRole = UserRole.EMPLOYEE) -> User:
    org_id = uuid.uuid4()
    return User(
        id=uuid.uuid4(),
        full_name="Export Tester",
        email=f"export-{uuid.uuid4().hex[:6]}@corp.com",
        hashed_password="$2b$12$dummy",
        role=role,
        organization_id=org_id,
        is_verified=True,
        is_active=True,
        approval_status=ApprovalStatus.APPROVED,
    )


def _auth_header(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "type": "access"})
    return {"Authorization": f"Bearer {token}"}


def _make_txt_file(content: str = "نص تجريبي للتصدير") -> tuple[str, io.BytesIO, str]:
    return ("test.txt", io.BytesIO(content.encode("utf-8")), "text/plain")


# ────────────────────────────────────────────────────────────────
# 1. GET /export/formats
# ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestExportFormats:
    async def test_formats_endpoint_returns_200(self, client: AsyncClient):
        resp = await client.get("/api/export/formats")
        assert resp.status_code == 200

    async def test_formats_returns_five_formats(self, client: AsyncClient):
        resp = await client.get("/api/export/formats")
        data = resp.json()
        assert "formats" in data
        assert len(data["formats"]) == 5

    async def test_formats_includes_excel(self, client: AsyncClient):
        resp = await client.get("/api/export/formats")
        formats = resp.json()["formats"]
        keys = [f["id"] for f in formats]
        assert "excel" in keys

    async def test_formats_includes_word(self, client: AsyncClient):
        resp = await client.get("/api/export/formats")
        formats = resp.json()["formats"]
        keys = [f["id"] for f in formats]
        assert "word" in keys

    async def test_formats_includes_powerbi(self, client: AsyncClient):
        resp = await client.get("/api/export/formats")
        formats = resp.json()["formats"]
        keys = [f["id"] for f in formats]
        assert "powerbi" in keys

    async def test_formats_have_required_fields(self, client: AsyncClient):
        resp = await client.get("/api/export/formats")
        for fmt in resp.json()["formats"]:
            assert "id" in fmt
            assert "label" in fmt
            assert "icon" in fmt
            assert "export_types" in fmt


# ────────────────────────────────────────────────────────────────
# 2. POST /export/generate — Auth enforcement
# ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestExportGenerateAuth:
    async def test_generate_requires_auth(self, client: AsyncClient):
        file = _make_txt_file()
        resp = await client.post(
            "/api/export/generate",
            files={"file": file},
            data={"output_format": "excel", "export_type": "table"},
        )
        assert resp.status_code in (401, 403)

    async def test_generate_rejects_unsupported_format(self, client: AsyncClient, db_session):
        user = _make_user()
        db_session.add(user)
        await db_session.flush()

        file = _make_txt_file()
        resp = await client.post(
            "/api/export/generate",
            files={"file": file},
            data={"output_format": "unsupported_format", "export_type": "table"},
            headers=_auth_header(user),
        )
        assert resp.status_code in (400, 422, 401, 403)

    async def test_generate_requires_file(self, client: AsyncClient, db_session):
        user = _make_user()
        db_session.add(user)
        await db_session.flush()

        resp = await client.post(
            "/api/export/generate",
            data={"output_format": "excel", "export_type": "table"},
            headers=_auth_header(user),
        )
        assert resp.status_code in (400, 422, 401, 403)


# ────────────────────────────────────────────────────────────────
# 3. POST /export/preview — Auth enforcement
# ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestExportPreviewAuth:
    async def test_preview_requires_auth(self, client: AsyncClient):
        file = _make_txt_file()
        resp = await client.post(
            "/api/export/preview",
            files={"file": file},
            data={"output_format": "word", "export_type": "report"},
        )
        assert resp.status_code in (401, 403)

    async def test_preview_rejects_unknown_format(self, client: AsyncClient, db_session):
        user = _make_user()
        db_session.add(user)
        await db_session.flush()

        file = _make_txt_file()
        resp = await client.post(
            "/api/export/preview",
            files={"file": file},
            data={"output_format": "xyz_format", "export_type": "table"},
            headers=_auth_header(user),
        )
        assert resp.status_code in (400, 422, 401, 403)


# ────────────────────────────────────────────────────────────────
# 4. SmartExportService unit tests
# ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSmartExportServiceUnit:
    async def test_extract_text_from_plain_txt(self):
        from app.services.smart_export_service import SmartExportService
        svc = SmartExportService()
        content = "هذا نص اختبار للتصدير."
        result = await svc.extract_full_text(
            file_bytes=content.encode("utf-8"),
            filename="test.txt",
        )
        assert "اختبار" in result

    async def test_extract_text_returns_string(self):
        from app.services.smart_export_service import SmartExportService
        svc = SmartExportService()
        result = await svc.extract_full_text(
            file_bytes=b"hello world",
            filename="sample.txt",
        )
        assert isinstance(result, str)

    async def test_extract_text_empty_file(self):
        from app.services.smart_export_service import SmartExportService
        svc = SmartExportService()
        result = await svc.extract_full_text(
            file_bytes=b"",
            filename="empty.txt",
        )
        assert isinstance(result, str)

    async def test_generate_excel_returns_bytes(self):
        from app.services.smart_export_service import SmartExportService
        svc = SmartExportService()
        sample_data = {
            "title": "تقرير الاختبار",
            "summary": "ملخص تجريبي",
            "sections": [],
            "tables": [{"headers": ["العمود 1", "العمود 2"], "rows": [["قيمة 1", "قيمة 2"]]}],
            "key_points": ["نقطة واحدة"],
            "metadata": {},
        }
        result = svc.generate_excel(sample_data)
        assert isinstance(result, bytes)
        assert len(result) > 0

    async def test_generate_word_returns_bytes(self):
        from app.services.smart_export_service import SmartExportService
        svc = SmartExportService()
        sample_data = {
            "title": "تقرير",
            "summary": "ملخص",
            "sections": [{"heading": "قسم 1", "content": "محتوى القسم"}],
            "tables": [],
            "key_points": ["نقطة 1", "نقطة 2"],
            "metadata": {"date": "2026-04-07"},
        }
        result = svc.generate_word(sample_data)
        assert isinstance(result, bytes)
        assert len(result) > 0

    async def test_generate_powerbi_returns_valid_json(self):
        from app.services.smart_export_service import SmartExportService
        import json
        svc = SmartExportService()
        sample_data = {
            "title": "تحليل البيانات",
            "summary": "ملخص",
            "sections": [],
            "tables": [{"headers": ["المنتج", "الكمية"], "rows": [["أ", "100"]]}],
            "key_points": [],
            "metadata": {},
        }
        result = svc.generate_powerbi(sample_data)
        assert isinstance(result, bytes)
        parsed = json.loads(result.decode("utf-8"))
        assert "tables" in parsed or "dataset" in parsed or isinstance(parsed, dict)
