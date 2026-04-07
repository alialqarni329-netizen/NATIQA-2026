"""
╔══════════════════════════════════════════════════════════════════════════╗
║  NATIQA — ERP & HR Connectors                                           ║
║                                                                          ║
║  يدعم الاتصال بـ:                                                        ║
║    • Odoo (JSON-RPC)      ← أودو                                         ║
║    • Rawa (REST API)      ← رواء (موارد بشرية سعودي)                   ║
║    • SAP S/4HANA (OData)  ← SAP                                         ║
║    • Oracle Fusion (REST) ← أوراكل                                      ║
║    • Masar / Qiwa (HR SA) ← مسار / قوى                                  ║
║    • Custom REST          ← أي نظام يدعم REST                            ║
║                                                                          ║
║  المبدأ: ناطقة تفهم السؤال → تختار النظام → تجلب البيانات              ║
║          → تمزجها مع RAG → تُجيب                                        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import httpx
import structlog

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════

class ERPSystem(str, Enum):
    ODOO       = "odoo"
    RAWA       = "rawa"
    SAP        = "sap"
    ORACLE     = "oracle"
    MASAR      = "masar"
    QIWA       = "qiwa"
    CUSTOM     = "custom"


class ERPDataType(str, Enum):
    BUDGET          = "budget"
    INVOICES        = "invoices"
    PURCHASE_ORDERS = "purchase_orders"
    COST_CENTERS    = "cost_centers"
    EMPLOYEES       = "employees"
    LEAVE_BALANCE   = "leave_balance"
    LEAVE_REQUESTS  = "leave_requests"
    PAYROLL         = "payroll"
    ASSETS          = "assets"
    INVENTORY       = "inventory"
    SALES           = "sales"
    CUSTOM_QUERY    = "custom_query"


# ═══════════════════════════════════════════════════════════
#  Config dataclass
# ═══════════════════════════════════════════════════════════

@dataclass
class ERPConfig:
    """إعدادات الاتصال بنظام ERP/HR — تُخزَّن مشفّرة في Vault."""
    system:     ERPSystem
    base_url:   str
    # Auth
    auth_type:  str = "api_key"   # api_key | oauth2 | basic | odoo_rpc
    api_key:    str = ""
    username:   str = ""
    password:   str = ""
    database:   str = ""          # لـ Odoo فقط
    client_id:  str = ""
    client_secret: str = ""
    # Settings
    timeout:    int = 30
    verify_ssl: bool = True
    extra:      dict = field(default_factory=dict)


@dataclass
class ERPResult:
    """نتيجة موحّدة من أي نظام ERP."""
    success:   bool
    system:    str
    data_type: str
    data:      Any
    error:     str = ""
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_context(self) -> str:
        """تحويل البيانات لنص سياق لـ RAG."""
        if not self.success:
            return f"[{self.system}] فشل جلب البيانات: {self.error}"
        return (
            f"[بيانات من {self.system} — {self.data_type}]\n"
            f"تاريخ الجلب: {self.fetched_at}\n\n"
            + json.dumps(self.data, ensure_ascii=False, indent=2)
        )


# ═══════════════════════════════════════════════════════════
#  Base Connector
# ═══════════════════════════════════════════════════════════

class BaseERPConnector:
    """قاعدة مشتركة لجميع الـ Connectors."""

    def __init__(self, config: ERPConfig):
        self.config = config
        self._token: str | None = None
        self._token_exp: float  = 0.0

    async def _client(self, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
            **kwargs,
        )

    async def fetch(self, data_type: ERPDataType, params: dict | None = None) -> ERPResult:
        """
        Subclasses must override this method.
        Returns a structured error response instead of raising NotImplementedError
        so callers always get a safe ERPResult.
        """
        system = getattr(self.config, "system", ERPSystem.CUSTOM)
        sys_name = system.value if hasattr(system, "value") else str(system)
        return ERPResult(
            success=False,
            system=sys_name,
            data_type=data_type.value if hasattr(data_type, "value") else str(data_type),
            data=None,
            error=f"جلب البيانات غير مُنفَّذ لهذا النوع من الأنظمة ({sys_name}). "
                  "يرجى استخدام GenericRESTConnector أو إضافة Connector مخصص.",
        )

    async def execute_action(self, action: str, params: dict) -> ERPResult:
        """
        Subclasses must override this method.
        Returns a structured error response instead of raising NotImplementedError.
        """
        system = getattr(self.config, "system", ERPSystem.CUSTOM)
        sys_name = system.value if hasattr(system, "value") else str(system)
        return ERPResult(
            success=False,
            system=sys_name,
            data_type=action,
            data=None,
            error=f"تنفيذ الإجراءات غير مُنفَّذ لهذا النوع من الأنظمة ({sys_name}). "
                  "يرجى استخدام GenericRESTConnector أو إضافة Connector مخصص.",
        )

    async def health(self) -> bool:
        """
        Subclasses must override this method.
        Returns False (unhealthy) instead of raising NotImplementedError.
        """
        log.warning(
            "health() not implemented for connector",
            system=getattr(self.config, "system", "unknown"),
        )
        return False


# ═══════════════════════════════════════════════════════════
#  Odoo Connector (JSON-RPC 2.0)
# ═══════════════════════════════════════════════════════════

class OdooConnector(BaseERPConnector):
    """
    يتصل بـ Odoo عبر JSON-RPC.
    يدعم Odoo 14 / 15 / 16 / 17.

    الإعدادات المطلوبة في ERPConfig:
        base_url  = "https://your-odoo.com"
        database  = "your_db_name"
        username  = "admin@company.com"
        password  = "odoo_password"
        auth_type = "odoo_rpc"
    """

    def __init__(self, config: ERPConfig):
        super().__init__(config)
        self._uid: int | None = None

    async def _authenticate(self) -> int:
        """تسجيل الدخول لـ Odoo والحصول على UID."""
        if self._uid:
            return self._uid
        async with await self._client() as client:
            resp = await client.post(
                "/web/dataset/call_kw",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "model": "res.users",
                        "method": "authenticate",
                        "args": [
                            self.config.database,
                            self.config.username,
                            self.config.password,
                            {},
                        ],
                        "kwargs": {},
                    },
                },
            )
            result = resp.json().get("result")
            if not result:
                raise ValueError("Odoo authentication failed")
            self._uid = result
            return self._uid

    async def _call(self, model: str, method: str, args: list, kwargs: dict | None = None) -> Any:
        uid = await self._authenticate()
        async with await self._client() as client:
            resp = await client.post(
                "/web/dataset/call_kw",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "model": model,
                        "method": method,
                        "args": [self.config.database, uid, self.config.password] + args,
                        "kwargs": kwargs or {},
                    },
                },
            )
            data = resp.json()
            if "error" in data:
                raise ValueError(data["error"].get("data", {}).get("message", str(data["error"])))
            return data.get("result")

    async def fetch(self, data_type: ERPDataType, params: dict | None = None) -> ERPResult:
        params = params or {}
        try:
            if data_type == ERPDataType.BUDGET:
                return await self._get_budget(params)
            elif data_type == ERPDataType.INVOICES:
                return await self._get_invoices(params)
            elif data_type == ERPDataType.PURCHASE_ORDERS:
                return await self._get_purchase_orders(params)
            elif data_type == ERPDataType.EMPLOYEES:
                return await self._get_employees(params)
            elif data_type == ERPDataType.LEAVE_BALANCE:
                return await self._get_leave_balance(params)
            elif data_type == ERPDataType.LEAVE_REQUESTS:
                return await self._get_leave_requests(params)
            elif data_type == ERPDataType.PAYROLL:
                return await self._get_payroll(params)
            elif data_type == ERPDataType.SALES:
                return await self._get_sales(params)
            else:
                return ERPResult(False, "odoo", data_type.value, None, f"نوع البيانات {data_type} غير مدعوم حالياً")
        except Exception as e:
            log.error("Odoo fetch error", data_type=data_type, error=str(e))
            return ERPResult(False, "odoo", data_type.value, None, str(e))

    async def _get_budget(self, params: dict) -> ERPResult:
        domain = []
        if "year" in params:
            domain.append(["date_from", ">=", f"{params['year']}-01-01"])
            domain.append(["date_to", "<=", f"{params['year']}-12-31"])
        if "quarter" in params:
            q = int(params["quarter"])
            months = {1:(1,3), 2:(4,6), 3:(7,9), 4:(10,12)}
            sm, em = months[q]
            year = params.get("year", datetime.now().year)
            domain += [
                ["date_from", ">=", f"{year}-{sm:02d}-01"],
                ["date_to", "<=", f"{year}-{em:02d}-30"],
            ]
        records = await self._call(
            "crossovered.budget", "search_read",
            [domain],
            {"fields": ["name","date_from","date_to","planned_amount","practical_amount","percentage"], "limit": 50},
        )
        summary = {
            "الميزانيات": records,
            "إجمالي المخطط": sum(r.get("planned_amount", 0) for r in (records or [])),
            "إجمالي الفعلي": sum(r.get("practical_amount", 0) for r in (records or [])),
            "عدد الميزانيات": len(records or []),
        }
        return ERPResult(True, "odoo", "budget", summary)

    async def _get_invoices(self, params: dict) -> ERPResult:
        domain = [["move_type", "in", ["out_invoice", "in_invoice"]]]
        if params.get("state"):
            domain.append(["state", "=", params["state"]])
        if params.get("date_from"):
            domain.append(["invoice_date", ">=", params["date_from"]])
        if params.get("date_to"):
            domain.append(["invoice_date", "<=", params["date_to"]])
        records = await self._call(
            "account.move", "search_read",
            [domain],
            {"fields": ["name","partner_id","amount_total","state","invoice_date","currency_id"], "limit": 100},
        )
        return ERPResult(True, "odoo", "invoices", {
            "الفواتير": records,
            "الإجمالي": sum(r.get("amount_total", 0) for r in (records or [])),
            "العدد": len(records or []),
        })

    async def _get_purchase_orders(self, params: dict) -> ERPResult:
        domain = []
        if params.get("state"):
            domain.append(["state", "=", params["state"]])
        records = await self._call(
            "purchase.order", "search_read",
            [domain],
            {"fields": ["name","partner_id","amount_total","state","date_order","currency_id"], "limit": 100},
        )
        return ERPResult(True, "odoo", "purchase_orders", records)

    async def _get_employees(self, params: dict) -> ERPResult:
        domain = [["active", "=", True]]
        if params.get("department"):
            domain.append(["department_id.name", "ilike", params["department"]])
        records = await self._call(
            "hr.employee", "search_read",
            [domain],
            {"fields": ["name","job_title","department_id","work_email","work_phone"], "limit": 200},
        )
        return ERPResult(True, "odoo", "employees", {
            "الموظفون": records,
            "العدد الإجمالي": len(records or []),
        })

    async def _get_leave_balance(self, params: dict) -> ERPResult:
        employee_id = params.get("employee_id")
        domain = [["active", "=", True]]
        if employee_id:
            domain.append(["employee_id", "=", employee_id])
        records = await self._call(
            "hr.leave.allocation", "search_read",
            [domain],
            {"fields": ["employee_id","holiday_status_id","number_of_days","number_of_days_display","state"], "limit": 50},
        )
        return ERPResult(True, "odoo", "leave_balance", records)

    async def _get_leave_requests(self, params: dict) -> ERPResult:
        domain = []
        if params.get("employee_id"):
            domain.append(["employee_id", "=", params["employee_id"]])
        if params.get("state"):
            domain.append(["state", "=", params["state"]])
        records = await self._call(
            "hr.leave", "search_read",
            [domain],
            {"fields": ["employee_id","holiday_status_id","date_from","date_to","number_of_days","state"], "limit": 50},
        )
        return ERPResult(True, "odoo", "leave_requests", records)

    async def _get_payroll(self, params: dict) -> ERPResult:
        domain = []
        if params.get("month"):
            domain.append(["date_from", ">=", params["month"] + "-01"])
        records = await self._call(
            "hr.payslip", "search_read",
            [domain],
            {"fields": ["employee_id","date_from","date_to","net_wage","state"], "limit": 100},
        )
        return ERPResult(True, "odoo", "payroll", {
            "كشوف الراتب": records,
            "إجمالي الرواتب الصافية": sum(r.get("net_wage", 0) for r in (records or [])),
        })

    async def _get_sales(self, params: dict) -> ERPResult:
        domain = [["state", "in", ["sale", "done"]]]
        if params.get("date_from"):
            domain.append(["date_order", ">=", params["date_from"]])
        if params.get("date_to"):
            domain.append(["date_order", "<=", params["date_to"]])
        records = await self._call(
            "sale.order", "search_read",
            [domain],
            {"fields": ["name","partner_id","amount_total","state","date_order"], "limit": 100},
        )
        return ERPResult(True, "odoo", "sales", {
            "أوامر البيع": records,
            "إجمالي المبيعات": sum(r.get("amount_total", 0) for r in (records or [])),
        })

    async def execute_action(self, action: str, params: dict) -> ERPResult:
        """تنفيذ إجراء — طلب إجازة، اعتماد PO، إلخ."""
        try:
            if action == "submit_leave":
                result = await self._call(
                    "hr.leave", "create",
                    [{
                        "employee_id": params["employee_id"],
                        "holiday_status_id": params.get("leave_type_id", 1),
                        "date_from": params["date_from"],
                        "date_to": params["date_to"],
                        "name": params.get("reason", "طلب إجازة"),
                    }],
                )
                return ERPResult(True, "odoo", "submit_leave", {"leave_id": result})

            elif action == "approve_leave":
                await self._call(
                    "hr.leave", "action_validate",
                    [[params["leave_id"]]],
                )
                return ERPResult(True, "odoo", "approve_leave", {"status": "approved"})

            else:
                return ERPResult(False, "odoo", action, None, f"الإجراء '{action}' غير مدعوم")
        except Exception as e:
            return ERPResult(False, "odoo", action, None, str(e))

    async def health(self) -> bool:
        try:
            await self._authenticate()
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════
#  Rawa HR Connector (رواء — نظام موارد بشرية سعودي)
# ═══════════════════════════════════════════════════════════

class RawaConnector(BaseERPConnector):
    """
    يتصل بنظام رواء (Rawa) لإدارة الموارد البشرية.
    يستخدم REST API.

    الإعدادات:
        base_url  = "https://api.rawa.com.sa/v1"
        api_key   = "your_api_key"
        auth_type = "api_key"
    """

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-App-ID": self.config.extra.get("app_id", "natiqa"),
        }

    async def fetch(self, data_type: ERPDataType, params: dict | None = None) -> ERPResult:
        params = params or {}
        try:
            if data_type == ERPDataType.EMPLOYEES:
                return await self._get_employees(params)
            elif data_type == ERPDataType.LEAVE_BALANCE:
                return await self._get_leave_balance(params)
            elif data_type == ERPDataType.LEAVE_REQUESTS:
                return await self._get_leave_requests(params)
            elif data_type == ERPDataType.PAYROLL:
                return await self._get_payroll(params)
            else:
                return ERPResult(False, "rawa", data_type.value, None, "غير مدعوم في رواء")
        except Exception as e:
            log.error("Rawa fetch error", data_type=data_type, error=str(e))
            return ERPResult(False, "rawa", data_type.value, None, str(e))

    async def _get_employees(self, params: dict) -> ERPResult:
        async with await self._client() as client:
            resp = await client.get(
                "/employees",
                headers=self._headers(),
                params={"department": params.get("department"), "page_size": 100},
            )
            resp.raise_for_status()
            data = resp.json()
        return ERPResult(True, "rawa", "employees", data)

    async def _get_leave_balance(self, params: dict) -> ERPResult:
        employee_id = params.get("employee_id", "")
        async with await self._client() as client:
            resp = await client.get(
                f"/employees/{employee_id}/leave-balance",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        return ERPResult(True, "rawa", "leave_balance", data)

    async def _get_leave_requests(self, params: dict) -> ERPResult:
        async with await self._client() as client:
            resp = await client.get(
                "/leave-requests",
                headers=self._headers(),
                params={
                    "employee_id": params.get("employee_id"),
                    "status": params.get("status"),
                    "date_from": params.get("date_from"),
                    "date_to": params.get("date_to"),
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return ERPResult(True, "rawa", "leave_requests", data)

    async def _get_payroll(self, params: dict) -> ERPResult:
        async with await self._client() as client:
            resp = await client.get(
                "/payroll",
                headers=self._headers(),
                params={"month": params.get("month"), "year": params.get("year")},
            )
            resp.raise_for_status()
            data = resp.json()
        return ERPResult(True, "rawa", "payroll", data)

    async def execute_action(self, action: str, params: dict) -> ERPResult:
        try:
            if action == "submit_leave":
                async with await self._client() as client:
                    resp = await client.post(
                        "/leave-requests",
                        headers=self._headers(),
                        json={
                            "employee_id": params["employee_id"],
                            "leave_type":  params.get("leave_type", "annual"),
                            "date_from":   params["date_from"],
                            "date_to":     params["date_to"],
                            "reason":      params.get("reason", ""),
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                return ERPResult(True, "rawa", "submit_leave", data)
            else:
                return ERPResult(False, "rawa", action, None, f"الإجراء '{action}' غير مدعوم")
        except Exception as e:
            return ERPResult(False, "rawa", action, None, str(e))

    async def health(self) -> bool:
        try:
            async with await self._client() as client:
                resp = await client.get("/health", headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════
#  SAP S/4HANA Connector (OData v4)
# ═══════════════════════════════════════════════════════════

class SAPConnector(BaseERPConnector):
    """
    SAP S/4HANA عبر OData v4.

    الإعدادات:
        base_url    = "https://sap.company.com/sap/opu/odata4/sap"
        username    = "sap_user"
        password    = "sap_pass"
        auth_type   = "basic"
    """

    def _headers(self) -> dict:
        import base64
        creds = base64.b64encode(
            f"{self.config.username}:{self.config.password}".encode()
        ).decode()
        return {
            "Authorization": f"Basic {creds}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def fetch(self, data_type: ERPDataType, params: dict | None = None) -> ERPResult:
        params = params or {}
        try:
            if data_type == ERPDataType.BUDGET:
                return await self._get_budget(params)
            elif data_type == ERPDataType.INVOICES:
                return await self._get_invoices(params)
            elif data_type == ERPDataType.COST_CENTERS:
                return await self._get_cost_centers(params)
            else:
                return ERPResult(False, "sap", data_type.value, None, "نوع البيانات غير مدعوم في SAP حالياً")
        except Exception as e:
            log.error("SAP fetch error", data_type=data_type, error=str(e))
            return ERPResult(False, "sap", data_type.value, None, str(e))

    async def _get_budget(self, params: dict) -> ERPResult:
        """SAP Budget Controlling via OData."""
        endpoint = "/API_COSTCENTER_0001/CostCenterCollection"
        qparams: dict = {"$format": "json", "$top": "100"}
        if params.get("fiscal_year"):
            qparams["$filter"] = f"FiscalYear eq '{params['fiscal_year']}'"
        async with await self._client() as client:
            resp = await client.get(endpoint, headers=self._headers(), params=qparams)
            resp.raise_for_status()
            data = resp.json()
        return ERPResult(True, "sap", "budget", data.get("value", data))

    async def _get_invoices(self, params: dict) -> ERPResult:
        endpoint = "/API_SUPPLIER_INVOICE_PROCESS_SRV/A_SupplierInvoice"
        qparams: dict = {"$format": "json", "$top": "100"}
        async with await self._client() as client:
            resp = await client.get(endpoint, headers=self._headers(), params=qparams)
            resp.raise_for_status()
            data = resp.json()
        return ERPResult(True, "sap", "invoices", data.get("value", data))

    async def _get_cost_centers(self, params: dict) -> ERPResult:
        endpoint = "/API_COSTCENTER_0001/CostCenterCollection"
        async with await self._client() as client:
            resp = await client.get(
                endpoint, headers=self._headers(),
                params={"$format": "json", "$top": "200"}
            )
            resp.raise_for_status()
            data = resp.json()
        return ERPResult(True, "sap", "cost_centers", data.get("value", data))

    async def execute_action(self, action: str, params: dict) -> ERPResult:
        return ERPResult(False, "sap", action, None, "تنفيذ الإجراءات في SAP يتطلب Workflow Approval — قيد التطوير")

    async def health(self) -> bool:
        try:
            async with await self._client() as client:
                resp = await client.get("/", headers=self._headers())
                return resp.status_code < 500
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════
#  Generic REST Connector (أي نظام يدعم REST)
# ═══════════════════════════════════════════════════════════

class GenericRESTConnector(BaseERPConnector):
    """
    لأي نظام يدعم REST API — Oracle، Dynamics، إلخ.

    الإعدادات:
        base_url  = "https://api.system.com"
        api_key   = "key"
        extra     = {
            "endpoints": {
                "budget": "/v1/finance/budget",
                "employees": "/v1/hr/employees",
                ...
            }
        }
    """

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key:
            h["Authorization"] = f"Bearer {self.config.api_key}"
        return h

    async def fetch(self, data_type: ERPDataType, params: dict | None = None) -> ERPResult:
        endpoints = self.config.extra.get("endpoints", {})
        endpoint  = endpoints.get(data_type.value)
        if not endpoint:
            return ERPResult(False, self.config.system.value, data_type.value, None,
                             f"لم يُحدَّد endpoint لـ {data_type.value} في إعدادات النظام")
        try:
            async with await self._client() as client:
                resp = await client.get(endpoint, headers=self._headers(), params=params or {})
                resp.raise_for_status()
                data = resp.json()
            return ERPResult(True, self.config.system.value, data_type.value, data)
        except Exception as e:
            log.error("Generic REST fetch error", system=self.config.system, error=str(e))
            return ERPResult(False, self.config.system.value, data_type.value, None, str(e))

    async def execute_action(self, action: str, params: dict) -> ERPResult:
        endpoints = self.config.extra.get("action_endpoints", {})
        endpoint  = endpoints.get(action)
        if not endpoint:
            return ERPResult(False, self.config.system.value, action, None, f"لا يوجد endpoint للإجراء '{action}'")
        try:
            async with await self._client() as client:
                resp = await client.post(endpoint, headers=self._headers(), json=params)
                resp.raise_for_status()
                data = resp.json()
            return ERPResult(True, self.config.system.value, action, data)
        except Exception as e:
            return ERPResult(False, self.config.system.value, action, None, str(e))

    async def health(self) -> bool:
        try:
            hep = self.config.extra.get("health_endpoint", "/health")
            async with await self._client() as client:
                resp = await client.get(hep, headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════
#  Connector Factory
# ═══════════════════════════════════════════════════════════

def create_connector(config: ERPConfig) -> BaseERPConnector:
    """إنشاء الـ Connector المناسب حسب النظام."""
    if config.system == ERPSystem.ODOO:
        return OdooConnector(config)
    elif config.system == ERPSystem.RAWA:
        return RawaConnector(config)
    elif config.system == ERPSystem.SAP:
        return SAPConnector(config)
    else:
        return GenericRESTConnector(config)


# ═══════════════════════════════════════════════════════════
#  ERP Registry — إدارة الاتصالات المسجّلة
# ═══════════════════════════════════════════════════════════

class ERPRegistry:
    """
    سجل مركزي لجميع الأنظمة المتصلة.
    يُنشأ instance واحد للتطبيق.
    """

    def __init__(self):
        self._connectors: dict[str, BaseERPConnector] = {}

    def register(self, name: str, config: ERPConfig) -> None:
        """تسجيل نظام جديد."""
        self._connectors[name] = create_connector(config)
        log.info("ERP system registered", name=name, system=config.system)

    def get(self, name: str) -> BaseERPConnector | None:
        return self._connectors.get(name)

    def list_systems(self) -> list[dict]:
        return [
            {"name": k, "system": v.config.system.value, "url": v.config.base_url}
            for k, v in self._connectors.items()
        ]

    async def health_all(self) -> dict[str, bool]:
        results = {}
        for name, connector in self._connectors.items():
            try:
                results[name] = await connector.health()
            except Exception:
                results[name] = False
        return results

    async def fetch_from(
        self,
        system_name: str,
        data_type: ERPDataType,
        params: dict | None = None,
    ) -> ERPResult:
        """جلب بيانات من نظام محدد."""
        connector = self.get(system_name)
        if not connector:
            return ERPResult(False, system_name, data_type.value, None,
                             f"النظام '{system_name}' غير مسجّل")
        return await connector.fetch(data_type, params)

    async def execute_in(
        self,
        system_name: str,
        action: str,
        params: dict,
    ) -> ERPResult:
        """تنفيذ إجراء في نظام محدد."""
        connector = self.get(system_name)
        if not connector:
            return ERPResult(False, system_name, action, None,
                             f"النظام '{system_name}' غير مسجّل")
        return await connector.execute_action(action, params)


# Singleton
_registry: ERPRegistry | None = None


def get_erp_registry() -> ERPRegistry:
    global _registry
    if _registry is None:
        _registry = ERPRegistry()
    return _registry
