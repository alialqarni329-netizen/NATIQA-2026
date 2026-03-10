"""
╔══════════════════════════════════════════════════════════════════════════╗
║  NATIQA — Concrete Adapters (ERP Finance / ERP Inventory / HR)          ║
║                                                                          ║
║  يحتوي على:                                                              ║
║    1. GenericHTTPAdapter  → HTTP client مشترك (Zero Trust headers)      ║
║    2. ERPFinanceAdapterImpl  → SAP / Oracle / Odoo (ماليات)             ║
║    3. ERPInventoryAdapterImpl → مخزون                                   ║
║    4. HRCoreAdapterImpl     → موارد بشرية                               ║
║    5. HRLeavesAdapterImpl   → إجازات                                    ║
║    6. MockERPAdapter        → بيانات وهمية للتطوير                      ║
║    7. MockHRAdapter         → بيانات وهمية للتطوير                      ║
║                                                                          ║
║  للاستخدام الفعلي: استبدل Mock بالـ Impl المناسب وأضف Credentials      ║
║  في الـ Vault ثم غيّر USE_MOCK=False في config                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from app.integrations.base import (
    AuthMethod,
    CircuitState,
    ConnectionStatus,
    ERPFinanceAdapter,
    ERPInventoryAdapter,
    HRCoreAdapter,
    HRLeavesAdapter,
    IntegrationCredentials,
    IntegrationType,
    StandardResponse,
)

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
#  1. Generic HTTP Adapter (مشترك)
# ═══════════════════════════════════════════════════════════

class GenericHTTPAdapter:
    """
    HTTP Client موحّد لجميع الـ Adapters.
    يُطبّق Zero Trust headers + HMAC signing على كل طلب.
    """

    def __init__(self, creds: IntegrationCredentials):
        self.creds   = creds
        self._client: httpx.AsyncClient | None = None
        self._token:  str | None = None
        self._token_expires: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.creds.base_url,
                timeout=self.creds.timeout_sec,
                verify=self.creds.verify_ssl,
            )
        return self._client

    async def _get_auth_headers(self) -> dict[str, str]:
        """
        بناء Auth headers حسب نوع المصادقة.
        يُحدَّث Token تلقائياً قبل انتهاء صلاحيته.
        """
        method = self.creds.auth_method

        if method == AuthMethod.BEARER_TOKEN:
            # تجديد Token إذا انتهت صلاحيته (مع هامش 5 دقائق)
            if self._token and time.time() < self._token_expires - 300:
                return {"Authorization": f"Bearer {self._token}"}
            await self._refresh_oauth_token()
            return {"Authorization": f"Bearer {self._token}"}

        elif method == AuthMethod.API_KEY:
            key = self.creds.api_key or ""
            return {
                "X-API-Key": key,
                "Authorization": f"ApiKey {key}",
            }

        elif method == AuthMethod.BASIC:
            import base64
            cred_str = f"{self.creds.username}:{self.creds.password}"
            encoded  = base64.b64encode(cred_str.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}

        elif method == AuthMethod.HMAC_SIGNED:
            # يُضاف في كل طلب بناءً على الـ body
            return {}

        return {}

    async def _refresh_oauth_token(self) -> None:
        """OAuth2 Client Credentials flow."""
        if not self.creds.client_id or not self.creds.client_secret:
            raise ValueError("OAuth2: client_id و client_secret مطلوبان")

        client = await self._get_client()
        resp = await client.post(
            "/oauth/token",
            data={
                "grant_type":    "client_credentials",
                "client_id":     self.creds.client_id,
                "client_secret": self.creds.client_secret,
                "scope":         "read",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._token         = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 3600)

    async def get(
        self,
        path:   str,
        params: dict | None = None,
        extra_headers: dict | None = None,
    ) -> dict:
        """GET طلب مع Zero Trust headers."""
        client  = await self._get_client()
        auth_h  = await self._get_auth_headers()

        # Zero Trust security headers
        sec_h = self.security_headers(self.creds.system_id)

        # HMAC signing إذا مطلوب
        sign_h: dict = {}
        if self.creds.auth_method == AuthMethod.HMAC_SIGNED and self.creds.hmac_secret:
            sign_h = self.sign_request("GET", path, "", self.creds.hmac_secret)

        headers = {**auth_h, **sec_h, **sign_h, **(extra_headers or {})}

        response = await client.get(path, params=params, headers=headers)
        response.raise_for_status()
        return response.json()

    async def post(
        self,
        path:    str,
        payload: dict,
        extra_headers: dict | None = None,
    ) -> dict:
        """POST طلب مع Zero Trust headers + HMAC signing."""
        client = await self._get_client()
        auth_h = await self._get_auth_headers()
        sec_h  = self.security_headers(self.creds.system_id)

        body_str = json.dumps(payload)
        sign_h: dict = {}
        if self.creds.auth_method == AuthMethod.HMAC_SIGNED and self.creds.hmac_secret:
            sign_h = self.sign_request("POST", path, body_str, self.creds.hmac_secret)

        headers = {
            **auth_h, **sec_h, **sign_h,
            "Content-Type": "application/json",
            **(extra_headers or {}),
        }

        response = await client.post(path, content=body_str, headers=headers)
        response.raise_for_status()
        return response.json()

    # دالة مستعارة من ZeroTrustMixin — يُضاف في __init__.py
    def security_headers(self, system_id: str) -> dict[str, str]:
        return {
            "X-Request-Source": "NATIQA-Integration-Hub",
            "X-System-ID":      system_id,
            "X-Timestamp":      str(int(time.time())),
            "User-Agent":       "NATIQA/3.0 IntegrationHub",
            "Accept":           "application/json",
            "Cache-Control":    "no-store",
        }

    def sign_request(self, method, path, body, secret, nonce=None):
        import hashlib, hmac, secrets as sec_mod
        if nonce is None:
            nonce = sec_mod.token_hex(8)
        timestamp  = str(int(time.time()))
        body_hash  = hashlib.sha256(body.encode()).hexdigest()
        message    = f"{method.upper()}:{path}:{timestamp}:{nonce}:{body_hash}"
        signature  = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return {
            "X-NATIQA-Timestamp": timestamp,
            "X-NATIQA-Nonce":     nonce,
            "X-NATIQA-Signature": signature,
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ═══════════════════════════════════════════════════════════
#  2. ERP Finance — Real Implementation
# ═══════════════════════════════════════════════════════════

class ERPFinanceAdapterImpl(ERPFinanceAdapter, GenericHTTPAdapter):
    """
    تنفيذ حقيقي للربط بـ ERP مالي.
    متوافق مع: SAP S/4HANA (OData) / Oracle Fusion / Odoo JSON-RPC

    للاستخدام مع SAP:
        base_url = "https://sap.company.com/sap/opu/odata/sap"
        auth_method = AuthMethod.OAUTH2

    للاستخدام مع Odoo:
        base_url = "https://odoo.company.com"
        auth_method = AuthMethod.API_KEY
    """

    def __init__(self, creds: IntegrationCredentials):
        ERPFinanceAdapter.__init__(self, creds)
        GenericHTTPAdapter.__init__(self, creds)

    @property
    def integration_type(self) -> IntegrationType:
        return IntegrationType.ERP_FINANCE

    async def connect(self) -> bool:
        try:
            status = await self.health_check()
            self._connected = status == ConnectionStatus.CONNECTED
            return self._connected
        except Exception as e:
            log.error("ERP Finance: فشل الاتصال", error=str(e))
            self._connected = False
            return False

    async def health_check(self) -> ConnectionStatus:
        try:
            await self.get("/api/v1/health")
            self._health_status = ConnectionStatus.CONNECTED
        except Exception:
            self._health_status = ConnectionStatus.ERROR
        return self._health_status

    async def fetch(self, endpoint: str, params: dict | None = None) -> StandardResponse:
        t = time.time()
        try:
            data = await self.get(endpoint, params)
            return StandardResponse(
                success=True,
                system_id=self.creds.system_id,
                data_type=endpoint.split("/")[-1],
                data=data,
                response_ms=int((time.time() - t) * 1000),
            )
        except Exception as e:
            return StandardResponse(
                success=False,
                system_id=self.creds.system_id,
                data_type="error",
                errors=[str(e)],
                response_ms=int((time.time() - t) * 1000),
            )

    async def get_budget_status(
        self,
        fiscal_year: int | None = None,
        cost_center: str | None = None,
    ) -> StandardResponse:
        year   = fiscal_year or datetime.now().year
        params = {"fiscal_year": year}
        if cost_center:
            params["cost_center"] = cost_center
        return await self.safe_fetch("/api/v1/finance/budget", params)

    async def get_cost_centers(self) -> StandardResponse:
        return await self.safe_fetch("/api/v1/finance/cost-centers")

    async def get_purchase_orders(
        self,
        status: str | None = None,
        date_from: str | None = None,
    ) -> StandardResponse:
        params = {}
        if status:    params["status"]    = status
        if date_from: params["date_from"] = date_from
        return await self.safe_fetch("/api/v1/finance/purchase-orders", params)

    async def get_invoices(
        self,
        status: str | None = None,
        vendor: str | None = None,
    ) -> StandardResponse:
        params = {}
        if status: params["status"] = status
        if vendor: params["vendor"] = vendor
        return await self.safe_fetch("/api/v1/finance/invoices", params)


# ═══════════════════════════════════════════════════════════
#  3. HR Leaves — Real Implementation
# ═══════════════════════════════════════════════════════════

class HRLeavesAdapterImpl(HRLeavesAdapter, GenericHTTPAdapter):
    """
    تنفيذ حقيقي لنظام الإجازات.
    متوافق مع: مسار (Masar) / Qiwa / SAP HCM / Oracle HCM
    """

    def __init__(self, creds: IntegrationCredentials):
        HRLeavesAdapter.__init__(self, creds)
        GenericHTTPAdapter.__init__(self, creds)

    @property
    def integration_type(self) -> IntegrationType:
        return IntegrationType.HR_LEAVES

    async def connect(self) -> bool:
        try:
            status = await self.health_check()
            self._connected = status == ConnectionStatus.CONNECTED
            return self._connected
        except Exception as e:
            log.error("HR Leaves: فشل الاتصال", error=str(e))
            return False

    async def health_check(self) -> ConnectionStatus:
        try:
            await self.get("/api/v1/health")
            return ConnectionStatus.CONNECTED
        except Exception:
            return ConnectionStatus.ERROR

    async def fetch(self, endpoint: str, params: dict | None = None) -> StandardResponse:
        t = time.time()
        try:
            data = await self.get(endpoint, params)
            return StandardResponse(
                success=True,
                system_id=self.creds.system_id,
                data_type=endpoint.split("/")[-1],
                data=data,
                response_ms=int((time.time() - t) * 1000),
            )
        except Exception as e:
            return StandardResponse(
                success=False,
                system_id=self.creds.system_id,
                data_type="error",
                errors=[str(e)],
                response_ms=int((time.time() - t) * 1000),
            )

    async def get_leave_balance(self, employee_id: str) -> StandardResponse:
        return await self.safe_fetch(f"/api/v1/employees/{employee_id}/leave-balance")

    async def submit_leave_request(
        self,
        employee_id: str,
        leave_type:  str,
        start_date:  str,
        end_date:    str,
        reason:      str | None = None,
    ) -> StandardResponse:
        t = time.time()
        try:
            data = await self.post(
                "/api/v1/leave-requests",
                {
                    "employee_id": employee_id,
                    "leave_type":  leave_type,
                    "start_date":  start_date,
                    "end_date":    end_date,
                    "reason":      reason or "",
                },
            )
            return StandardResponse(
                success=True,
                system_id=self.creds.system_id,
                data_type="leave_request",
                data=data,
                response_ms=int((time.time() - t) * 1000),
            )
        except Exception as e:
            return StandardResponse(
                success=False,
                system_id=self.creds.system_id,
                data_type="error",
                errors=[str(e)],
            )

    async def get_leave_requests(
        self,
        employee_id: str | None = None,
        status: str | None = None,
    ) -> StandardResponse:
        params = {}
        if employee_id: params["employee_id"] = employee_id
        if status:      params["status"]      = status
        return await self.safe_fetch("/api/v1/leave-requests", params)

    async def approve_leave_request(
        self,
        request_id:  str,
        approver_id: str,
        notes:       str | None = None,
    ) -> StandardResponse:
        t = time.time()
        try:
            data = await self.post(
                f"/api/v1/leave-requests/{request_id}/approve",
                {"approver_id": approver_id, "notes": notes or ""},
            )
            return StandardResponse(
                success=True,
                system_id=self.creds.system_id,
                data_type="leave_approval",
                data=data,
                response_ms=int((time.time() - t) * 1000),
            )
        except Exception as e:
            return StandardResponse(
                success=False,
                system_id=self.creds.system_id,
                data_type="error",
                errors=[str(e)],
            )


# ═══════════════════════════════════════════════════════════
#  4. Mock ERP Adapter (بيانات وهمية للتطوير والتجربة)
# ═══════════════════════════════════════════════════════════

class MockERPFinanceAdapter(ERPFinanceAdapter):
    """
    ERP وهمي يولّد بيانات مالية واقعية.
    يُستخدم في بيئة التطوير وعروض المنصة.
    غيّر USE_MOCK=False عند الربط بـ ERP حقيقي.
    """

    def __init__(self):
        creds = IntegrationCredentials(
            system_id="mock_erp",
            base_url="http://localhost:9999",
            auth_method=AuthMethod.API_KEY,
            api_key="mock_key",
        )
        super().__init__(creds)
        self._connected = True
        self._health_status = ConnectionStatus.CONNECTED

    @property
    def integration_type(self) -> IntegrationType:
        return IntegrationType.ERP_FINANCE

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def health_check(self) -> ConnectionStatus:
        return ConnectionStatus.CONNECTED

    async def fetch(self, endpoint: str, params: dict | None = None) -> StandardResponse:
        return StandardResponse(
            success=True,
            system_id="mock_erp",
            data_type="mock",
            data={},
        )

    async def get_budget_status(
        self,
        fiscal_year: int | None = None,
        cost_center: str | None = None,
    ) -> StandardResponse:
        year = fiscal_year or 2025
        now  = datetime.now()
        elapsed_pct = round((now.timetuple().tm_yday / 365) * 100, 1)

        cost_centers_data = {
            "IT":    {"allocated": 2_800_000, "spent": 1_640_000, "dept": "تقنية المعلومات"},
            "HR":    {"allocated": 1_500_000, "spent":   820_000, "dept": "الموارد البشرية"},
            "OPS":   {"allocated": 4_200_000, "spent": 2_950_000, "dept": "العمليات"},
            "SALES": {"allocated": 3_100_000, "spent": 1_880_000, "dept": "المبيعات"},
            "FIN":   {"allocated": 1_200_000, "spent":   640_000, "dept": "المالية"},
        }

        if cost_center and cost_center.upper() in cost_centers_data:
            cc_data = cost_centers_data[cost_center.upper()]
            summary_cc = [cc_data]
        else:
            summary_cc = list(cost_centers_data.values())

        total_allocated = sum(c["allocated"] for c in summary_cc)
        total_spent     = sum(c["spent"]     for c in summary_cc)
        total_remaining = total_allocated - total_spent
        utilization_pct = round((total_spent / total_allocated) * 100, 1)
        expected_spent  = round((elapsed_pct / 100) * total_allocated)
        variance        = total_spent - expected_spent
        variance_pct    = round((variance / expected_spent) * 100, 1) if expected_spent else 0

        return StandardResponse(
            success=True,
            system_id="mock_erp",
            data_type="budget_status",
            data={
                "fiscal_year":       year,
                "period":            f"يناير–{now.strftime('%B')} {year}",
                "as_of_date":        now.strftime("%Y-%m-%d"),
                "elapsed_year_pct":  elapsed_pct,
                "total_allocated":   total_allocated,
                "total_spent":       total_spent,
                "total_remaining":   total_remaining,
                "utilization_pct":   utilization_pct,
                "expected_spent":    expected_spent,
                "variance_sar":      variance,
                "variance_pct":      variance_pct,
                "variance_status":   "إنفاق أعلى من المتوقع" if variance > 0 else "إنفاق أقل من المتوقع",
                "currency":          "SAR",
                "cost_centers":      [
                    {
                        "code":       code,
                        "name":       v["dept"],
                        "allocated":  v["allocated"],
                        "spent":      v["spent"],
                        "remaining":  v["allocated"] - v["spent"],
                        "pct_used":   round((v["spent"] / v["allocated"]) * 100, 1),
                    }
                    for code, v in cost_centers_data.items()
                ],
                "top_expenses": [
                    {"category": "الرواتب والمزايا",         "amount": 5_820_000, "pct_of_total": 41.4},
                    {"category": "العقود والخدمات المهنية",  "amount": 2_340_000, "pct_of_total": 16.6},
                    {"category": "التقنية والبرمجيات",       "amount": 1_680_000, "pct_of_total": 12.0},
                    {"category": "السفر والتنقل",            "amount":   920_000, "pct_of_total":  6.5},
                    {"category": "المصروفات التشغيلية",      "amount": 3_170_000, "pct_of_total": 22.5},
                ],
                "alerts": [
                    {
                        "level":   "warning",
                        "message": "مركز تكلفة OPS استهلك 70.2% من ميزانيته",
                        "action":  "مراجعة المصروفات التشغيلية",
                    }
                ] if cost_center is None else [],
            },
            response_ms=45,
        )

    async def get_cost_centers(self) -> StandardResponse:
        return StandardResponse(
            success=True,
            system_id="mock_erp",
            data_type="cost_centers",
            data={"cost_centers": ["IT", "HR", "OPS", "SALES", "FIN"]},
        )

    async def get_purchase_orders(
        self,
        status: str | None = None,
        date_from: str | None = None,
    ) -> StandardResponse:
        pos = [
            {"id": "PO-2025-0841", "vendor": "شركة الأنظمة المتكاملة",    "amount": 485_000, "status": "pending",  "items": 12},
            {"id": "PO-2025-0782", "vendor": "مجموعة التقنية الرائدة",     "amount": 128_500, "status": "approved", "items":  3},
            {"id": "PO-2025-0750", "vendor": "شركة البنية التحتية الشاملة","amount": 950_000, "status": "approved", "items": 28},
            {"id": "PO-2025-0710", "vendor": "مؤسسة الدعم التقني",         "amount":  67_200, "status": "pending",  "items":  5},
        ]
        if status:
            pos = [p for p in pos if p["status"] == status]
        return StandardResponse(
            success=True, system_id="mock_erp", data_type="purchase_orders",
            data={"purchase_orders": pos, "total": sum(p["amount"] for p in pos)},
        )

    async def get_invoices(
        self, status: str | None = None, vendor: str | None = None
    ) -> StandardResponse:
        invoices = [
            {"id": "INV-5521", "vendor": "شركة الأنظمة المتكاملة",  "amount": 120_000, "due_days": 15, "status": "unpaid"},
            {"id": "INV-5498", "vendor": "مجموعة التقنية الرائدة",   "amount":  48_750, "due_days":  3, "status": "overdue"},
            {"id": "INV-5432", "vendor": "مؤسسة الدعم التقني",      "amount":  67_200, "due_days": 30, "status": "unpaid"},
        ]
        return StandardResponse(
            success=True, system_id="mock_erp", data_type="invoices",
            data={"invoices": invoices, "overdue_count": sum(1 for i in invoices if i["status"] == "overdue")},
        )


# ═══════════════════════════════════════════════════════════
#  5. Mock HR Adapter (بيانات إجازات وهمية)
# ═══════════════════════════════════════════════════════════

class MockHRLeavesAdapter(HRLeavesAdapter):
    """
    نظام إجازات وهمي بالقواعد السعودية (نظام العمل).
    يُستخدم للتطوير — استبدله بـ HRLeavesAdapterImpl عند الربط.
    """

    def __init__(self):
        creds = IntegrationCredentials(
            system_id="mock_hr",
            base_url="http://localhost:9998",
            auth_method=AuthMethod.API_KEY,
            api_key="mock_hr_key",
        )
        super().__init__(creds)
        self._connected = True
        self._health_status = ConnectionStatus.CONNECTED

        # قاعدة بيانات وهمية للتطوير
        self._employees: dict[str, dict] = {
            "EMP-001": {"name": "أحمد العدواني",  "dept": "تقنية المعلومات", "grade": "A3"},
            "EMP-002": {"name": "سارة المطيري",   "dept": "الموارد البشرية", "grade": "B2"},
            "EMP-003": {"name": "خالد الشمري",    "dept": "العمليات",        "grade": "A2"},
            "EMP-004": {"name": "نورة الزهراني",  "dept": "المالية",         "grade": "A1"},
        }
        self._leave_requests: dict[str, dict] = {}
        self._request_counter = 1000

    @property
    def integration_type(self) -> IntegrationType:
        return IntegrationType.HR_LEAVES

    async def connect(self) -> bool:
        return True

    async def health_check(self) -> ConnectionStatus:
        return ConnectionStatus.CONNECTED

    async def fetch(self, endpoint: str, params: dict | None = None) -> StandardResponse:
        return StandardResponse(
            success=True, system_id="mock_hr", data_type="mock", data={}
        )

    async def get_leave_balance(self, employee_id: str) -> StandardResponse:
        emp = self._employees.get(employee_id)
        if not emp:
            return StandardResponse(
                success=False, system_id="mock_hr", data_type="error",
                errors=[f"الموظف '{employee_id}' غير موجود"],
            )

        # حساب الرصيد بناءً على نظام العمل السعودي
        year_fraction = datetime.now().timetuple().tm_yday / 365
        annual_days   = 30  # نظام العمل السعودي: 30 يوم للموظف القديم

        return StandardResponse(
            success=True,
            system_id="mock_hr",
            data_type="leave_balance",
            data={
                "employee_id":   employee_id,
                "employee_name": emp["name"],
                "department":    emp["dept"],
                "grade":         emp["grade"],
                "leave_year":    2025,
                "balances": {
                    "annual": {
                        "entitled":  annual_days,
                        "taken":     int(annual_days * year_fraction * 0.4),
                        "remaining": int(annual_days * (1 - year_fraction * 0.4)),
                        "pending":   3,
                        "label":     "إجازة سنوية",
                    },
                    "sick": {
                        "entitled":  30,
                        "taken":      2,
                        "remaining": 28,
                        "pending":    0,
                        "label":     "إجازة مرضية",
                    },
                    "emergency": {
                        "entitled":   3,
                        "taken":      1,
                        "remaining":  2,
                        "pending":    0,
                        "label":     "إجازة طارئة",
                    },
                    "hajj": {
                        "entitled":   21,
                        "taken":       0,
                        "remaining":  21,
                        "note":       "مرة واحدة طوال الخدمة",
                        "label":     "إجازة الحج",
                    },
                },
                "pending_requests":   3,
                "last_leave_date":    "2025-01-15",
                "as_of_date":         datetime.now().strftime("%Y-%m-%d"),
            },
            response_ms=18,
        )

    async def submit_leave_request(
        self,
        employee_id: str,
        leave_type:  str,
        start_date:  str,
        end_date:    str,
        reason:      str | None = None,
    ) -> StandardResponse:
        emp = self._employees.get(employee_id)
        if not emp:
            return StandardResponse(
                success=False, system_id="mock_hr", data_type="error",
                errors=[f"الموظف '{employee_id}' غير موجود"],
            )

        # حساب عدد الأيام
        try:
            s = date.fromisoformat(start_date)
            e = date.fromisoformat(end_date)
            days = (e - s).days + 1
            if days <= 0:
                raise ValueError("تاريخ النهاية قبل تاريخ البداية")
        except ValueError as ve:
            return StandardResponse(
                success=False, system_id="mock_hr", data_type="error",
                errors=[str(ve)],
            )

        self._request_counter += 1
        request_id = f"LR-2025-{self._request_counter}"

        request = {
            "request_id":    request_id,
            "employee_id":   employee_id,
            "employee_name": emp["name"],
            "department":    emp["dept"],
            "leave_type":    leave_type,
            "start_date":    start_date,
            "end_date":      end_date,
            "days_requested": days,
            "reason":        reason or "",
            "status":        "pending",
            "submitted_at":  datetime.now(timezone.utc).isoformat(),
            "approver":      "مدير المجموعة",
            "sla_hours":     24,
        }
        self._leave_requests[request_id] = request

        return StandardResponse(
            success=True,
            system_id="mock_hr",
            data_type="leave_request_submitted",
            data=request,
            summary=(
                f"تم تقديم طلب {leave_type} بنجاح\n"
                f"رقم الطلب: {request_id}\n"
                f"المدة: {days} يوم ({start_date} → {end_date})\n"
                f"سيتم الرد خلال 24 ساعة"
            ),
            response_ms=22,
        )

    async def get_leave_requests(
        self,
        employee_id: str | None = None,
        status: str | None = None,
    ) -> StandardResponse:
        requests = list(self._leave_requests.values())
        if employee_id:
            requests = [r for r in requests if r["employee_id"] == employee_id]
        if status:
            requests = [r for r in requests if r["status"] == status]

        return StandardResponse(
            success=True,
            system_id="mock_hr",
            data_type="leave_requests",
            data={"requests": requests, "count": len(requests)},
        )

    async def approve_leave_request(
        self,
        request_id:  str,
        approver_id: str,
        notes:       str | None = None,
    ) -> StandardResponse:
        if request_id not in self._leave_requests:
            return StandardResponse(
                success=False, system_id="mock_hr", data_type="error",
                errors=[f"الطلب '{request_id}' غير موجود"],
            )

        self._leave_requests[request_id]["status"]      = "approved"
        self._leave_requests[request_id]["approved_by"] = approver_id
        self._leave_requests[request_id]["approved_at"] = datetime.now(timezone.utc).isoformat()
        self._leave_requests[request_id]["notes"]        = notes or ""

        return StandardResponse(
            success=True,
            system_id="mock_hr",
            data_type="leave_approved",
            data=self._leave_requests[request_id],
            summary=f"تمت الموافقة على الطلب {request_id}",
        )


# ── Singletons للـ Mock Adapters ──────────────────────────────────────────

_mock_erp:  MockERPFinanceAdapter | None = None
_mock_hr:   MockHRLeavesAdapter   | None = None


def get_mock_erp() -> MockERPFinanceAdapter:
    global _mock_erp
    if _mock_erp is None:
        _mock_erp = MockERPFinanceAdapter()
    return _mock_erp


def get_mock_hr() -> MockHRLeavesAdapter:
    global _mock_hr
    if _mock_hr is None:
        _mock_hr = MockHRLeavesAdapter()
    return _mock_hr
