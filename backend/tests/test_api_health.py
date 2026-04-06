"""
اختبارات API:
- Health endpoint
- Auth endpoints (register, login)
- Password validation
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_health_returns_200(self, client: AsyncClient):
        resp = await client.get("/api/health")
        # قد يرجع 200 أو 503 حسب توافر DB
        assert resp.status_code in (200, 503)

    async def test_health_has_version(self, client: AsyncClient):
        resp = await client.get("/api/health")
        data = resp.json()
        assert "version" in data

    async def test_health_has_status(self, client: AsyncClient):
        resp = await client.get("/api/health")
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("ok", "unhealthy", "degraded")


@pytest.mark.asyncio
class TestAuthValidation:
    async def test_register_rejects_personal_email(self, client: AsyncClient):
        resp = await client.post("/api/auth/register", json={
            "email": "user@gmail.com",
            "full_name": "Test User",
            "password": "SecurePass123",
            "business_name": "Test Company",
            "document_type": "cr",
            "document_number": "1234567890",
            "terms_accepted": True,
        })
        assert resp.status_code == 422

    async def test_register_rejects_weak_password(self, client: AsyncClient):
        resp = await client.post("/api/auth/register", json={
            "email": "user@company.com",
            "full_name": "Test User",
            "password": "abc",
            "business_name": "Test Company",
            "document_type": "cr",
            "document_number": "1234567890",
            "terms_accepted": True,
        })
        assert resp.status_code == 422

    async def test_register_rejects_missing_terms(self, client: AsyncClient):
        resp = await client.post("/api/auth/register", json={
            "email": "user@company.com",
            "full_name": "Test User",
            "password": "SecurePass123",
            "business_name": "Test Company",
            "document_type": "cr",
            "document_number": "1234567890",
            "terms_accepted": False,
        })
        assert resp.status_code in (400, 422)

    async def test_login_with_nonexistent_user(self, client: AsyncClient):
        resp = await client.post("/api/auth/login", json={
            "email": "nobody@company.com",
            "password": "SomePassword123",
        })
        assert resp.status_code == 401

    async def test_login_missing_fields(self, client: AsyncClient):
        resp = await client.post("/api/auth/login", json={
            "email": "test@company.com",
        })
        assert resp.status_code == 422

    async def test_no_dev_bypass_account(self, client: AsyncClient):
        """يتحقق من حذف حساب DEV المضمن نهائياً"""
        resp = await client.post("/api/auth/login", json={
            "email": "ali@natiqa.com",
            "password": "Alluosh2026",
        })
        # يجب أن يُعامَل كمستخدم عادي — 401 إذا غير موجود في DB
        assert resp.status_code == 401

    async def test_protected_route_without_token(self, client: AsyncClient):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401 or resp.status_code == 403

    async def test_protected_route_invalid_token(self, client: AsyncClient):
        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert resp.status_code in (401, 403)


@pytest.mark.asyncio
class TestCORSHeaders:
    async def test_cors_allowed_origin(self, client: AsyncClient):
        resp = await client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            }
        )
        assert resp.status_code in (200, 204)

    async def test_error_response_no_sensitive_debug_info(self, client: AsyncClient):
        """في الإنتاج: لا يجب أن يظهر stack trace في الاستجابة"""
        resp = await client.get("/api/nonexistent-route-xyz")
        if resp.status_code == 500:
            data = resp.json()
            # في حالة DEBUG=false يجب ألا يظهر debug dict
            assert "traceback" not in str(data).lower()


@pytest.mark.asyncio
class TestInputValidation:
    async def test_register_validates_document_number_empty(self, client: AsyncClient):
        resp = await client.post("/api/auth/register", json={
            "email": "valid@corp.com",
            "full_name": "Valid User",
            "password": "ValidPass123",
            "business_name": "Corp",
            "document_type": "cr",
            "document_number": "",
            "terms_accepted": True,
        })
        assert resp.status_code == 422

    async def test_register_full_name_too_short(self, client: AsyncClient):
        resp = await client.post("/api/auth/register", json={
            "email": "valid@corp.com",
            "full_name": "A",
            "password": "ValidPass123",
            "business_name": "Corp",
            "document_type": "cr",
            "document_number": "1234567890",
            "terms_accepted": True,
        })
        assert resp.status_code == 422
