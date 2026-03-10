"""
╔══════════════════════════════════════════════════════════════════════════╗
║        NATIQA — Integration Manager  (مدير التكامل)                     ║
║                                                                          ║
║  المسؤوليات:                                                             ║
║    1. تسجيل وإدارة جميع الـ Adapters (ERP / HR ...)                    ║
║    2. سحب البيانات من الـ Vault وبناء Credentials                       ║
║    3. تمرير البيانات للـ LLM لتحويلها إلى تقارير مقروءة                ║
║    4. Intent Detection: تحليل سؤال المستخدم وتحديد النظام المناسب      ║
║    5. تسجيل كل استدعاء خارجي في Audit Log                               ║
║                                                                          ║
║  تدفق الطلب:                                                             ║
║    User Chat → IntentDetector → IntegrationManager                      ║
║      → Vault (load creds) → Adapter (fetch data)                       ║
║      → Masking → LLM (format report) → Unmask → User                   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

from app.core.config import settings
from app.integrations.base import (
    ConnectionStatus,
    IntegrationBase,
    IntegrationType,
    StandardResponse,
)
from app.integrations.vault import get_vault
from app.services.llm.factory import get_llm
from app.services.llm.masking import mask_sensitive_data, unmask_data

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
#  1. Intent Detection
# ═══════════════════════════════════════════════════════════

class QueryIntent(str, Enum):
    """نية المستخدم من السؤال."""
    # ERP - Finance
    BUDGET_QUERY       = "budget_query"
    PURCHASE_ORDERS    = "purchase_orders"
    INVOICES           = "invoices"
    COST_CENTERS       = "cost_centers"
    # HR - Leaves
    LEAVE_BALANCE      = "leave_balance"
    SUBMIT_LEAVE       = "submit_leave"
    LEAVE_STATUS       = "leave_status"
    APPROVE_LEAVE      = "approve_leave"
    # HR - General
    EMPLOYEE_INFO      = "employee_info"
    HEADCOUNT          = "headcount"
    # Inventory
    STOCK_LEVELS       = "stock_levels"
    # Unknown
    UNKNOWN            = "unknown"


# كلمات مفتاحية عربية وإنجليزية لكل نية
INTENT_KEYWORDS: dict[QueryIntent, list[str]] = {
    QueryIntent.BUDGET_QUERY: [
        "ميزانية", "budget", "الصرف", "المصروف", "الإنفاق",
        "المتبقي", "remaining", "مركز تكلفة", "cost center",
        "الميزانية السنوية", "fiscal", "مالية", "بند",
    ],
    QueryIntent.PURCHASE_ORDERS: [
        "طلبات الشراء", "purchase order", "po", "مشتريات",
        "طلب شراء", "موردين", "vendor",
    ],
    QueryIntent.INVOICES: [
        "فاتورة", "فواتير", "invoice", "invoices",
        "مستحقات", "دفع", "سداد",
    ],
    QueryIntent.LEAVE_BALANCE: [
        "رصيد الإجازة", "رصيد إجازاتي", "كم باقي", "leave balance",
        "إجازة سنوية", "أيام إجازة", "متبقي لي",
        "رصيد", "كم لدي من إجازات",
    ],
    QueryIntent.SUBMIT_LEAVE: [
        "أريد إجازة", "اطلب إجازة", "تقديم إجازة", "submit leave",
        "request leave", "طلب إجازة", "أحتاج إجازة", "خذ إجازة",
        "من تاريخ", "إلى تاريخ",
    ],
    QueryIntent.LEAVE_STATUS: [
        "حالة الطلب", "leave status", "طلباتي", "my requests",
        "هل وافقوا", "تمت الموافقة", "طلبات الإجازة",
    ],
    QueryIntent.APPROVE_LEAVE: [
        "وافق على", "approve leave", "قبول الطلب", "رفض الطلب",
        "موافقة إجازة",
    ],
    QueryIntent.EMPLOYEE_INFO: [
        "بيانات موظف", "employee", "معلومات موظف", "ملف الموظف",
    ],
    QueryIntent.HEADCOUNT: [
        "عدد الموظفين", "headcount", "القوى العاملة", "workforce",
        "كم موظف",
    ],
    QueryIntent.STOCK_LEVELS: [
        "مخزون", "stock", "inventory", "مستوى المخزون",
        "المواد", "warehouse",
    ],
}


@dataclass
class IntentResult:
    intent:      QueryIntent
    confidence:  float           # 0.0 → 1.0
    params:      dict            # معاملات مستخرجة من السؤال
    raw_query:   str


def detect_intent(query: str) -> IntentResult:
    """
    كشف نية المستخدم بدون LLM (regex + keyword matching).
    سريع — لا يستهلك tokens.
    """
    q_lower = query.lower()
    scores: dict[QueryIntent, float] = {}

    for intent, keywords in INTENT_KEYWORDS.items():
        hits  = sum(1 for kw in keywords if kw.lower() in q_lower)
        score = hits / max(len(keywords), 1)
        if hits > 0:
            scores[intent] = score

    if not scores:
        return IntentResult(
            intent=QueryIntent.UNKNOWN,
            confidence=0.0,
            params={},
            raw_query=query,
        )

    best_intent = max(scores, key=lambda k: scores[k])
    confidence  = min(scores[best_intent] * 3, 1.0)  # تضخيم نسبي

    # استخراج معاملات من السؤال
    params = _extract_params(query, best_intent)

    return IntentResult(
        intent=best_intent,
        confidence=confidence,
        params=params,
        raw_query=query,
    )


def _extract_params(query: str, intent: QueryIntent) -> dict:
    """استخراج معاملات من نص السؤال (تاريخ / موظف / مركز تكلفة...)."""
    params: dict[str, Any] = {}
    q = query

    # استخراج تواريخ (YYYY-MM-DD أو DD/MM/YYYY)
    dates = re.findall(r'\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}', q)
    if len(dates) >= 2:
        params["start_date"] = dates[0].replace("/", "-")
        params["end_date"]   = dates[1].replace("/", "-")
    elif len(dates) == 1:
        params["date"] = dates[0]

    # استخراج رقم موظف
    emp = re.search(r'EMP-\d+|\bموظف\s+(\d+)\b', q, re.IGNORECASE)
    if emp:
        params["employee_id"] = emp.group(0)

    # استخراج نوع الإجازة
    leave_types = {
        "سنوية": "annual", "annual": "annual",
        "مرضية": "sick",   "sick":   "sick",
        "طارئة": "emergency",
        "حج":    "hajj",
    }
    for ar, en in leave_types.items():
        if ar in q or en in q.lower():
            params["leave_type"] = en
            break
    if "leave_type" not in params and intent == QueryIntent.SUBMIT_LEAVE:
        params["leave_type"] = "annual"

    # استخراج مركز التكلفة
    cc = re.search(r'\b(IT|HR|OPS|SALES|FIN)\b', q, re.IGNORECASE)
    if cc:
        params["cost_center"] = cc.group(0).upper()

    # استخراج سنة مالية
    year = re.search(r'\b(202[3-9]|203[0-5])\b', q)
    if year:
        params["fiscal_year"] = int(year.group(0))

    # رقم طلب إجازة
    lr = re.search(r'LR-\d{4}-\d+', q)
    if lr:
        params["request_id"] = lr.group(0)

    return params


# ═══════════════════════════════════════════════════════════
#  2. Report Generator (LLM Formatter)
# ═══════════════════════════════════════════════════════════

@dataclass
class ReportConfig:
    """إعداد التقرير النهائي."""
    format:     str = "arabic_executive"   # arabic_executive / bullet_points / table
    max_tokens: int = 1500
    include_recommendations: bool = True
    preserve_numbers: bool = True           # شرط حاسم — الأرقام لا تتغير


REPORT_SYSTEM_PROMPT = """
أنت مساعد تحليلي للمدير التنفيذي في منصة ناطقة.

مهمتك: تحويل البيانات الخام من أنظمة ERP/HR إلى تقرير تنفيذي باللغة العربية.

قواعد صارمة:
1. الأرقام الدقيقة يجب أن تبقى كما هي تماماً — لا تقريب، لا تغيير
2. أي <<PLACEHOLDER>> في البيانات يجب أن تعيده كما هو في تقريرك
3. التقرير يكون موجزاً، مقروءاً، بتنسيق واضح
4. استخدم ريال سعودي (﷼) للمبالغ المالية
5. أضف تحليلاً موجزاً وتوصيات عملية
6. لا تختلق أرقاماً أو معلومات غير موجودة في البيانات
"""


async def generate_executive_report(
    data: dict | list,
    data_type: str,
    query:     str,
    config:    ReportConfig | None = None,
) -> tuple[str, int]:
    """
    تحويل بيانات خام إلى تقرير تنفيذي عبر LLM.

    يعود بـ: (report_text, tokens_used)

    مسار البيانات:
      raw_data → JSON → Masking → LLM → Unmask → report
    """
    if config is None:
        config = ReportConfig()

    llm   = get_llm()
    salt  = settings.ENCRYPTION_KEY[:16]

    # تحويل البيانات إلى نص
    data_json = json.dumps(data, ensure_ascii=False, indent=2, default=str)

    # تطبيق Masking إذا كان LLM خارجياً
    mappings: dict = {}
    if llm.provider_name == "claude":
        mask_result = mask_sensitive_data(data_json, session_salt=salt)
        data_to_send = mask_result.masked_text
        mappings     = mask_result.mappings
    else:
        data_to_send = data_json

    # بناء Prompt
    prompt = f"""
نوع البيانات: {data_type}
سؤال المدير: {query}

البيانات الخام:
{data_to_send}

اكتب تقريراً تنفيذياً عربياً واضحاً يجيب على سؤال المدير مباشرة،
مع الإشارة للأرقام الدقيقة وإضافة توصيات عملية مختصرة.
"""

    resp = await llm.generate(
        prompt=prompt,
        system=REPORT_SYSTEM_PROMPT,
        temperature=0.3,
        max_tokens=config.max_tokens,
    )

    # استعادة البيانات الأصلية
    report = resp.content
    if mappings:
        report = unmask_data(report, mappings)

    return report, resp.total_tokens


# ═══════════════════════════════════════════════════════════
#  3. Integration Manager
# ═══════════════════════════════════════════════════════════

@dataclass
class IntegrationCallResult:
    """نتيجة استدعاء نظام خارجي كاملة."""
    success:       bool
    intent:        QueryIntent
    system_id:     str
    raw_data:      dict | list | None
    report:        str                    # التقرير الجاهز للمدير
    confidence:    float
    response_ms:   int
    tokens_used:   int = 0
    errors:        list[str] = field(default_factory=list)
    warnings:      list[str] = field(default_factory=list)
    masked_fields: int = 0
    from_cache:    bool = False


class IntegrationManager:
    """
    مدير التكامل المركزي.
    نقطة الدخول الوحيدة لجميع الاستعلامات عن الأنظمة الخارجية.
    """

    def __init__(self, use_mock: bool = True):
        """
        use_mock=True  → بيانات وهمية (للتطوير)
        use_mock=False → ربط حقيقي عبر Vault
        """
        self._adapters: dict[str, IntegrationBase] = {}
        self._use_mock   = use_mock
        self._vault      = get_vault()
        self._cache:     dict[str, tuple[dict, float]] = {}
        self._cache_ttl  = 120  # ثانيتان للميزانية (بيانات حساسة = ttl قصير)

        if use_mock:
            self._register_mock_adapters()

    def _register_mock_adapters(self) -> None:
        """تسجيل Mock Adapters للتطوير."""
        from app.integrations.adapters import get_mock_erp, get_mock_hr
        self._adapters["erp_finance"] = get_mock_erp()
        self._adapters["hr_leaves"]   = get_mock_hr()
        log.info("IntegrationManager: Mock adapters registered")

    async def register_real_adapter(
        self,
        system_id:   str,
        system_type: str,
        adapter_cls,
    ) -> bool:
        """
        تسجيل Adapter حقيقي باستخدام Credentials من الـ Vault.

        مثال:
            await manager.register_real_adapter(
                "sap_prod", "erp_finance", ERPFinanceAdapterImpl
            )
        """
        try:
            creds_dict = await self._vault.load_credentials(system_id)
            from app.integrations.base import IntegrationCredentials, AuthMethod
            creds = IntegrationCredentials(
                system_id=system_id,
                base_url=creds_dict.get("base_url", ""),
                auth_method=AuthMethod(creds_dict.get("auth_method", "api_key")),
                api_key=creds_dict.get("api_key"),
                client_id=creds_dict.get("client_id"),
                client_secret=creds_dict.get("client_secret"),
                hmac_secret=creds_dict.get("hmac_secret"),
            )
            adapter = adapter_cls(creds)
            connected = await adapter.connect()
            if connected:
                self._adapters[system_type] = adapter
                log.info("Adapter registered", system_id=system_id, type=system_type)
                return True
            else:
                log.error("Adapter connection failed", system_id=system_id)
                return False
        except Exception as e:
            log.error("Adapter registration error", system_id=system_id, error=str(e))
            return False

    # ── Main Entry Point ──────────────────────────────────

    async def process_query(
        self,
        query:       str,
        user_role:   str = "analyst",
        employee_id: str | None = None,
        report_config: ReportConfig | None = None,
    ) -> IntegrationCallResult:
        """
        معالجة سؤال طبيعي وإرجاع تقرير كامل.

        مسار:
        query → Intent Detection → Adapter → Data → LLM → Report
        """
        t_start = time.time()

        # ── 1. كشف النية ─────────────────────────────────
        intent_result = detect_intent(query)
        log.info(
            "Intent detected",
            intent=intent_result.intent.value,
            confidence=intent_result.confidence,
            query_snippet=query[:60],
        )

        # ── 2. التحقق من الصلاحيات ───────────────────────
        rbac_ok, rbac_msg = self._check_rbac(intent_result.intent, user_role)
        if not rbac_ok:
            return IntegrationCallResult(
                success=False,
                intent=intent_result.intent,
                system_id="rbac",
                raw_data=None,
                report=f"⚠️ غير مسموح لك بهذا الاستعلام.\n{rbac_msg}",
                confidence=intent_result.confidence,
                response_ms=int((time.time() - t_start) * 1000),
                errors=[rbac_msg],
            )

        # ── 3. استدعاء الـ Adapter المناسب ────────────────
        try:
            raw_response = await self._dispatch(
                intent_result, employee_id, user_role
            )
        except Exception as e:
            log.error("Dispatch error", error=str(e))
            return IntegrationCallResult(
                success=False,
                intent=intent_result.intent,
                system_id="dispatch",
                raw_data=None,
                report=f"❌ تعذّر الاتصال بالنظام الخارجي: {e}",
                confidence=intent_result.confidence,
                response_ms=int((time.time() - t_start) * 1000),
                errors=[str(e)],
            )

        if not raw_response.success:
            error_text = "; ".join(raw_response.errors)
            return IntegrationCallResult(
                success=False,
                intent=intent_result.intent,
                system_id=raw_response.system_id,
                raw_data=None,
                report=f"❌ {error_text}",
                confidence=intent_result.confidence,
                response_ms=int((time.time() - t_start) * 1000),
                errors=raw_response.errors,
            )

        # ── 4. توليد التقرير عبر LLM ─────────────────────
        # إذا كانت هناك summary جاهزة من الـ Adapter، استخدمها مباشرة
        if raw_response.summary:
            report = raw_response.summary
            tokens = 0
        else:
            report, tokens = await generate_executive_report(
                data=raw_response.data or {},
                data_type=raw_response.data_type,
                query=query,
                config=report_config,
            )

        return IntegrationCallResult(
            success=True,
            intent=intent_result.intent,
            system_id=raw_response.system_id,
            raw_data=raw_response.data,
            report=report,
            confidence=intent_result.confidence,
            response_ms=int((time.time() - t_start) * 1000),
            tokens_used=tokens,
            masked_fields=raw_response.masked_fields,
        )

    # ── Dispatch ──────────────────────────────────────────

    async def _dispatch(
        self,
        intent:      IntentResult,
        employee_id: str | None,
        user_role:   str,
    ) -> StandardResponse:
        """توجيه الطلب للـ Adapter الصحيح."""
        params = intent.params
        it     = intent.intent

        # ──── ERP Finance ─────────────────────────────────
        if it == QueryIntent.BUDGET_QUERY:
            adapter = self._get_adapter("erp_finance")
            from app.integrations.adapters import ERPFinanceAdapterImpl, MockERPFinanceAdapter
            erp = adapter  # type: ignore
            return await erp.get_budget_status(
                fiscal_year=params.get("fiscal_year"),
                cost_center=params.get("cost_center"),
            )

        elif it == QueryIntent.PURCHASE_ORDERS:
            adapter = self._get_adapter("erp_finance")
            return await adapter.safe_fetch("/purchase-orders", params)   # type: ignore

        elif it == QueryIntent.INVOICES:
            adapter = self._get_adapter("erp_finance")
            erp = adapter  # type: ignore
            return await erp.get_invoices()

        # ──── HR Leaves ───────────────────────────────────
        elif it == QueryIntent.LEAVE_BALANCE:
            adapter = self._get_adapter("hr_leaves")
            emp_id  = params.get("employee_id") or employee_id or "EMP-001"
            return await adapter.get_leave_balance(emp_id)   # type: ignore

        elif it == QueryIntent.SUBMIT_LEAVE:
            adapter = self._get_adapter("hr_leaves")
            emp_id  = params.get("employee_id") or employee_id or "EMP-001"

            # التحقق من وجود التواريخ
            if not params.get("start_date") or not params.get("end_date"):
                return StandardResponse(
                    success=False,
                    system_id="hr_leaves",
                    data_type="error",
                    errors=["يرجى تحديد تاريخ البداية والنهاية. مثال: من 2025-03-01 إلى 2025-03-07"],
                )

            return await adapter.submit_leave_request(   # type: ignore
                employee_id=emp_id,
                leave_type=params.get("leave_type", "annual"),
                start_date=params["start_date"],
                end_date=params["end_date"],
                reason=intent.raw_query,
            )

        elif it == QueryIntent.LEAVE_STATUS:
            adapter = self._get_adapter("hr_leaves")
            emp_id  = params.get("employee_id") or employee_id
            return await adapter.get_leave_requests(employee_id=emp_id)   # type: ignore

        elif it == QueryIntent.APPROVE_LEAVE:
            if user_role not in ("admin", "super_admin", "hr_analyst"):
                return StandardResponse(
                    success=False,
                    system_id="hr_leaves",
                    data_type="error",
                    errors=["الموافقة على الإجازات تتطلب دور مدير أو HR"],
                )
            adapter = self._get_adapter("hr_leaves")
            return await adapter.approve_leave_request(   # type: ignore
                request_id=params.get("request_id", ""),
                approver_id=employee_id or "MANAGER",
                notes=intent.raw_query,
            )

        else:
            return StandardResponse(
                success=False,
                system_id="unknown",
                data_type="error",
                errors=["لم أتمكن من تحديد النظام المناسب للإجابة على سؤالك. جرّب صياغة أوضح."],
            )

    def _get_adapter(self, system_type: str) -> IntegrationBase:
        adapter = self._adapters.get(system_type)
        if not adapter:
            raise RuntimeError(
                f"لا يوجد Adapter مسجّل للنظام '{system_type}'. "
                f"تحقق من إعدادات الربط في integration_settings."
            )
        return adapter

    # ── RBAC ─────────────────────────────────────────────

    def _check_rbac(self, intent: QueryIntent, user_role: str) -> tuple[bool, str]:
        """فحص صلاحية المستخدم لهذه النية."""
        ROLE_PERMISSIONS: dict[QueryIntent, set[str]] = {
            QueryIntent.BUDGET_QUERY:    {"analyst", "admin", "super_admin"},
            QueryIntent.PURCHASE_ORDERS: {"analyst", "admin", "super_admin"},
            QueryIntent.INVOICES:        {"analyst", "admin", "super_admin"},
            QueryIntent.COST_CENTERS:    {"analyst", "admin", "super_admin"},
            QueryIntent.LEAVE_BALANCE:   {"viewer", "analyst", "hr_analyst", "admin", "super_admin"},
            QueryIntent.SUBMIT_LEAVE:    {"viewer", "analyst", "hr_analyst", "admin", "super_admin"},
            QueryIntent.LEAVE_STATUS:    {"viewer", "analyst", "hr_analyst", "admin", "super_admin"},
            QueryIntent.APPROVE_LEAVE:   {"hr_analyst", "admin", "super_admin"},
            QueryIntent.EMPLOYEE_INFO:   {"hr_analyst", "admin", "super_admin"},
            QueryIntent.HEADCOUNT:       {"analyst", "hr_analyst", "admin", "super_admin"},
            QueryIntent.STOCK_LEVELS:    {"analyst", "admin", "super_admin"},
            QueryIntent.UNKNOWN:         {"viewer", "analyst", "hr_analyst", "admin", "super_admin"},
        }

        allowed = ROLE_PERMISSIONS.get(intent, set())
        if user_role in allowed:
            return True, ""

        role_labels = {
            "viewer":      "مستعرض",
            "analyst":     "محلل",
            "hr_analyst":  "محلل HR",
            "admin":       "مدير",
            "super_admin": "مدير عام",
        }
        allowed_labels = [role_labels.get(r, r) for r in sorted(allowed)]
        return False, (
            f"دورك الحالي '{role_labels.get(user_role, user_role)}' "
            f"لا يملك صلاحية هذا الاستعلام. "
            f"الأدوار المسموح لها: {', '.join(allowed_labels)}"
        )

    # ── Health Dashboard ─────────────────────────────────

    async def health_summary(self) -> dict:
        """ملخص صحة جميع الأنظمة المسجّلة."""
        systems: list[dict] = []
        for name, adapter in self._adapters.items():
            try:
                status = await adapter.health_check()
            except Exception:
                status = ConnectionStatus.ERROR
            systems.append({
                "system_id":     name,
                "type":          adapter.integration_type.value,
                "status":        status.value,
                "circuit_state": adapter.circuit.state.value,
                "mock":          self._use_mock,
            })
        return {
            "total":     len(systems),
            "connected": sum(1 for s in systems if s["status"] == "connected"),
            "systems":   systems,
            "vault_systems": await get_vault().list_systems(),
        }


# ═══════════════════════════════════════════════════════════
#  4. Singleton
# ═══════════════════════════════════════════════════════════

_manager: IntegrationManager | None = None


def get_integration_manager(use_mock: bool = True) -> IntegrationManager:
    """Singleton للـ IntegrationManager."""
    global _manager
    if _manager is None:
        _manager = IntegrationManager(use_mock=use_mock)
    return _manager
