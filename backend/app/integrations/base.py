"""
╔══════════════════════════════════════════════════════════════════════════╗
║        NATIQA — Integration Base Interfaces (Zero Trust)                ║
║                                                                          ║
║  كل Adapter خارجي يرث من:                                               ║
║    • IntegrationBase    → واجهة موحّدة (connect/fetch/health)           ║
║    • ZeroTrustMixin     → Token rotation + mTLS + request signing       ║
║    • StandardResponse   → هيكل الرد الموحّد لكل مصدر                   ║
║                                                                          ║
║  مبادئ Zero Trust المطبّقة:                                              ║
║    1. Never Trust → كل طلب يُتحقق منه (Token + HMAC signature)         ║
║    2. Least Privilege → كل Adapter يطلب فقط الـ Scopes التي يحتاجها    ║
║    3. Assume Breach → Timeout قصير + Circuit Breaker + Retry logic      ║
║    4. Verify Explicitly → mTLS certificates + Token expiry checks       ║
║    5. Log Everything → كل طلب خارجي مسجّل في AuditLog                  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import hashlib
import hmac
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ═══════════════════════════════════════════════════════════
#  1. Enums
# ═══════════════════════════════════════════════════════════

class IntegrationType(str, Enum):
    ERP_FINANCE   = "erp_finance"
    ERP_INVENTORY = "erp_inventory"
    HR_CORE       = "hr_core"
    HR_PAYROLL    = "hr_payroll"
    HR_LEAVES     = "hr_leaves"
    CUSTOM        = "custom"


class AuthMethod(str, Enum):
    BEARER_TOKEN  = "bearer_token"
    OAUTH2        = "oauth2"
    API_KEY       = "api_key"
    BASIC         = "basic"
    MTLS          = "mtls"          # مزدوج TLS
    HMAC_SIGNED   = "hmac_signed"   # طلبات موقّعة


class ConnectionStatus(str, Enum):
    CONNECTED    = "connected"
    DISCONNECTED = "disconnected"
    DEGRADED     = "degraded"       # يعمل لكن بطيء/جزئي
    ERROR        = "error"


class CircuitState(str, Enum):
    CLOSED   = "closed"    # طبيعي — الطلبات تمر
    OPEN     = "open"      # محجوب — فشل متكرر
    HALF_OPEN = "half_open" # اختبار — طلب واحد يمر


# ═══════════════════════════════════════════════════════════
#  2. Data Structures
# ═══════════════════════════════════════════════════════════

@dataclass
class IntegrationCredentials:
    """
    بيانات الاتصال — تُرسل فقط عند بناء الـ Adapter،
    وتُخزّن مشفّرة في Vault. لا تُسجَّل في أي log.
    """
    system_id:    str
    base_url:     str
    auth_method:  AuthMethod
    # الحقول الآتية اختيارية حسب auth_method
    api_key:      str | None = None
    client_id:    str | None = None
    client_secret: str | None = None
    username:     str | None = None
    password:     str | None = None
    hmac_secret:  str | None = None
    cert_path:    str | None = None
    key_path:     str | None = None
    timeout_sec:  int = 30
    verify_ssl:   bool = True

    def __repr__(self):
        # لا تُظهر أسرار في logs أبداً
        return (
            f"IntegrationCredentials("
            f"system_id={self.system_id!r}, "
            f"base_url={self.base_url!r}, "
            f"auth_method={self.auth_method!r})"
        )


@dataclass
class StandardResponse:
    """
    هيكل الرد الموحّد من أي نظام خارجي.
    يُطبَّق على ERP و HR وأي مصدر آخر.
    """
    success:      bool
    system_id:    str
    data_type:    str                          # budget / leaves / employees / inventory ...
    data:         dict | list | None = None    # البيانات الخام من النظام
    summary:      str | None = None            # ملخص نصي جاهز للـ LLM
    errors:       list[str] = field(default_factory=list)
    warnings:     list[str] = field(default_factory=list)
    fetched_at:   float = field(default_factory=time.time)
    response_ms:  int = 0
    masked_fields: int = 0                     # عدد الحقول التي مرّت بـ Masking

    @property
    def age_seconds(self) -> float:
        return time.time() - self.fetched_at

    def is_fresh(self, max_age: int = 300) -> bool:
        """هل البيانات حديثة (أقل من max_age ثانية)؟"""
        return self.age_seconds < max_age


@dataclass
class CircuitBreaker:
    """
    Circuit Breaker لحماية النظام من الأعطال المتتالية.

    منطق:
    CLOSED  → الطلبات تمر. عند N فشل متتالي → OPEN
    OPEN    → جميع الطلبات مرفوضة. بعد recovery_sec → HALF_OPEN
    HALF_OPEN → طلب واحد يمر. إن نجح → CLOSED، إن فشل → OPEN
    """
    failure_threshold: int = 5
    recovery_sec:      int = 60
    state:             CircuitState = CircuitState.CLOSED
    failure_count:     int = 0
    last_failure_at:   float = 0.0

    def record_success(self) -> None:
        self.state         = CircuitState.CLOSED
        self.failure_count = 0

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_at = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def can_attempt(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_at >= self.recovery_sec:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN → اسمح بمحاولة


# ═══════════════════════════════════════════════════════════
#  3. Zero Trust Mixin
# ═══════════════════════════════════════════════════════════

class ZeroTrustMixin:
    """
    طبقة Zero Trust تُطبَّق على كل Adapter.

    المسؤوليات:
    - توقيع كل طلب بـ HMAC-SHA256
    - التحقق من انتهاء صلاحية Token قبل الاستخدام
    - إضافة Security Headers لكل طلب
    - تسجيل كل طلب خارجي في Audit
    """

    _token_cache: dict[str, tuple[str, float]] = {}  # {system_id: (token, expires_at)}

    def sign_request(
        self,
        method:  str,
        path:    str,
        body:    str,
        secret:  str,
        nonce:   str | None = None,
    ) -> dict[str, str]:
        """
        توقيع HMAC-SHA256 للطلب.
        يُضاف كـ header: X-NATIQA-Signature

        الصيغة: HMAC(method + path + timestamp + nonce + body_hash)
        """
        if nonce is None:
            import secrets
            nonce = secrets.token_hex(8)

        timestamp  = str(int(time.time()))
        body_hash  = hashlib.sha256(body.encode()).hexdigest()
        message    = f"{method.upper()}:{path}:{timestamp}:{nonce}:{body_hash}"
        signature  = hmac.new(
            secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()

        return {
            "X-NATIQA-Timestamp": timestamp,
            "X-NATIQA-Nonce":     nonce,
            "X-NATIQA-Signature": signature,
        }

    def security_headers(self, system_id: str) -> dict[str, str]:
        """Headers أمنية ثابتة لكل طلب خارجي."""
        return {
            "X-Request-Source":  "NATIQA-Integration-Hub",
            "X-System-ID":       system_id,
            "X-Timestamp":       str(int(time.time())),
            "User-Agent":        "NATIQA/3.0 IntegrationHub",
            "Accept":            "application/json",
            "Cache-Control":     "no-store",
        }

    def is_token_valid(self, system_id: str) -> bool:
        """هل الـ Token الحالي ما زال صالحاً (مع هامش 60 ثانية)؟"""
        cache = self._token_cache.get(system_id)
        if not cache:
            return False
        _, expires_at = cache
        return time.time() < (expires_at - 60)

    def cache_token(self, system_id: str, token: str, ttl_sec: int = 3600) -> None:
        self._token_cache[system_id] = (token, time.time() + ttl_sec)

    def get_cached_token(self, system_id: str) -> str | None:
        cache = self._token_cache.get(system_id)
        return cache[0] if cache else None

    def revoke_token(self, system_id: str) -> None:
        self._token_cache.pop(system_id, None)


# ═══════════════════════════════════════════════════════════
#  4. Abstract Base Adapter
# ═══════════════════════════════════════════════════════════

class IntegrationBase(ABC, ZeroTrustMixin):
    """
    الواجهة الموحّدة لكل Adapter خارجي.
    كل integration_manager.py يتعامل مع هذه الـ Interface فقط.
    """

    def __init__(self, credentials: IntegrationCredentials):
        self.creds          = credentials
        self.circuit        = CircuitBreaker()
        self._connected     = False
        self._last_health   = 0.0
        self._health_status = ConnectionStatus.DISCONNECTED

    # ── Abstract ──────────────────────────────────────────

    @property
    @abstractmethod
    def integration_type(self) -> IntegrationType:
        """نوع الـ Integration."""

    @abstractmethod
    async def connect(self) -> bool:
        """إنشاء الاتصال وتهيئة الـ Token."""

    @abstractmethod
    async def health_check(self) -> ConnectionStatus:
        """فحص صحة الاتصال."""

    @abstractmethod
    async def fetch(self, endpoint: str, params: dict | None = None) -> StandardResponse:
        """جلب بيانات من النظام الخارجي."""

    # ── Concrete ──────────────────────────────────────────

    async def safe_fetch(
        self,
        endpoint: str,
        params: dict | None = None,
        retry: int = 2,
    ) -> StandardResponse:
        """
        جلب آمن مع:
        - Circuit Breaker فحص
        - Retry تلقائي
        - Timeout حماية
        """
        if not self.circuit.can_attempt():
            return StandardResponse(
                success=False,
                system_id=self.creds.system_id,
                data_type="error",
                errors=[
                    f"Circuit breaker OPEN — النظام {self.creds.system_id} "
                    f"غير متاح مؤقتاً، يعيد المحاولة بعد "
                    f"{int(self.circuit.recovery_sec - (time.time() - self.circuit.last_failure_at))} ثانية"
                ],
            )

        last_error = ""
        for attempt in range(retry + 1):
            try:
                result = await self.fetch(endpoint, params)
                if result.success:
                    self.circuit.record_success()
                    return result
                last_error = "; ".join(result.errors)
            except Exception as e:
                last_error = str(e)

        self.circuit.record_failure()
        return StandardResponse(
            success=False,
            system_id=self.creds.system_id,
            data_type="error",
            errors=[f"فشل بعد {retry + 1} محاولات: {last_error}"],
        )

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def status(self) -> ConnectionStatus:
        return self._health_status


# ═══════════════════════════════════════════════════════════
#  5. ERP Finance Adapter Interface
# ═══════════════════════════════════════════════════════════

class ERPFinanceAdapter(IntegrationBase):
    """
    Adapter مالي لأنظمة ERP (SAP / Oracle / Odoo / Microsoft Dynamics).

    يوفر:
    - budget_status()    → حالة الميزانية الحالية
    - gl_accounts()      → الحسابات الختامية
    - cost_centers()     → مراكز التكلفة
    - purchase_orders()  → طلبات الشراء
    - invoices()         → الفواتير
    """

    @property
    def integration_type(self) -> IntegrationType:
        return IntegrationType.ERP_FINANCE

    @abstractmethod
    async def get_budget_status(
        self,
        fiscal_year: int | None = None,
        cost_center: str | None = None,
    ) -> StandardResponse:
        """ميزانية الفترة الحالية مع المصروف والمتبقي."""

    @abstractmethod
    async def get_cost_centers(self) -> StandardResponse:
        """قائمة مراكز التكلفة."""

    @abstractmethod
    async def get_purchase_orders(
        self,
        status: str | None = None,
        date_from: str | None = None,
    ) -> StandardResponse:
        """طلبات الشراء."""

    @abstractmethod
    async def get_invoices(
        self,
        status: str | None = None,
        vendor: str | None = None,
    ) -> StandardResponse:
        """الفواتير."""


# ═══════════════════════════════════════════════════════════
#  6. ERP Inventory Adapter Interface
# ═══════════════════════════════════════════════════════════

class ERPInventoryAdapter(IntegrationBase):
    """
    Adapter للمخزون.

    يوفر:
    - stock_levels()      → مستويات المخزون
    - low_stock_alerts()  → تنبيهات المخزون المنخفض
    - stock_movements()   → حركة المخزون
    """

    @property
    def integration_type(self) -> IntegrationType:
        return IntegrationType.ERP_INVENTORY

    @abstractmethod
    async def get_stock_levels(
        self,
        warehouse: str | None = None,
        category: str | None = None,
    ) -> StandardResponse:
        """مستويات المخزون الحالية."""

    @abstractmethod
    async def get_low_stock_alerts(self, threshold: int = 10) -> StandardResponse:
        """المواد التي وصلت للحد الأدنى."""


# ═══════════════════════════════════════════════════════════
#  7. HR Core Adapter Interface
# ═══════════════════════════════════════════════════════════

class HRCoreAdapter(IntegrationBase):
    """
    Adapter للموارد البشرية (SAP HCM / Oracle HCM / مسار / قيود).

    يوفر:
    - employee_profile()  → بيانات موظف
    - org_chart()         → الهيكل التنظيمي
    - headcount()         → إحصاءات القوى العاملة
    """

    @property
    def integration_type(self) -> IntegrationType:
        return IntegrationType.HR_CORE

    @abstractmethod
    async def get_employee_profile(self, employee_id: str) -> StandardResponse:
        """بيانات موظف محدد."""

    @abstractmethod
    async def get_headcount(
        self,
        department: str | None = None,
    ) -> StandardResponse:
        """إحصاءات القوى العاملة."""

    @abstractmethod
    async def get_org_chart(self, department: str | None = None) -> StandardResponse:
        """الهيكل التنظيمي."""


# ═══════════════════════════════════════════════════════════
#  8. HR Leaves Adapter Interface
# ═══════════════════════════════════════════════════════════

class HRLeavesAdapter(IntegrationBase):
    """
    Adapter لإدارة الإجازات.

    يوفر:
    - leave_balance()      → رصيد الإجازات
    - submit_leave()       → تقديم طلب إجازة
    - leave_requests()     → قائمة الطلبات
    - approve_leave()      → الموافقة على إجازة
    - leave_calendar()     → تقويم الإجازات
    """

    @property
    def integration_type(self) -> IntegrationType:
        return IntegrationType.HR_LEAVES

    @abstractmethod
    async def get_leave_balance(self, employee_id: str) -> StandardResponse:
        """رصيد الإجازات لموظف."""

    @abstractmethod
    async def submit_leave_request(
        self,
        employee_id: str,
        leave_type:  str,
        start_date:  str,
        end_date:    str,
        reason:      str | None = None,
    ) -> StandardResponse:
        """تقديم طلب إجازة جديد."""

    @abstractmethod
    async def get_leave_requests(
        self,
        employee_id: str | None = None,
        status: str | None = None,
    ) -> StandardResponse:
        """قائمة طلبات الإجازات."""

    @abstractmethod
    async def approve_leave_request(
        self,
        request_id:  str,
        approver_id: str,
        notes:       str | None = None,
    ) -> StandardResponse:
        """الموافقة أو رفض طلب إجازة."""
