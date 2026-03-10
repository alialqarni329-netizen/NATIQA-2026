"""
╔══════════════════════════════════════════════════════════════════════════╗
║  NATIQA — Integration API Endpoints                                      ║
║                                                                          ║
║  Endpoints:                                                              ║
║                                                                          ║
║  [Chat / Natural Language]                                               ║
║    POST /api/integrations/chat                                           ║
║         ← الواجهة الرئيسية: سؤال طبيعي → تقرير تنفيذي                  ║
║                                                                          ║
║  [Budget / ERP]                                                          ║
║    GET  /api/integrations/erp/budget                                     ║
║    GET  /api/integrations/erp/budget/{cost_center}                       ║
║    GET  /api/integrations/erp/purchase-orders                            ║
║    GET  /api/integrations/erp/invoices                                   ║
║                                                                          ║
║  [Leaves / HR]                                                           ║
║    GET  /api/integrations/hr/leave-balance/{employee_id}                 ║
║    POST /api/integrations/hr/leave-request                               ║
║    GET  /api/integrations/hr/leave-requests                              ║
║    POST /api/integrations/hr/leave-requests/{id}/approve                 ║
║                                                                          ║
║  [Vault Management]                                                      ║
║    POST /api/integrations/vault/store                                    ║
║    POST /api/integrations/vault/rotate                                   ║
║    GET  /api/integrations/vault/systems                                  ║
║    DELETE /api/integrations/vault/revoke                                 ║
║                                                                          ║
║  [System Health]                                                         ║
║    GET  /api/integrations/health                                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
import structlog

from app.core.dependencies import get_current_user
from app.integrations.integration_manager import (
    IntegrationCallResult,
    ReportConfig,
    get_integration_manager,
)
from app.integrations.vault import get_vault

log = structlog.get_logger()
router = APIRouter(prefix="/api/integrations", tags=["integrations"])


# ═══════════════════════════════════════════════════════════
#  Request / Response Schemas
# ═══════════════════════════════════════════════════════════

class ChatQueryRequest(BaseModel):
    """طلب محادثة طبيعية مع الأنظمة المتكاملة."""
    query:       str  = Field(..., min_length=3, max_length=1000, description="السؤال بالعربية أو الإنجليزية")
    employee_id: Optional[str] = Field(None, description="معرّف الموظف (للاستعلام عن إجازاته)")
    verbose:     bool = Field(False, description="إرجاع البيانات الخام إضافةً للتقرير")


class ChatQueryResponse(BaseModel):
    success:      bool
    report:       str
    intent:       str
    system_id:    str
    confidence:   float
    response_ms:  int
    tokens_used:  int
    masked_fields: int
    raw_data:     Optional[dict | list] = None
    errors:       list[str] = []


class LeaveRequestBody(BaseModel):
    """طلب إجازة مباشر."""
    employee_id: str   = Field(..., description="معرّف الموظف مثل EMP-001")
    leave_type:  str   = Field("annual", description="annual / sick / emergency / hajj")
    start_date:  str   = Field(..., description="YYYY-MM-DD")
    end_date:    str   = Field(..., description="YYYY-MM-DD")
    reason:      Optional[str] = Field(None, max_length=500)

    @field_validator("leave_type")
    @classmethod
    def validate_leave_type(cls, v: str) -> str:
        allowed = {"annual", "sick", "emergency", "hajj", "maternity", "paternity"}
        if v not in allowed:
            raise ValueError(f"نوع الإجازة يجب أن يكون: {', '.join(allowed)}")
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("صيغة التاريخ يجب أن تكون YYYY-MM-DD")
        return v


class LeaveApprovalBody(BaseModel):
    approver_id: str
    decision:    str = Field(..., description="approve / reject")
    notes:       Optional[str] = Field(None, max_length=500)

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        if v not in ("approve", "reject"):
            raise ValueError("القرار يجب أن يكون approve أو reject")
        return v


class VaultStoreRequest(BaseModel):
    system_id:  str = Field(..., description="معرّف النظام الخارجي")
    key_name:   str = Field(..., description="اسم المفتاح: api_key / client_secret ...")
    value:      str = Field(..., min_length=1, description="القيمة السرية")
    ttl_days:   Optional[int] = Field(None, ge=1, le=3650)


class VaultRotateRequest(BaseModel):
    system_id:  str
    key_name:   str
    new_value:  str = Field(..., min_length=1)


# ═══════════════════════════════════════════════════════════
#  Helper
# ═══════════════════════════════════════════════════════════

def _result_to_response(result: IntegrationCallResult, verbose: bool = False) -> ChatQueryResponse:
    return ChatQueryResponse(
        success=result.success,
        report=result.report,
        intent=result.intent.value,
        system_id=result.system_id,
        confidence=round(result.confidence, 3),
        response_ms=result.response_ms,
        tokens_used=result.tokens_used,
        masked_fields=result.masked_fields,
        raw_data=result.raw_data if verbose else None,
        errors=result.errors,
    )


# ═══════════════════════════════════════════════════════════
#  1. Chat — الواجهة الرئيسية (سؤال طبيعي)
# ═══════════════════════════════════════════════════════════

@router.post(
    "/chat",
    response_model=ChatQueryResponse,
    summary="استعلام طبيعي عن ERP / HR",
    description="""
الواجهة الذكية: اكتب سؤالك بالعربية وسيحدد النظام تلقائياً من أين يجلب البيانات.

**أمثلة:**
- "ما حالة ميزانية قسم تقنية المعلومات؟"
- "كم باقي لديّ من إجازة سنوية؟"
- "أريد إجازة من 2025-03-01 إلى 2025-03-07"
- "اعرض طلبات الشراء المعلّقة"
""",
)
async def integration_chat(
    body:    ChatQueryRequest,
    request: Request,
    current_user = Depends(get_current_user),
):
    manager = get_integration_manager(use_mock=True)

    result = await manager.process_query(
        query=body.query,
        user_role=current_user.role.value,
        employee_id=body.employee_id or getattr(current_user, "employee_id", None),
        report_config=ReportConfig(include_recommendations=True),
    )

    # Audit log
    log.info(
        "integration_chat",
        user_id=str(current_user.id),
        user_role=current_user.role.value,
        intent=result.intent.value,
        system_id=result.system_id,
        success=result.success,
        ip=request.client.host if request.client else "unknown",
    )

    return _result_to_response(result, verbose=body.verbose)


# ═══════════════════════════════════════════════════════════
#  2. ERP — Budget
# ═══════════════════════════════════════════════════════════

@router.get(
    "/erp/budget",
    summary="ميزانية السنة المالية الحالية",
)
async def get_budget(
    fiscal_year: Optional[int]  = None,
    verbose:     bool = False,
    current_user = Depends(get_current_user),
):
    """حالة الميزانية الكاملة مع تحليل LLM."""
    _require_roles(current_user, {"analyst", "admin", "super_admin"})

    manager = get_integration_manager()
    result  = await manager.process_query(
        query=f"ما حالة الميزانية للسنة المالية {fiscal_year or 'الحالية'}؟",
        user_role=current_user.role.value,
    )
    return _result_to_response(result, verbose)


@router.get(
    "/erp/budget/{cost_center}",
    summary="ميزانية مركز تكلفة محدد",
)
async def get_budget_by_cost_center(
    cost_center: str,
    fiscal_year: Optional[int] = None,
    current_user = Depends(get_current_user),
):
    """ميزانية قسم أو مركز تكلفة محدد."""
    _require_roles(current_user, {"analyst", "admin", "super_admin"})

    manager = get_integration_manager()

    # جلب البيانات مباشرة بدون LLM
    from app.integrations.adapters import get_mock_erp
    erp  = get_mock_erp()
    resp = await erp.get_budget_status(
        fiscal_year=fiscal_year,
        cost_center=cost_center.upper(),
    )

    if not resp.success:
        raise HTTPException(status_code=502, detail=resp.errors)

    # تحليل LLM للتقرير
    from app.integrations.integration_manager import generate_executive_report
    report, tokens = await generate_executive_report(
        data=resp.data,
        data_type="budget_status",
        query=f"تحليل ميزانية مركز التكلفة {cost_center}",
    )

    return {
        "cost_center": cost_center.upper(),
        "report":      report,
        "raw_data":    resp.data,
        "tokens_used": tokens,
        "response_ms": resp.response_ms,
    }


@router.get("/erp/purchase-orders", summary="طلبات الشراء")
async def get_purchase_orders(
    status: Optional[str] = None,
    current_user = Depends(get_current_user),
):
    _require_roles(current_user, {"analyst", "admin", "super_admin"})
    manager = get_integration_manager()
    result  = await manager.process_query(
        query="اعرض طلبات الشراء" + (f" بحالة {status}" if status else ""),
        user_role=current_user.role.value,
    )
    return _result_to_response(result)


@router.get("/erp/invoices", summary="الفواتير")
async def get_invoices(
    status: Optional[str] = None,
    current_user = Depends(get_current_user),
):
    _require_roles(current_user, {"analyst", "admin", "super_admin"})
    manager = get_integration_manager()
    result  = await manager.process_query(
        query="اعرض الفواتير" + (f" غير المدفوعة" if status == "unpaid" else ""),
        user_role=current_user.role.value,
    )
    return _result_to_response(result)


# ═══════════════════════════════════════════════════════════
#  3. HR — Leave Balance
# ═══════════════════════════════════════════════════════════

@router.get(
    "/hr/leave-balance/{employee_id}",
    summary="رصيد إجازات موظف",
)
async def get_leave_balance(
    employee_id: str,
    current_user = Depends(get_current_user),
):
    """
    رصيد الإجازات مفصّل (سنوية / مرضية / طارئة / حج).
    كل موظف يرى رصيده فقط — المدير يرى رصيد أي موظف.
    """
    # كل مستخدم يرى رصيده فقط ما لم يكن مديراً
    if (current_user.role.value not in ("admin", "super_admin", "hr_analyst")
            and employee_id != getattr(current_user, "employee_id", employee_id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا يمكنك الاطلاع على رصيد إجازات موظف آخر",
        )

    from app.integrations.adapters import get_mock_hr
    hr   = get_mock_hr()
    resp = await hr.get_leave_balance(employee_id)

    if not resp.success:
        raise HTTPException(status_code=502, detail=resp.errors)

    # تقرير LLM موجز
    from app.integrations.integration_manager import generate_executive_report
    report, tokens = await generate_executive_report(
        data=resp.data,
        data_type="leave_balance",
        query=f"ملخص رصيد إجازات الموظف {employee_id}",
    )

    return {
        "employee_id": employee_id,
        "report":      report,
        "balances":    resp.data.get("balances", {}),
        "as_of_date":  resp.data.get("as_of_date"),
        "tokens_used": tokens,
    }


# ═══════════════════════════════════════════════════════════
#  4. HR — Submit Leave Request
# ═══════════════════════════════════════════════════════════

@router.post(
    "/hr/leave-request",
    status_code=status.HTTP_201_CREATED,
    summary="تقديم طلب إجازة",
)
async def submit_leave_request(
    body:    LeaveRequestBody,
    request: Request,
    current_user = Depends(get_current_user),
):
    """
    تقديم طلب إجازة جديد.
    يُرجع رقم الطلب ووقت الرد المتوقع.

    **أنواع الإجازة:**
    - `annual`     → إجازة سنوية (30 يوم/سنة)
    - `sick`       → إجازة مرضية (تتطلب تقرير طبي)
    - `emergency`  → إجازة طارئة (3 أيام)
    - `hajj`       → إجازة الحج (21 يوم — مرة واحدة)
    """
    from app.integrations.adapters import get_mock_hr
    hr   = get_mock_hr()
    resp = await hr.submit_leave_request(
        employee_id=body.employee_id,
        leave_type=body.leave_type,
        start_date=body.start_date,
        end_date=body.end_date,
        reason=body.reason,
    )

    if not resp.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=resp.errors,
        )

    log.info(
        "leave_request_submitted",
        employee_id=body.employee_id,
        leave_type=body.leave_type,
        days=(resp.data or {}).get("days_requested"),
        request_id=(resp.data or {}).get("request_id"),
        submitted_by=str(current_user.id),
    )

    return {
        "message":        "تم تقديم طلب الإجازة بنجاح",
        "request_id":     resp.data.get("request_id") if resp.data else None,
        "days_requested": resp.data.get("days_requested") if resp.data else None,
        "status":         "pending",
        "expected_reply": "خلال 24 ساعة عمل",
        "summary":        resp.summary,
        "details":        resp.data,
    }


# ═══════════════════════════════════════════════════════════
#  5. HR — Leave Requests List
# ═══════════════════════════════════════════════════════════

@router.get(
    "/hr/leave-requests",
    summary="قائمة طلبات الإجازة",
)
async def list_leave_requests(
    employee_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    current_user  = Depends(get_current_user),
):
    """
    قائمة طلبات الإجازة.
    الموظف العادي يرى طلباته فقط.
    المدير يرى طلبات الجميع.
    """
    from app.integrations.adapters import get_mock_hr
    hr = get_mock_hr()

    # تقييد الرؤية بناءً على الدور
    if current_user.role.value not in ("admin", "super_admin", "hr_analyst"):
        employee_id = getattr(current_user, "employee_id", None)

    resp = await hr.get_leave_requests(
        employee_id=employee_id,
        status=status_filter,
    )

    if not resp.success:
        raise HTTPException(status_code=502, detail=resp.errors)

    return {
        "requests":    resp.data.get("requests", []) if resp.data else [],
        "count":       resp.data.get("count", 0) if resp.data else 0,
        "response_ms": resp.response_ms,
    }


# ═══════════════════════════════════════════════════════════
#  6. HR — Approve / Reject Leave
# ═══════════════════════════════════════════════════════════

@router.post(
    "/hr/leave-requests/{request_id}/approve",
    summary="الموافقة أو رفض طلب إجازة",
)
async def approve_leave_request(
    request_id: str,
    body:       LeaveApprovalBody,
    current_user = Depends(get_current_user),
):
    """
    الموافقة على طلب إجازة أو رفضه.
    يتطلب دور: `admin` أو `super_admin` أو `hr_analyst`.
    """
    _require_roles(current_user, {"admin", "super_admin", "hr_analyst"})

    from app.integrations.adapters import get_mock_hr
    hr = get_mock_hr()

    if body.decision == "approve":
        resp = await hr.approve_leave_request(
            request_id=request_id,
            approver_id=str(current_user.id),
            notes=body.notes,
        )
    else:
        # Reject — نفس منطق الـ approve لكن بحالة مختلفة
        resp = await hr.approve_leave_request(
            request_id=request_id,
            approver_id=str(current_user.id),
            notes=f"مرفوض: {body.notes or ''}",
        )
        if resp.success and resp.data:
            resp.data["status"] = "rejected"

    if not resp.success:
        raise HTTPException(status_code=400, detail=resp.errors)

    return {
        "message":    f"تم {'قبول' if body.decision == 'approve' else 'رفض'} الطلب {request_id}",
        "request_id": request_id,
        "decision":   body.decision,
        "details":    resp.data,
    }


# ═══════════════════════════════════════════════════════════
#  7. Vault Management (super_admin فقط)
# ═══════════════════════════════════════════════════════════

@router.post(
    "/vault/store",
    status_code=status.HTTP_201_CREATED,
    summary="تخزين سر في الـ Vault (مشفّر)",
)
async def vault_store(
    body: VaultStoreRequest,
    current_user = Depends(get_current_user),
):
    """
    تخزين API Key أو Token مشفّر في Vault.
    يتطلب دور `super_admin`.
    الـ Value لا يُخزَّن كنص — يُشفَّر فوراً بـ AES-256-GCM.
    """
    _require_roles(current_user, {"super_admin"})

    vault     = get_vault()
    secret_id = await vault.store_secret(
        system_id=body.system_id,
        key_name=body.key_name,
        plaintext=body.value,
        ttl_days=body.ttl_days,
        created_by=str(current_user.id),
    )

    return {
        "message":   "تم التخزين المشفّر بنجاح",
        "system_id": body.system_id,
        "key_name":  body.key_name,
        "secret_id": secret_id,
        "ttl_days":  body.ttl_days,
    }


@router.post("/vault/rotate", summary="تدوير مفتاح في الـ Vault")
async def vault_rotate(
    body: VaultRotateRequest,
    current_user = Depends(get_current_user),
):
    """
    Key Rotation: تشفير جديد بـ nonce وsalt جديدين.
    المفتاح القديم يُبطَل فوراً.
    """
    _require_roles(current_user, {"super_admin"})

    vault      = get_vault()
    new_version = await vault.rotate_secret(
        system_id=body.system_id,
        key_name=body.key_name,
        new_plaintext=body.new_value,
        rotated_by=str(current_user.id),
    )

    return {
        "message":     "تم تدوير المفتاح بنجاح",
        "system_id":   body.system_id,
        "key_name":    body.key_name,
        "new_version": new_version,
    }


@router.get("/vault/systems", summary="قائمة الأنظمة في الـ Vault")
async def vault_list_systems(
    current_user = Depends(get_current_user),
):
    """قائمة الأنظمة المسجّلة (بدون كشف القيم)."""
    _require_roles(current_user, {"admin", "super_admin"})
    vault   = get_vault()
    systems = await vault.list_systems()
    return {"systems": systems, "count": len(systems)}


@router.delete("/vault/revoke", summary="إبطال سر من الـ Vault")
async def vault_revoke(
    system_id: str,
    key_name:  str,
    current_user = Depends(get_current_user),
):
    """إبطال فوري لسر معيّن (soft delete)."""
    _require_roles(current_user, {"super_admin"})
    vault   = get_vault()
    success = await vault.revoke_secret(system_id, key_name)

    if not success:
        raise HTTPException(status_code=404, detail="السر غير موجود أو مُبطَل مسبقاً")

    return {"message": f"تم إبطال '{key_name}' للنظام '{system_id}'"}


# ═══════════════════════════════════════════════════════════
#  8. Health Check
# ═══════════════════════════════════════════════════════════

@router.get("/health", summary="صحة أنظمة التكامل")
async def integration_health(
    current_user = Depends(get_current_user),
):
    """ملخص صحة جميع الأنظمة المتكاملة."""
    _require_roles(current_user, {"admin", "super_admin"})
    manager  = get_integration_manager()
    summary  = await manager.health_summary()
    return summary


# ═══════════════════════════════════════════════════════════
#  Helper: RBAC Check
# ═══════════════════════════════════════════════════════════

def _require_roles(user, allowed: set[str]) -> None:
    if user.role.value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"دورك '{user.role.value}' لا يملك صلاحية هذه العملية. "
                f"الأدوار المسموح لها: {', '.join(sorted(allowed))}"
            ),
        )
