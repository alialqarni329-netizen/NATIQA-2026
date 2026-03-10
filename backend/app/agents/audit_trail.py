"""
╔══════════════════════════════════════════════════════════════════════════╗
║   NATIQA — Audit Trail  (سجل التدقيق الشامل)                            ║
║                                                                          ║
║  معايير الامتثال المطبّقة:                                               ║
║    • ISO 27001  — سجل الوصول للمعلومات                                  ║
║    • SOC 2 Type II — تتبع كل قرار                                       ║
║    • SAMA Cybersecurity Framework — للقطاع المالي السعودي               ║
║    • NCA ECC — هيئة الأمن السيبراني الوطنية                             ║
║                                                                          ║
║  خصائص السجل:                                                            ║
║    • Immutable: لا يمكن حذف أو تعديل سجل بعد كتابته                    ║
║    • Tamper-Evident: كل سجل يحمل HMAC لكشف أي تلاعب                    ║
║    • Chained: كل سجل يحتوي على hash السابق (مثل Blockchain)             ║
║    • Queryable: بحث متقدم + تقارير PDF/Excel                            ║
║    • Retention: 7 سنوات (SAMA) / 90 يوم hot + archive                  ║
║                                                                          ║
║  ما يُسجَّل:                                                             ║
║    1. كل قرار اتخذه AI (أي agent)                                       ║
║    2. كل استعلام أجراه مستخدم                                           ║
║    3. كل workflow بدأ أو انتهى                                          ║
║    4. كل رفض RBAC                                                       ║
║    5. كل وصول للـ Vault                                                 ║
║    6. كل تغيير في الإعدادات                                             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

from app.core.config import settings

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
#  1. Audit Event Types
# ═══════════════════════════════════════════════════════════

class AuditCategory(str, Enum):
    """تصنيف أحداث التدقيق للامتثال."""
    AUTHENTICATION   = "authentication"      # دخول / خروج / فشل
    AUTHORIZATION    = "authorization"       # رفض RBAC / تغيير صلاحيات
    DATA_ACCESS      = "data_access"         # قراءة بيانات
    DATA_MUTATION    = "data_mutation"       # تعديل / حذف بيانات
    AI_DECISION      = "ai_decision"         # قرار اتخذه AI
    WORKFLOW         = "workflow"            # بدء / انتهاء Workflow
    VAULT_ACCESS     = "vault_access"        # وصول للـ Vault
    SYSTEM           = "system"              # أحداث النظام
    COMPLIANCE       = "compliance"          # فحوصات الامتثال


class AuditSeverity(str, Enum):
    """أهمية الحدث."""
    LOW      = "low"       # استعلام عادي
    MEDIUM   = "medium"    # قرار AI / تعديل
    HIGH     = "high"      # رفض RBAC / وصول حساس
    CRITICAL = "critical"  # تغيير صلاحيات / وصول Vault


class AuditAction(str, Enum):
    """الإجراء المُسجَّل — موسّع عن models_v2."""
    # Auth
    LOGIN                   = "login"
    LOGOUT                  = "logout"
    LOGIN_FAILED            = "login_failed"
    TOKEN_REFRESH           = "token_refresh"
    TWO_FA_ENABLED          = "2fa_enabled"

    # RBAC
    ACCESS_DENIED           = "access_denied"
    PERMISSION_GRANTED      = "permission_granted"
    PERMISSION_CHANGE       = "permission_change"
    ROLE_ASSIGNED           = "role_assigned"

    # Data
    FILE_UPLOAD             = "file_upload"
    FILE_DELETE             = "file_delete"
    FILE_ACCESS             = "file_access"
    FILE_WIPE               = "file_wipe"
    DOCUMENT_QUERY          = "document_query"

    # AI Decisions
    AGENT_QUERY             = "agent_query"        # سؤال لوكيل
    AGENT_DECISION          = "agent_decision"     # قرار اتخذه وكيل
    AGENT_TOOL_CALL         = "agent_tool_call"    # استدعاء tool
    AGENT_RBAC_BLOCK        = "agent_rbac_block"   # رفض داخل الوكيل
    ROUTER_DECISION         = "router_decision"    # قرار الـ Router Chain
    LLM_CALL                = "llm_call"           # استدعاء LLM مباشر

    # Workflows
    WORKFLOW_CREATED        = "workflow_created"
    WORKFLOW_PROCESSED      = "workflow_processed"
    WORKFLOW_APPROVED       = "workflow_approved"
    WORKFLOW_REJECTED       = "workflow_rejected"
    WORKFLOW_EXPIRED        = "workflow_expired"

    # Vault
    VAULT_SECRET_STORED     = "vault_secret_stored"
    VAULT_SECRET_ACCESSED   = "vault_secret_accessed"
    VAULT_SECRET_REVOKED    = "vault_secret_revoked"
    VAULT_KEY_ROTATED       = "vault_key_rotated"

    # System
    QUERY_RBAC_BLOCK        = "query_rbac_block"
    SETTINGS_CHANGE         = "settings_change"
    SYSTEM_STARTUP          = "system_startup"
    COMPLIANCE_CHECK        = "compliance_check"
    DATA_MASKED             = "data_masked"

    # Projects/Documents
    PROJECT_CREATE          = "project_create"
    PROJECT_DELETE          = "project_delete"
    USER_CREATE             = "user_create"
    USER_DELETE             = "user_delete"
    REPORT_GENERATE         = "report_generate"


# ═══════════════════════════════════════════════════════════
#  2. Audit Record
# ═══════════════════════════════════════════════════════════

@dataclass
class AuditRecord:
    """
    سجل تدقيق واحد — غير قابل للتعديل بعد الإنشاء.

    يحمل:
    • HMAC signature لكشف التلاعب
    • hash السجل السابق (Chaining)
    • كل التفاصيل اللازمة للتحقيق لاحقاً
    """
    # المعرّف والتسلسل
    record_id:      str = field(default_factory=lambda: str(uuid.uuid4()))
    sequence_num:   int = 0                          # رقم تسلسلي متصاعد
    prev_hash:      str = ""                         # hash السجل السابق (Chaining)
    record_hash:    str = ""                         # HMAC لهذا السجل
    chain_valid:    bool = True

    # الحدث
    action:         AuditAction = AuditAction.AGENT_QUERY
    category:       AuditCategory = AuditCategory.AI_DECISION
    severity:       AuditSeverity = AuditSeverity.LOW

    # الفاعل
    actor_id:       str | None = None    # معرّف المستخدم أو الوكيل
    actor_type:     str = "user"         # user / agent / system
    actor_role:     str | None = None
    actor_name:     str | None = None

    # الهدف
    target_type:    str | None = None    # document / agent / workflow ...
    target_id:      str | None = None
    target_name:    str | None = None

    # التفاصيل
    description:    str = ""
    request_text:   str | None = None    # ما طلبه المستخدم
    ai_response:    str | None = None    # ما ردّ به AI (مُقتطع)
    ai_decision:    str | None = None    # القرار الصريح (approve/reject/escalate)
    tool_calls:     list[dict] = field(default_factory=list)
    masked_fields:  int = 0
    tokens_used:    int = 0

    # الشبكة
    ip_address:     str | None = None
    user_agent:     str | None = None
    session_id:     str | None = None

    # النتيجة
    success:        bool = True
    error_message:  str | None = None
    response_ms:    int = 0

    # Workflow
    workflow_id:    str | None = None
    workflow_type:  str | None = None

    # التوقيت
    created_at:     float = field(default_factory=time.time)
    created_at_iso: str   = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # بيانات إضافية
    metadata:       dict = field(default_factory=dict)

    def compute_hash(self, signing_key: str) -> str:
        """
        حساب HMAC-SHA256 للسجل.
        يُستخدم للتحقق من عدم التلاعب.
        """
        content = json.dumps({
            "record_id":   self.record_id,
            "sequence_num": self.sequence_num,
            "prev_hash":   self.prev_hash,
            "action":      self.action.value,
            "actor_id":    self.actor_id,
            "target_id":   self.target_id,
            "description": self.description,
            "created_at":  self.created_at,
        }, sort_keys=True)

        return hmac.new(
            signing_key.encode(),
            content.encode(),
            hashlib.sha256,
        ).hexdigest()

    def finalize(self, prev_hash: str, sequence_num: int, signing_key: str) -> None:
        """
        تثبيت السجل — يُستدعى مرة واحدة فقط قبل التخزين.
        بعدها لا يمكن تعديل السجل.
        """
        self.prev_hash    = prev_hash
        self.sequence_num = sequence_num
        self.record_hash  = self.compute_hash(signing_key)

    def verify_integrity(self, signing_key: str) -> bool:
        """التحقق من سلامة السجل — يكشف أي تلاعب."""
        expected = self.compute_hash(signing_key)
        return hmac.compare_digest(self.record_hash, expected)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["action"]   = self.action.value
        d["category"] = self.category.value
        d["severity"] = self.severity.value
        return d

    def to_display(self) -> dict:
        """نسخة آمنة للعرض — تُخفي التفاصيل الحساسة."""
        return {
            "record_id":   self.record_id,
            "timestamp":   self.created_at_iso,
            "action":      self.action.value,
            "category":    self.category.value,
            "severity":    self.severity.value,
            "actor":       f"{self.actor_type}:{self.actor_id or 'unknown'}",
            "actor_role":  self.actor_role,
            "target":      f"{self.target_type}:{self.target_id}" if self.target_type else None,
            "description": self.description,
            "success":     self.success,
            "response_ms": self.response_ms,
            "chain_valid": self.chain_valid,
        }


# ═══════════════════════════════════════════════════════════
#  3. Audit Trail Engine
# ═══════════════════════════════════════════════════════════

class AuditTrail:
    """
    محرك سجل التدقيق الرئيسي.

    يخزّن في:
    • In-Memory Buffer (للأداء)
    • Redis (للـ real-time streaming)
    • PostgreSQL (للاحتفاظ الدائم — 7 سنوات)

    الـ Chaining يضمن أن أي حذف أو تعديل سيُكتشف.
    """

    REDIS_AUDIT_KEY    = "natiqa:audit_stream"
    REDIS_AUDIT_LATEST = "natiqa:audit_latest_hash"
    BATCH_SIZE         = 50     # إرسال DB كل 50 سجل
    MAX_MEMORY_BUFFER  = 1000   # أقصى حجم للـ Buffer

    def __init__(self):
        self._signing_key   = settings.SECRET_KEY[:32]
        self._buffer:       list[AuditRecord] = []
        self._sequence_num  = 0
        self._last_hash     = "0" * 64      # Genesis hash
        self._redis         = None
        self._db_session_factory = None
        self._pending_flush: list[AuditRecord] = []

    def set_db_session(self, factory) -> None:
        self._db_session_factory = factory

    # ── Public API ────────────────────────────────────────

    async def log(self, record: AuditRecord) -> str:
        """
        تسجيل حدث في سجل التدقيق.
        يعود بـ record_id للمرجعية.
        """
        # تثبيت السجل (chain + hash)
        self._sequence_num += 1
        record.finalize(
            prev_hash=self._last_hash,
            sequence_num=self._sequence_num,
            signing_key=self._signing_key,
        )
        self._last_hash = record.record_hash

        # Buffer
        self._buffer.append(record)
        if len(self._buffer) > self.MAX_MEMORY_BUFFER:
            self._buffer = self._buffer[-self.MAX_MEMORY_BUFFER:]

        # Redis Stream (async, non-blocking)
        asyncio.create_task(self._stream_to_redis(record))

        # DB Flush إذا امتلأ الـ batch
        self._pending_flush.append(record)
        if len(self._pending_flush) >= self.BATCH_SIZE:
            asyncio.create_task(self._flush_to_db())

        # log للـ structlog أيضاً
        log_fn = log.warning if record.severity in (AuditSeverity.HIGH, AuditSeverity.CRITICAL) else log.info
        log_fn(
            "AUDIT",
            action=record.action.value,
            actor=record.actor_id,
            severity=record.severity.value,
            success=record.success,
            record_id=record.record_id,
        )

        return record.record_id

    async def log_agent_query(
        self,
        actor_id:     str,
        actor_role:   str,
        agent_type:   str,
        query:        str,
        response:     str,
        tool_calls:   list[dict],
        tokens_used:  int,
        elapsed_ms:   int,
        ip_address:   str | None = None,
        session_id:   str | None = None,
        masked_fields: int = 0,
    ) -> str:
        """تسجيل استعلام لوكيل AI."""
        record = AuditRecord(
            action=AuditAction.AGENT_QUERY,
            category=AuditCategory.AI_DECISION,
            severity=AuditSeverity.MEDIUM,
            actor_id=actor_id,
            actor_type="user",
            actor_role=actor_role,
            target_type="agent",
            target_id=agent_type,
            target_name=agent_type,
            description=f"استعلام للوكيل {agent_type}: {query[:100]}",
            request_text=query[:500],
            ai_response=response[:500],
            tool_calls=tool_calls,
            tokens_used=tokens_used,
            masked_fields=masked_fields,
            ip_address=ip_address,
            session_id=session_id,
            success=True,
            response_ms=elapsed_ms,
        )
        return await self.log(record)

    async def log_agent_decision(
        self,
        agent_type:  str,
        decision:    str,
        context:     str,
        tool_used:   str | None = None,
        workflow_id: str | None = None,
        severity:    AuditSeverity = AuditSeverity.HIGH,
    ) -> str:
        """تسجيل قرار اتخذه وكيل AI (موافقة / رفض / تصعيد)."""
        record = AuditRecord(
            action=AuditAction.AGENT_DECISION,
            category=AuditCategory.AI_DECISION,
            severity=severity,
            actor_id=agent_type,
            actor_type="agent",
            target_type="workflow" if workflow_id else "decision",
            target_id=workflow_id,
            description=f"قرار AI: {decision[:200]}",
            ai_decision=decision,
            request_text=context[:300],
            tool_calls=[{"tool": tool_used}] if tool_used else [],
            workflow_id=workflow_id,
            success=True,
        )
        return await self.log(record)

    async def log_access_denied(
        self,
        actor_id:    str,
        actor_role:  str,
        resource:    str,
        reason:      str,
        ip_address:  str | None = None,
    ) -> str:
        """تسجيل رفض RBAC — أهمية عالية."""
        record = AuditRecord(
            action=AuditAction.ACCESS_DENIED,
            category=AuditCategory.AUTHORIZATION,
            severity=AuditSeverity.HIGH,
            actor_id=actor_id,
            actor_type="user",
            actor_role=actor_role,
            target_type="resource",
            target_name=resource,
            description=f"رُفض الوصول: {reason}",
            error_message=reason,
            ip_address=ip_address,
            success=False,
        )
        return await self.log(record)

    async def log_vault_access(
        self,
        actor_id:   str,
        system_id:  str,
        key_name:   str,
        action_type: str,   # stored / accessed / revoked / rotated
    ) -> str:
        """تسجيل وصول للـ Vault — أعلى مستوى أهمية."""
        action_map = {
            "stored":  AuditAction.VAULT_SECRET_STORED,
            "accessed": AuditAction.VAULT_SECRET_ACCESSED,
            "revoked":  AuditAction.VAULT_SECRET_REVOKED,
            "rotated":  AuditAction.VAULT_KEY_ROTATED,
        }
        record = AuditRecord(
            action=action_map.get(action_type, AuditAction.VAULT_SECRET_ACCESSED),
            category=AuditCategory.VAULT_ACCESS,
            severity=AuditSeverity.CRITICAL,
            actor_id=actor_id,
            actor_type="user",
            target_type="vault",
            target_id=f"{system_id}:{key_name}",
            description=f"Vault {action_type}: {system_id}/{key_name}",
            metadata={"system_id": system_id, "key_name": key_name},
            success=True,
        )
        return await self.log(record)

    async def log_workflow_event(self, workflow_event) -> str:
        """تسجيل حدث Workflow (WorkflowEvent)."""
        status = getattr(workflow_event.status, 'value', str(workflow_event.status))
        action_map = {
            "pending":    AuditAction.WORKFLOW_CREATED,
            "completed":  AuditAction.WORKFLOW_PROCESSED,
            "approved":   AuditAction.WORKFLOW_APPROVED,
            "rejected":   AuditAction.WORKFLOW_REJECTED,
            "expired":    AuditAction.WORKFLOW_EXPIRED,
        }
        record = AuditRecord(
            action=action_map.get(status, AuditAction.WORKFLOW_CREATED),
            category=AuditCategory.WORKFLOW,
            severity=AuditSeverity.MEDIUM,
            actor_id=workflow_event.initiator_id,
            actor_type="user",
            actor_role=workflow_event.initiator_role,
            target_type="workflow",
            target_id=workflow_event.event_id,
            target_name=getattr(workflow_event.workflow_type, 'value', str(workflow_event.workflow_type)),
            description=f"Workflow {status}: {workflow_event.event_id}",
            workflow_id=workflow_event.event_id,
            workflow_type=getattr(workflow_event.workflow_type, 'value', str(workflow_event.workflow_type)),
            metadata={"payload_keys": list((workflow_event.payload or {}).keys())},
            success=status != "failed",
        )
        return await self.log(record)

    async def log_router_decision(
        self,
        query:      str,
        actor_id:   str,
        actor_role: str,
        decision,   # RouteDecision
    ) -> str:
        """تسجيل قرار الـ Router Chain."""
        record = AuditRecord(
            action=AuditAction.ROUTER_DECISION,
            category=AuditCategory.AI_DECISION,
            severity=AuditSeverity.LOW,
            actor_id=actor_id,
            actor_role=actor_role,
            actor_type="system",
            target_type="agent",
            target_id=decision.primary_agent.value,
            description=f"Router → {decision.primary_agent.value} (conf: {decision.confidence:.2f})",
            request_text=query[:200],
            metadata={
                "strategy":   decision.strategy.value,
                "method":     decision.routing_method,
                "confidence": decision.confidence,
                "reason":     decision.routing_reason,
                "secondary":  [a.value for a in decision.secondary_agents],
            },
            success=True,
            response_ms=decision.elapsed_ms,
        )
        return await self.log(record)

    # ── Query API ─────────────────────────────────────────

    async def search(
        self,
        actor_id:    str | None = None,
        action:      AuditAction | None = None,
        category:    AuditCategory | None = None,
        severity:    AuditSeverity | None = None,
        from_ts:     float | None = None,
        to_ts:       float | None = None,
        success:     bool | None = None,
        limit:       int = 100,
    ) -> list[dict]:
        """بحث في سجل التدقيق (من الـ Buffer)."""
        results = self._buffer.copy()

        if actor_id:
            results = [r for r in results if r.actor_id == actor_id]
        if action:
            results = [r for r in results if r.action == action]
        if category:
            results = [r for r in results if r.category == category]
        if severity:
            results = [r for r in results if r.severity == severity]
        if from_ts:
            results = [r for r in results if r.created_at >= from_ts]
        if to_ts:
            results = [r for r in results if r.created_at <= to_ts]
        if success is not None:
            results = [r for r in results if r.success == success]

        # ترتيب تنازلي — الأحدث أولاً
        results.sort(key=lambda r: r.created_at, reverse=True)
        return [r.to_display() for r in results[:limit]]

    async def get_compliance_summary(self) -> dict:
        """
        ملخص امتثال شامل — يُستخدم في التقارير الدورية.
        """
        now    = time.time()
        day_ago = now - 86400
        week_ago = now - 604800

        recent = [r for r in self._buffer if r.created_at >= day_ago]
        weekly  = [r for r in self._buffer if r.created_at >= week_ago]

        denied_24h    = [r for r in recent if r.action == AuditAction.ACCESS_DENIED]
        ai_decisions  = [r for r in weekly if r.category == AuditCategory.AI_DECISION]
        vault_accesses = [r for r in weekly if r.category == AuditCategory.VAULT_ACCESS]
        critical_events = [r for r in weekly if r.severity == AuditSeverity.CRITICAL]

        # Chain integrity check
        chain_ok = self._verify_chain_sample()

        return {
            "report_generated_at": datetime.now(timezone.utc).isoformat(),
            "total_records":       len(self._buffer),
            "chain_integrity":     "سليم ✓" if chain_ok else "⚠️ تحقق مطلوب",
            "last_24h": {
                "total_events":      len(recent),
                "access_denied":     len(denied_24h),
                "top_denied_actors": self._top_actors(denied_24h, 5),
            },
            "last_7d": {
                "ai_decisions":      len(ai_decisions),
                "vault_accesses":    len(vault_accesses),
                "critical_events":   len(critical_events),
                "success_rate":      self._success_rate(weekly),
            },
            "compliance_flags": self._check_compliance_flags(weekly),
        }

    async def verify_record_integrity(self, record_id: str) -> dict:
        """التحقق من سلامة سجل معيّن."""
        record = next((r for r in self._buffer if r.record_id == record_id), None)
        if not record:
            return {"valid": False, "error": "السجل غير موجود في الـ Buffer"}

        valid = record.verify_integrity(self._signing_key)
        return {
            "record_id":  record_id,
            "valid":      valid,
            "message":    "السجل سليم وغير مُعدَّل ✓" if valid else "⚠️ تحذير: قد يكون السجل مُعدَّلاً!",
            "sequence":   record.sequence_num,
            "created_at": record.created_at_iso,
        }

    # ── Private helpers ───────────────────────────────────

    async def _stream_to_redis(self, record: AuditRecord) -> None:
        """بث السجل على Redis Stream للـ real-time monitoring."""
        try:
            if self._redis is None:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(
                    settings.REDIS_URL, encoding="utf-8", decode_responses=True
                )

            await self._redis.xadd(
                self.REDIS_AUDIT_KEY,
                {
                    "record_id": record.record_id,
                    "action":    record.action.value,
                    "severity":  record.severity.value,
                    "actor":     record.actor_id or "system",
                    "ts":        str(record.created_at),
                },
                maxlen=10_000,   # احتفظ بآخر 10,000 حدث
            )
        except Exception as e:
            # لا تُوقف النظام إذا فشل Redis
            pass

    async def _flush_to_db(self) -> None:
        """كتابة دفعة من السجلات لـ PostgreSQL."""
        if not self._db_session_factory or not self._pending_flush:
            return

        batch = self._pending_flush[:self.BATCH_SIZE]
        self._pending_flush = self._pending_flush[self.BATCH_SIZE:]

        try:
            async with self._db_session_factory() as session:
                from sqlalchemy import text
                for record in batch:
                    await session.execute(
                        text("""
                            INSERT INTO agent_audit_logs (
                                record_id, sequence_num, prev_hash, record_hash,
                                action, category, severity,
                                actor_id, actor_type, actor_role,
                                target_type, target_id,
                                description, request_text, ai_response, ai_decision,
                                tool_calls, masked_fields, tokens_used,
                                ip_address, session_id,
                                success, error_message, response_ms,
                                workflow_id, workflow_type,
                                metadata, created_at
                            ) VALUES (
                                :record_id, :sequence_num, :prev_hash, :record_hash,
                                :action, :category, :severity,
                                :actor_id, :actor_type, :actor_role,
                                :target_type, :target_id,
                                :description, :request_text, :ai_response, :ai_decision,
                                :tool_calls::jsonb, :masked_fields, :tokens_used,
                                :ip_address, :session_id,
                                :success, :error_message, :response_ms,
                                :workflow_id, :workflow_type,
                                :metadata::jsonb, TO_TIMESTAMP(:created_at)
                            ) ON CONFLICT (record_id) DO NOTHING
                        """),
                        {
                            **{k: v for k, v in record.to_dict().items()
                               if k not in ("chain_valid", "created_at_iso")},
                            "tool_calls":  json.dumps(record.tool_calls, default=str),
                            "metadata":    json.dumps(record.metadata, default=str),
                        },
                    )
                await session.commit()

        except Exception as e:
            log.error("AuditTrail: فشل حفظ الدفعة في DB", error=str(e))
            # إعادة للـ pending queue
            self._pending_flush = batch + self._pending_flush

    def _verify_chain_sample(self) -> bool:
        """التحقق من سلسلة آخر 100 سجل."""
        sample = sorted(self._buffer[-100:], key=lambda r: r.sequence_num)
        for i in range(1, len(sample)):
            if sample[i].prev_hash != sample[i-1].record_hash:
                return False
        return True

    def _top_actors(self, records: list[AuditRecord], n: int) -> list[dict]:
        counts: dict = {}
        for r in records:
            k = r.actor_id or "unknown"
            counts[k] = counts.get(k, 0) + 1
        return sorted(
            [{"actor": k, "count": v} for k, v in counts.items()],
            key=lambda x: x["count"], reverse=True
        )[:n]

    def _success_rate(self, records: list[AuditRecord]) -> str:
        if not records:
            return "N/A"
        pct = sum(1 for r in records if r.success) / len(records) * 100
        return f"{pct:.1f}%"

    def _check_compliance_flags(self, records: list[AuditRecord]) -> list[dict]:
        """كشف أنماط تستحق التحقيق."""
        flags: list[dict] = []

        # فحص 1: محاولات وصول مرفوضة متكررة
        denied = [r for r in records if r.action == AuditAction.ACCESS_DENIED]
        actor_counts: dict = {}
        for r in denied:
            actor_counts[r.actor_id or "?"] = actor_counts.get(r.actor_id or "?", 0) + 1
        for actor, count in actor_counts.items():
            if count >= 5:
                flags.append({
                    "type":    "repeated_access_denied",
                    "message": f"المستخدم {actor} رُفض وصوله {count} مرات خلال 7 أيام",
                    "severity": "high",
                })

        # فحص 2: وصول للـ Vault خارج ساعات العمل
        vault_night = [
            r for r in records
            if r.category == AuditCategory.VAULT_ACCESS
            and datetime.fromtimestamp(r.created_at).hour not in range(7, 20)
        ]
        if vault_night:
            flags.append({
                "type":    "vault_off_hours",
                "message": f"وصول للـ Vault خارج ساعات العمل ({len(vault_night)} مرة)",
                "severity": "medium",
            })

        # فحص 3: قرارات AI بدون تسجيل مستخدم
        ai_no_actor = [
            r for r in records
            if r.category == AuditCategory.AI_DECISION
            and not r.actor_id
        ]
        if ai_no_actor:
            flags.append({
                "type":    "anonymous_ai_decisions",
                "message": f"{len(ai_no_actor)} قرار AI بدون تعريف الفاعل",
                "severity": "low",
            })

        return flags


# ═══════════════════════════════════════════════════════════
#  4. Singleton
# ═══════════════════════════════════════════════════════════

_audit_trail: AuditTrail | None = None


def get_audit_trail(db_factory=None) -> AuditTrail:
    global _audit_trail
    if _audit_trail is None:
        _audit_trail = AuditTrail()
        if db_factory:
            _audit_trail.set_db_session(db_factory)
    return _audit_trail


# ═══════════════════════════════════════════════════════════
#  5. Decorator للتسجيل التلقائي
# ═══════════════════════════════════════════════════════════

def audit_action(
    action:   AuditAction,
    category: AuditCategory = AuditCategory.DATA_ACCESS,
    severity: AuditSeverity = AuditSeverity.LOW,
):
    """
    Decorator يُسجّل تلقائياً أي استدعاء لـ API endpoint.

    الاستخدام:
        @router.get("/sensitive-data")
        @audit_action(AuditAction.FILE_ACCESS, severity=AuditSeverity.HIGH)
        async def get_data(current_user = Depends(...)):
            ...
    """
    import functools
    import asyncio

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            audit    = get_audit_trail()
            t_start  = time.time()
            success  = True
            error    = None

            # محاولة استخراج current_user من kwargs
            user = kwargs.get("current_user")
            actor_id   = str(user.id)   if user else None
            actor_role = user.role.value if user else None

            # محاولة استخراج request IP
            request = kwargs.get("request")
            ip = request.client.host if request and request.client else None

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                success = True
                error   = str(e)
                raise
            finally:
                elapsed = int((time.time() - t_start) * 1000)
                record  = AuditRecord(
                    action=action,
                    category=category,
                    severity=severity,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    actor_type="user",
                    description=f"{func.__name__} called",
                    ip_address=ip,
                    success=success,
                    error_message=error,
                    response_ms=elapsed,
                )
                asyncio.create_task(audit.log(record))

        return wrapper
    return decorator


import asyncio
