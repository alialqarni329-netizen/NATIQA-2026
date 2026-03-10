"""
╔══════════════════════════════════════════════════════════════════════════╗
║  NATIQA — ERP/HR Integration API                                        ║
║                                                                          ║
║  POST /api/erp/connect           ← ربط نظام جديد                       ║
║  GET  /api/erp/systems           ← قائمة الأنظمة المربوطة              ║
║  GET  /api/erp/health            ← حالة الاتصال بكل نظام               ║
║  POST /api/erp/fetch             ← جلب بيانات من نظام                  ║
║  POST /api/erp/action            ← تنفيذ إجراء (طلب إجازة، إلخ)        ║
║  DELETE /api/erp/{name}          ← فصل نظام                            ║
║                                                                          ║
║  POST /api/erp/chat              ← سؤال طبيعي يجلب من ERP + RAG        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
import structlog

from app.core.dependencies import get_current_user, require_admin
from app.integrations.erp_connectors import (
    ERPConfig, ERPSystem, ERPDataType, get_erp_registry,
)

log = structlog.get_logger()
router = APIRouter(prefix="/api/erp", tags=["ERP Integrations"])


# ═══════════════════════════════════════════════════════════
#  Schemas
# ═══════════════════════════════════════════════════════════

class ConnectRequest(BaseModel):
    name:         str = Field(..., description="اسم مرجعي للنظام مثل odoo_main أو rawa_hr")
    system:       ERPSystem
    base_url:     str = Field(..., description="رابط API الأساسي")
    auth_type:    str = Field("api_key", description="api_key | basic | odoo_rpc | oauth2")
    api_key:      str = ""
    username:     str = ""
    password:     str = ""
    database:     str = Field("", description="اسم قاعدة البيانات — لـ Odoo فقط")
    client_id:    str = ""
    client_secret: str = ""
    extra:        dict = Field(default_factory=dict, description="إعدادات إضافية حسب النظام")


class FetchRequest(BaseModel):
    system_name: str = Field(..., description="اسم النظام المسجّل")
    data_type:   ERPDataType
    params:      dict = Field(default_factory=dict, description="معاملات البحث")


class ActionRequest(BaseModel):
    system_name: str
    action:      str = Field(..., description="submit_leave | approve_leave | إلخ")
    params:      dict = Field(default_factory=dict)


class ERPChatRequest(BaseModel):
    question:    str = Field(..., min_length=3, max_length=1000)
    project_id:  Optional[str] = None
    employee_id: Optional[str] = None


# ═══════════════════════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════════════════════

@router.post("/connect", summary="ربط نظام ERP/HR جديد")
async def connect_erp(
    body: ConnectRequest,
    admin=Depends(require_admin),
):
    """
    يُسجّل نظام ERP/HR في ناطقة.
    يتطلب دور admin أو super_admin.

    مثال لأودو:
    ```json
    {
      "name": "odoo_main",
      "system": "odoo",
      "base_url": "https://your-odoo.com",
      "auth_type": "odoo_rpc",
      "username": "admin@company.com",
      "password": "password",
      "database": "company_db"
    }
    ```

    مثال لرواء:
    ```json
    {
      "name": "rawa_hr",
      "system": "rawa",
      "base_url": "https://api.rawa.com.sa/v1",
      "auth_type": "api_key",
      "api_key": "your_api_key"
    }
    ```
    """
    registry = get_erp_registry()

    config = ERPConfig(
        system=body.system,
        base_url=body.base_url.rstrip("/"),
        auth_type=body.auth_type,
        api_key=body.api_key,
        username=body.username,
        password=body.password,
        database=body.database,
        client_id=body.client_id,
        client_secret=body.client_secret,
        extra=body.extra,
    )

    registry.register(body.name, config)

    # Test connection
    connector = registry.get(body.name)
    is_healthy = False
    try:
        is_healthy = await connector.health()
    except Exception as e:
        log.warning("ERP health check failed after connect", name=body.name, error=str(e))

    return {
        "success": True,
        "name": body.name,
        "system": body.system.value,
        "connected": is_healthy,
        "message": "تم ربط النظام بنجاح" if is_healthy else "تم التسجيل لكن تحقق الاتصال فشل — تأكد من الإعدادات",
    }


@router.get("/systems", summary="قائمة الأنظمة المربوطة")
async def list_systems(user=Depends(get_current_user)):
    registry = get_erp_registry()
    return {
        "systems": registry.list_systems(),
        "count": len(registry.list_systems()),
    }


@router.get("/health", summary="حالة الاتصال بكل الأنظمة")
async def health_check(user=Depends(get_current_user)):
    registry = get_erp_registry()
    results  = await registry.health_all()
    return {
        "systems": results,
        "all_healthy": all(results.values()) if results else False,
    }


@router.post("/fetch", summary="جلب بيانات من نظام ERP")
async def fetch_data(
    body: FetchRequest,
    user=Depends(get_current_user),
):
    """
    جلب بيانات محددة من نظام مُسجَّل.

    أنواع البيانات المتاحة:
    - budget, invoices, purchase_orders, cost_centers
    - employees, leave_balance, leave_requests, payroll
    - sales, inventory, custom_query

    مثال — جلب ميزانية الربع الأول:
    ```json
    {
      "system_name": "odoo_main",
      "data_type": "budget",
      "params": {"year": 2026, "quarter": 1}
    }
    ```
    """
    registry = get_erp_registry()
    result   = await registry.fetch_from(body.system_name, body.data_type, body.params)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"فشل جلب البيانات من {body.system_name}: {result.error}"
        )
    return {
        "success": True,
        "system":  result.system,
        "type":    result.data_type,
        "data":    result.data,
        "fetched_at": result.fetched_at,
    }


@router.post("/action", summary="تنفيذ إجراء في نظام ERP")
async def execute_action(
    body: ActionRequest,
    user=Depends(get_current_user),
):
    """
    تنفيذ إجراء في نظام ERP مثل تقديم طلب إجازة.

    مثال — تقديم طلب إجازة في أودو:
    ```json
    {
      "system_name": "odoo_main",
      "action": "submit_leave",
      "params": {
        "employee_id": 42,
        "date_from": "2026-03-10",
        "date_to": "2026-03-15",
        "reason": "إجازة سنوية"
      }
    }
    ```
    """
    registry = get_erp_registry()
    result   = await registry.execute_in(body.system_name, body.action, body.params)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"فشل تنفيذ الإجراء: {result.error}"
        )
    return {
        "success": True,
        "system":  result.system,
        "action":  result.data_type,
        "result":  result.data,
    }


@router.delete("/{system_name}", summary="فصل نظام ERP")
async def disconnect_erp(
    system_name: str,
    admin=Depends(require_admin),
):
    registry = get_erp_registry()
    if not registry.get(system_name):
        raise HTTPException(status_code=404, detail=f"النظام '{system_name}' غير مسجّل")
    registry._connectors.pop(system_name, None)
    return {"success": True, "message": f"تم فصل النظام '{system_name}'"}


# ═══════════════════════════════════════════════════════════
#  Smart ERP + RAG Chat
# ═══════════════════════════════════════════════════════════

@router.post("/chat", summary="سؤال ذكي — يجمع ERP + قاعدة المعرفة")
async def erp_rag_chat(
    body: ERPChatRequest,
    user=Depends(get_current_user),
):
    """
    ناطقة تفهم السؤال → تجلب من ERP المناسب → تدمج مع RAG → تُجيب.

    أمثلة:
    - "ما ميزانية الربع الأول لعام 2026؟" → يجلب من ERP المالي
    - "كم رصيد إجازاتي المتبقي؟" → يجلب من HR
    - "ما حالة أوامر الشراء المعلّقة؟" → يجلب من ERP
    """
    from app.services.llm import get_llm
    import time

    start    = time.time()
    registry = get_erp_registry()
    llm      = get_llm()

    question = body.question

    # 1. تحليل السؤال لاختيار نوع البيانات المطلوب
    intent_prompt = f"""
حلّل السؤال التالي وحدد نوع البيانات المطلوبة من نظام ERP/HR.
أجب بـ JSON فقط بدون أي نص إضافي.

السؤال: {question}

أجب بهذا الشكل:
{{
  "needs_erp": true/false,
  "data_types": ["budget", "invoices", "leave_balance", "employees", "payroll", "purchase_orders", "sales"],
  "params": {{
    "year": null,
    "quarter": null,
    "month": null,
    "employee_id": null,
    "department": null
  }},
  "action": null
}}

أنواع البيانات المتاحة:
- budget: الميزانيات والمصروفات
- invoices: الفواتير
- purchase_orders: أوامر الشراء
- employees: بيانات الموظفين
- leave_balance: رصيد الإجازات
- leave_requests: طلبات الإجازة
- payroll: الرواتب
- sales: المبيعات
"""

    intent_resp = await llm.generate(
        prompt=intent_prompt,
        system="أنت محلل بيانات. أجب بـ JSON فقط.",
        temperature=0.1,
        max_tokens=300,
    )

    import json, re
    intent: dict = {}
    try:
        raw = intent_resp.content.strip()
        # استخراج JSON من الرد
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            intent = json.loads(match.group())
    except Exception as e:
        log.warning("Intent parsing failed", error=str(e))
        intent = {"needs_erp": False, "data_types": [], "params": {}}

    # 2. جلب البيانات من ERP إذا لزم
    erp_contexts: list[str] = []
    systems = registry.list_systems()

    if intent.get("needs_erp") and systems:
        params = {k: v for k, v in (intent.get("params") or {}).items() if v is not None}
        if body.employee_id:
            params["employee_id"] = body.employee_id

        for dtype_str in (intent.get("data_types") or []):
            try:
                dtype = ERPDataType(dtype_str)
            except ValueError:
                continue

            for sys_info in systems:
                result = await registry.fetch_from(sys_info["name"], dtype, params)
                if result.success:
                    erp_contexts.append(result.to_context())
                    log.info("ERP data fetched for chat", system=sys_info["name"], dtype=dtype_str)
                    break  # نكتفي بأول نظام يرد بنجاح

    # 3. بناء الـ prompt النهائي
    erp_section = ""
    if erp_contexts:
        erp_section = "\n\n**بيانات حية من الأنظمة المتصلة:**\n" + "\n\n".join(erp_contexts)

    # 4. RAG من قاعدة المعرفة (إذا كان project_id موجوداً)
    rag_section = ""
    if body.project_id:
        try:
            from app.services.rag_dept import query_rag_scoped
            rag_result = await query_rag_scoped(
                question=question,
                project_id=body.project_id,
                user=user,
                top_k=4,
            )
            if rag_result.get("answer") and "فارغة" not in rag_result["answer"]:
                rag_section = f"\n\n**معلومات من قاعدة المعرفة:**\n{rag_result['answer']}"
        except Exception as e:
            log.warning("RAG fetch failed in ERP chat", error=str(e))

    final_prompt = f"""
السؤال: {question}
{erp_section}
{rag_section}

أجب بالعربية بشكل مباشر ودقيق. إذا توفرت أرقام فاستشهد بها.
"""

    final_resp = await llm.generate(
        prompt=final_prompt,
        system=(
            "أنت مساعد مؤسسي ذكي في منصة ناطقة. "
            "لديك صلاحية الوصول لبيانات الأنظمة المتصلة. "
            "أجب بدقة مستنداً للبيانات الفعلية المقدمة."
        ),
        temperature=0.2,
        max_tokens=2048,
    )

    return {
        "answer":        final_resp.content,
        "used_erp":      len(erp_contexts) > 0,
        "erp_systems":   [s["name"] for s in systems] if erp_contexts else [],
        "used_rag":      bool(rag_section),
        "tokens":        final_resp.total_tokens,
        "response_time_ms": int((time.time() - start) * 1000),
    }
