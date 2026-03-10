"""
╔══════════════════════════════════════════════════════════════════════════╗
║   NATIQA — Workflow Engine  (Redis Pub/Sub + Celery Task Queue)         ║
║                                                                          ║
║  البنية:                                                                 ║
║    WorkflowEvent  → حدث منشور على Redis Channel                         ║
║    WorkflowTask   → مهمة في Celery Queue (معالجة غير متزامنة)           ║
║    EventBus       → ينشر/يستمع للأحداث عبر Redis Pub/Sub                ║
║    WorkflowEngine → يُنسّق تدفق العمل بين الوكلاء                      ║
║                                                                          ║
║  مثال: طلب شراء من المبيعات                                             ║
║    ┌─────────────┐  publish   ┌──────────────────┐                      ║
║    │ Sales Agent │ ─────────► │ Redis: workflow   │                     ║
║    └─────────────┘            │ Channel           │                     ║
║                               └────────┬─────────┘                     ║
║                                        │ subscribe                      ║
║                               ┌────────▼─────────┐                     ║
║                               │ Celery Worker     │                     ║
║                               │ (Finance Task)    │                     ║
║                               └────────┬─────────┘                     ║
║                                        │ run                            ║
║                               ┌────────▼─────────┐                     ║
║                               │ Finance Agent     │                     ║
║                               │ approve/reject    │                     ║
║                               └──────────────────┘                     ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable

import structlog

from app.core.config import settings

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
#  1. Workflow Event & Status
# ═══════════════════════════════════════════════════════════

class WorkflowStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    AWAITING   = "awaiting"     # ينتظر موافقة بشرية
    APPROVED   = "approved"
    REJECTED   = "rejected"
    COMPLETED  = "completed"
    FAILED     = "failed"
    EXPIRED    = "expired"


class WorkflowType(str, Enum):
    PURCHASE_APPROVAL   = "purchase_approval"     # Sales → Finance
    LEAVE_NOTIFICATION  = "leave_notification"    # HR → Manager
    BUDGET_ALERT        = "budget_alert"          # Finance → Admin
    CROSS_DEPT_REPORT   = "cross_dept_report"     # كل الوكلاء
    ESCALATION          = "escalation"            # تصعيد لـ super_admin


@dataclass
class WorkflowEvent:
    """
    حدث منشور على Redis Channel.
    يحمل كل المعلومات اللازمة للمعالجة بشكل مستقل.
    """
    event_id:       str = field(default_factory=lambda: f"WF-{uuid.uuid4().hex[:10].upper()}")
    workflow_type:  WorkflowType = WorkflowType.PURCHASE_APPROVAL
    status:         WorkflowStatus = WorkflowStatus.PENDING

    # المصدر والهدف
    source_agent:   str = ""     # sales_agent / hr_agent ...
    target_agent:   str = ""     # finance_agent ...
    initiator_id:   str = ""     # معرّف المستخدم
    initiator_role: str = ""

    # البيانات
    payload:        dict = field(default_factory=dict)
    result:         dict | None = None

    # Timing
    created_at:     float = field(default_factory=time.time)
    expires_at:     float = field(default_factory=lambda: time.time() + 172800)  # 48h
    processed_at:   float | None = None
    completed_at:   float | None = None

    # Audit
    audit_chain:    list[dict] = field(default_factory=list)

    def add_audit(self, event: str, actor: str, data: dict | None = None) -> None:
        """إضافة خطوة لسلسلة التدقيق."""
        self.audit_chain.append({
            "event":  event,
            "actor":  actor,
            "data":   data or {},
            "ts":     time.time(),
            "ts_iso": datetime.now(timezone.utc).isoformat(),
        })

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, data: str) -> "WorkflowEvent":
        d = json.loads(data)
        d["workflow_type"] = WorkflowType(d["workflow_type"])
        d["status"]        = WorkflowStatus(d["status"])
        return cls(**d)

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════
#  2. Redis Event Bus
# ═══════════════════════════════════════════════════════════

WORKFLOW_CHANNEL   = "natiqa:workflows"
WORKFLOW_STORE_KEY = "natiqa:workflow:{event_id}"
WORKFLOW_LIST_KEY  = "natiqa:workflow_list"


class EventBus:
    """
    Bus للأحداث عبر Redis Pub/Sub.
    يُنشئ/يستقبل WorkflowEvents بين الوكلاء.
    """

    def __init__(self):
        self._redis = None
        self._handlers: dict[WorkflowType, list[Callable]] = {}
        self._running = False

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def publish(self, event: WorkflowEvent) -> bool:
        """
        نشر حدث على Redis Channel + تخزينه لـ 48 ساعة.
        """
        try:
            r = await self._get_redis()

            event.add_audit("published", event.source_agent, {
                "channel": WORKFLOW_CHANNEL,
                "type":    event.workflow_type.value,
            })

            # تخزين الحدث في Redis Hash (للاسترجاع لاحقاً)
            store_key = WORKFLOW_STORE_KEY.format(event_id=event.event_id)
            await r.setex(store_key, 172800, event.to_json())  # TTL 48h

            # إضافة لقائمة الـ Active Workflows
            await r.lpush(WORKFLOW_LIST_KEY, event.event_id)
            await r.ltrim(WORKFLOW_LIST_KEY, 0, 999)  # احتفظ بآخر 1000

            # نشر على Channel
            await r.publish(WORKFLOW_CHANNEL, event.to_json())

            log.info(
                "workflow_published",
                event_id=event.event_id,
                type=event.workflow_type.value,
                source=event.source_agent,
                target=event.target_agent,
            )
            return True

        except Exception as e:
            log.error("workflow_publish_failed", error=str(e), event_id=event.event_id)
            return False

    async def get_event(self, event_id: str) -> WorkflowEvent | None:
        """استرجاع حدث محفوظ."""
        try:
            r = await self._get_redis()
            store_key = WORKFLOW_STORE_KEY.format(event_id=event_id)
            data = await r.get(store_key)
            return WorkflowEvent.from_json(data) if data else None
        except Exception:
            return None

    async def update_event(self, event: WorkflowEvent) -> bool:
        """تحديث حالة حدث محفوظ."""
        try:
            r = await self._get_redis()
            store_key = WORKFLOW_STORE_KEY.format(event_id=event.event_id)
            await r.setex(store_key, 172800, event.to_json())
            return True
        except Exception:
            return False

    async def list_pending(self, workflow_type: WorkflowType | None = None) -> list[WorkflowEvent]:
        """قائمة الأحداث المعلّقة."""
        try:
            r = await self._get_redis()
            event_ids = await r.lrange(WORKFLOW_LIST_KEY, 0, 99)
            events: list[WorkflowEvent] = []

            for eid in event_ids:
                ev = await self.get_event(eid)
                if ev and ev.status == WorkflowStatus.PENDING:
                    if workflow_type is None or ev.workflow_type == workflow_type:
                        events.append(ev)

            return events
        except Exception as e:
            log.error("list_pending_failed", error=str(e))
            return []

    def register_handler(
        self,
        workflow_type: WorkflowType,
        handler: Callable[[WorkflowEvent], Awaitable[None]],
    ) -> None:
        """تسجيل معالج لنوع حدث معيّن."""
        if workflow_type not in self._handlers:
            self._handlers[workflow_type] = []
        self._handlers[workflow_type].append(handler)

    async def start_listener(self) -> None:
        """
        بدء الاستماع على Redis Channel.
        يُشغَّل في background task عند بدء التطبيق.
        """
        self._running = True
        log.info("EventBus: بدء الاستماع", channel=WORKFLOW_CHANNEL)

        try:
            r = await self._get_redis()
            pubsub = r.pubsub()
            await pubsub.subscribe(WORKFLOW_CHANNEL)

            async for message in pubsub.listen():
                if not self._running:
                    break
                if message["type"] != "message":
                    continue

                try:
                    event = WorkflowEvent.from_json(message["data"])
                    await self._dispatch(event)
                except Exception as e:
                    log.error("EventBus: خطأ في المعالجة", error=str(e))

        except Exception as e:
            log.error("EventBus: انقطع الاتصال", error=str(e))

    async def _dispatch(self, event: WorkflowEvent) -> None:
        """توزيع الحدث على المعالجين المناسبين."""
        handlers = self._handlers.get(event.workflow_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                log.error("EventBus: فشل المعالج", handler=handler.__name__, error=str(e))

    def stop(self) -> None:
        self._running = False


# ═══════════════════════════════════════════════════════════
#  3. Celery Configuration (Task Queue)
# ═══════════════════════════════════════════════════════════

def create_celery_app():
    """
    إنشاء Celery App باستخدام Redis كـ Broker و Backend.
    يُستخدم لمعالجة Workflows غير المتزامنة.
    """
    try:
        from celery import Celery

        celery_app = Celery(
            "natiqa_workers",
            broker=settings.REDIS_URL,
            backend=settings.REDIS_URL,
        )

        celery_app.conf.update(
            # Serialization
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],

            # Timezone
            timezone="Asia/Riyadh",
            enable_utc=True,

            # Task behavior
            task_acks_late=True,        # الإقرار بعد الإتمام (ضمان التسليم)
            task_reject_on_worker_lost=True,
            task_track_started=True,

            # Queues
            task_routes={
                "natiqa.workflows.purchase_approval": {"queue": "finance_queue"},
                "natiqa.workflows.leave_notification": {"queue": "hr_queue"},
                "natiqa.workflows.budget_alert":       {"queue": "admin_queue"},
                "natiqa.workflows.*":                  {"queue": "default"},
            },

            # Retry
            task_max_retries=3,
            task_default_retry_delay=30,

            # Result expiry
            result_expires=86400,  # 24 ساعة
        )

        # Scheduled tasks (Celery Beat)
        celery_app.conf.beat_schedule = {
            "expire-old-workflows": {
                "task":     "natiqa.workflows.expire_old",
                "schedule": 3600,  # كل ساعة
            },
            "audit-compliance-check": {
                "task":     "natiqa.audit.compliance_check",
                "schedule": 86400,  # يومياً
            },
        }

        return celery_app

    except ImportError:
        log.warning("Celery غير مثبّت — سيعمل بالوضع المتزامن")
        return None


# ═══════════════════════════════════════════════════════════
#  4. Celery Tasks
# ═══════════════════════════════════════════════════════════

# يُستورد فقط إذا كان Celery متاحاً
try:
    from celery import Celery, Task
    _celery_available = True
except ImportError:
    _celery_available = False


def register_celery_tasks(celery_app) -> None:
    """
    تسجيل جميع Workflow Tasks في Celery.
    يُستدعى بعد إنشاء الـ Celery app.
    """
    if not celery_app:
        return

    @celery_app.task(
        name="natiqa.workflows.purchase_approval",
        bind=True,
        max_retries=3,
    )
    def process_purchase_approval(self, event_data: dict):
        """
        معالجة طلب الشراء:
        1. تحميل الحدث
        2. تشغيل Finance Agent للمراجعة
        3. إرسال القرار للـ Sales Agent
        4. تسجيل النتيجة في Audit
        """
        import asyncio

        async def _run():
            event_bus = get_event_bus()
            event_id  = event_data.get("event_id")

            # استرجاع الحدث
            event = await event_bus.get_event(event_id)
            if not event or event.is_expired:
                log.warning("purchase_approval: حدث منتهي الصلاحية", event_id=event_id)
                return

            event.status = WorkflowStatus.PROCESSING
            event.processed_at = time.time()
            event.add_audit("celery_started", "celery_worker")
            await event_bus.update_event(event)

            # تشغيل Finance Agent
            try:
                from app.agents.agents import FinanceAgent
                finance_agent = FinanceAgent(user_role="admin")
                payload = event.payload

                query = (
                    f"طلب شراء وارد من قسم المبيعات:\n"
                    f"العنصر: {payload.get('item')}\n"
                    f"المبلغ: {payload.get('amount'):,} ريال\n"
                    f"المبرر: {payload.get('justification')}\n"
                    f"تحقق من توفر الميزانية وقرر الاعتماد أو الرفض."
                )

                result = await finance_agent.run(query)

                event.result = {
                    "finance_response": result.response,
                    "tool_calls":       len(result.tool_calls),
                    "tokens":           result.tokens_used,
                }
                event.status     = WorkflowStatus.COMPLETED
                event.completed_at = time.time()
                event.add_audit("finance_reviewed", "finance_agent", {
                    "decision": "reviewed",
                    "response_snippet": result.response[:200],
                })

            except Exception as e:
                event.status = WorkflowStatus.FAILED
                event.add_audit("processing_error", "celery_worker", {"error": str(e)})
                log.error("purchase_approval: فشل التنفيذ", error=str(e))

            await event_bus.update_event(event)

            # Audit Trail في DB
            from app.agents.audit_trail import get_audit_trail
            audit = get_audit_trail()
            await audit.log_workflow_event(event)

        # تشغيل الـ async في Celery
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    @celery_app.task(
        name="natiqa.workflows.leave_notification",
        bind=True,
    )
    def process_leave_notification(self, event_data: dict):
        """
        إشعار مدير القسم بطلب إجازة يتطلب موافقته.
        """
        import asyncio

        async def _run():
            event_bus = get_event_bus()
            event     = await event_bus.get_event(event_data.get("event_id"))
            if not event:
                return

            event.status = WorkflowStatus.AWAITING
            event.add_audit("notification_sent", "hr_agent", {
                "manager": event.payload.get("manager_id"),
            })
            await event_bus.update_event(event)

            from app.agents.audit_trail import get_audit_trail
            await get_audit_trail().log_workflow_event(event)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    @celery_app.task(name="natiqa.workflows.expire_old")
    def expire_old_workflows():
        """تنظيف الأحداث المنتهية الصلاحية (يومي)."""
        log.info("expire_old_workflows: بدء التنظيف")

    @celery_app.task(name="natiqa.audit.compliance_check")
    def daily_compliance_check():
        """فحص امتثال يومي — يُنتج تقريراً للـ Audit."""
        log.info("daily_compliance_check: بدء الفحص اليومي")


# ═══════════════════════════════════════════════════════════
#  5. Workflow Engine (المنسّق الرئيسي)
# ═══════════════════════════════════════════════════════════

class WorkflowEngine:
    """
    المنسّق الرئيسي للـ Cross-Agent Workflows.
    يستقبل نتائج الوكلاء ويُنشئ Events المناسبة.
    """

    def __init__(self):
        self._bus    = get_event_bus()
        self._celery = create_celery_app()
        if self._celery:
            register_celery_tasks(self._celery)

    async def trigger_purchase_approval(
        self,
        item:           str,
        amount:         float,
        justification:  str,
        requestor_id:   str,
        requestor_role: str,
    ) -> WorkflowEvent:
        """
        بدء Workflow اعتماد طلب الشراء.
        يُستدعى عندما يطلب Sales Agent موافقة مالية.
        """
        event = WorkflowEvent(
            workflow_type=WorkflowType.PURCHASE_APPROVAL,
            source_agent="sales_agent",
            target_agent="finance_agent",
            initiator_id=requestor_id,
            initiator_role=requestor_role,
            payload={
                "item":          item,
                "amount":        amount,
                "justification": justification,
                "requestor":     requestor_id,
                "high_value":    amount > 500_000,
            },
        )

        event.add_audit("workflow_created", requestor_id, {
            "amount":   amount,
            "item":     item,
            "auto_approve": amount <= 50_000,  # أقل من 50,000 → موافقة تلقائية
        })

        # موافقة تلقائية للمبالغ الصغيرة
        if amount <= 50_000:
            event.status = WorkflowStatus.APPROVED
            event.result = {
                "decision": "auto_approved",
                "reason":   "المبلغ أقل من حد الموافقة التلقائية (50,000 ريال)",
            }
            event.completed_at = time.time()
            event.add_audit("auto_approved", "system", {"threshold": 50_000})
            await self._bus.publish(event)
            return event

        # نشر على Redis
        await self._bus.publish(event)

        # إرسال لـ Celery Queue
        if self._celery:
            self._celery.send_task(
                "natiqa.workflows.purchase_approval",
                args=[event.to_dict()],
                queue="finance_queue",
                countdown=2,  # تأخير 2 ثانية للسماح بالـ publish
            )
        else:
            # Fallback متزامن إذا لم يكن Celery متاحاً
            await self._process_purchase_approval_sync(event)

        return event

    async def trigger_leave_notification(
        self,
        employee_id: str,
        request_id:  str,
        manager_id:  str,
        leave_type:  str,
        days:        int,
    ) -> WorkflowEvent:
        """إشعار المدير بطلب إجازة يحتاج موافقة."""
        event = WorkflowEvent(
            workflow_type=WorkflowType.LEAVE_NOTIFICATION,
            source_agent="hr_agent",
            target_agent="manager",
            initiator_id=employee_id,
            initiator_role="employee",
            payload={
                "employee_id": employee_id,
                "request_id":  request_id,
                "manager_id":  manager_id,
                "leave_type":  leave_type,
                "days":        days,
            },
        )

        event.add_audit("leave_notification_created", "hr_agent")
        await self._bus.publish(event)

        if self._celery:
            self._celery.send_task(
                "natiqa.workflows.leave_notification",
                args=[event.to_dict()],
                queue="hr_queue",
            )

        return event

    async def get_workflow_status(self, event_id: str) -> dict:
        """استعلام عن حالة workflow."""
        event = await self._bus.get_event(event_id)
        if not event:
            return {"error": f"الحدث '{event_id}' غير موجود أو انتهت صلاحيته"}

        return {
            "event_id":      event.event_id,
            "type":          event.workflow_type.value,
            "status":        event.status.value,
            "source":        event.source_agent,
            "target":        event.target_agent,
            "age_hours":     round(event.age_seconds / 3600, 1),
            "result":        event.result,
            "audit_steps":   len(event.audit_chain),
            "last_action":   event.audit_chain[-1] if event.audit_chain else None,
        }

    async def _process_purchase_approval_sync(self, event: WorkflowEvent) -> None:
        """معالجة متزامنة عندما لا يكون Celery متاحاً."""
        try:
            from app.agents.agents import FinanceAgent
            finance_agent = FinanceAgent(user_role="admin")
            payload = event.payload

            result = await finance_agent.run(
                f"راجع طلب الشراء: {payload.get('item')} "
                f"بمبلغ {payload.get('amount'):,} ريال"
            )

            event.result    = {"finance_response": result.response}
            event.status    = WorkflowStatus.COMPLETED
            event.completed_at = time.time()
            event.add_audit("sync_processed", "finance_agent")
            await self._bus.update_event(event)

        except Exception as e:
            event.status = WorkflowStatus.FAILED
            event.add_audit("sync_error", "system", {"error": str(e)})
            await self._bus.update_event(event)


# ═══════════════════════════════════════════════════════════
#  6. Singletons
# ═══════════════════════════════════════════════════════════

_event_bus:       EventBus | None = None
_workflow_engine: WorkflowEngine | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def get_workflow_engine() -> WorkflowEngine:
    global _workflow_engine
    if _workflow_engine is None:
        _workflow_engine = WorkflowEngine()
    return _workflow_engine
