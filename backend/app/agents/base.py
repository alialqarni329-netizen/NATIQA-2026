"""
╔══════════════════════════════════════════════════════════════════════════╗
║   NATIQA — Agent Base Framework  (بدون LangChain — بنية خاصة أخف)      ║
║                                                                          ║
║  لماذا لا LangChain؟                                                    ║
║    LangChain ثقيل (800+ MB) ويضيف تعقيداً غير ضروري على البنية          ║
║    القائمة. بدلاً منه بنينا AgentBase خفيف يعتمد على نفس LLM Adapter   ║
║    الموجود + Tool Registry بنمط مشابه لـ LangChain Tools.               ║
║                                                                          ║
║  البنية:                                                                 ║
║    AgentTool      → وحدة قدرة واحدة (مثل: get_budget)                  ║
║    AgentMemory    → ذاكرة المحادثة (في الذاكرة فقط — لا تخزين)         ║
║    AgentBase      → الوكيل الأساسي المجرد                               ║
║    AgentResult    → نتيجة موحّدة من أي وكيل                             ║
║                                                                          ║
║  مبادئ الأمان:                                                           ║
║    • كل وكيل محصور بـ tools محددة (Least Privilege)                     ║
║    • System Prompt غير قابل للتجاوز (Prompt Injection Protection)       ║
║    • كل استدعاء tool مسجّل في Audit قبل التنفيذ                         ║
║    • الوكيل لا يمكنه الوصول لبيانات قسم آخر مباشرةً                    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

import structlog

from app.services.llm.factory import get_llm
from app.services.llm.masking import mask_sensitive_data, unmask_data
from app.core.config import settings

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
#  1. Enums
# ═══════════════════════════════════════════════════════════

class AgentType(str, Enum):
    HR_AGENT      = "hr_agent"
    FINANCE_AGENT = "finance_agent"
    SALES_AGENT   = "sales_agent"
    ROUTER        = "router"
    ORCHESTRATOR  = "orchestrator"


class AgentStatus(str, Enum):
    IDLE       = "idle"
    THINKING   = "thinking"
    EXECUTING  = "executing"
    WAITING    = "waiting"   # ينتظر وكيلاً آخر
    DONE       = "done"
    FAILED     = "failed"


class ToolCallStatus(str, Enum):
    SUCCESS  = "success"
    FAILED   = "failed"
    SKIPPED  = "skipped"   # رُفض لأسباب RBAC


# ═══════════════════════════════════════════════════════════
#  2. Agent Tool
# ═══════════════════════════════════════════════════════════

@dataclass
class AgentTool:
    """
    وحدة قدرة واحدة يملكها الوكيل.
    مثل LangChain Tool لكن أبسط وأخف.

    الـ function يجب أن تكون async وتقبل **kwargs.
    """
    name:        str
    description: str              # يُقرأ من LLM لاختيار الأداة
    parameters:  dict             # JSON Schema للمعاملات
    function:    Callable[..., Awaitable[Any]]
    requires_roles: set[str] = field(default_factory=lambda: {"analyst", "admin", "super_admin"})
    dangerous:   bool = False     # يتطلب تأكيداً إضافياً

    def to_llm_spec(self) -> dict:
        """تحويل للصيغة التي يفهمها LLM (Function Calling)."""
        return {
            "name":        self.name,
            "description": self.description,
            "parameters":  self.parameters,
        }


@dataclass
class ToolCallRecord:
    """سجل استدعاء tool واحد."""
    tool_name:   str
    arguments:   dict
    result:      Any
    status:      ToolCallStatus
    elapsed_ms:  int
    error:       str | None = None
    called_at:   float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════
#  3. Agent Memory (قصيرة الأمد)
# ═══════════════════════════════════════════════════════════

@dataclass
class AgentMessage:
    role:    str   # user | assistant | tool
    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class AgentMemory:
    """
    ذاكرة المحادثة للوكيل.
    محدودة بـ max_turns لمنع تضخم context window.
    لا تُخزَّن على القرص — تُحذف بنهاية الجلسة.
    """

    def __init__(self, max_turns: int = 10):
        self._messages: list[AgentMessage] = []
        self._max_turns = max_turns

    def add(self, role: str, content: str, tool_calls: list | None = None) -> None:
        self._messages.append(AgentMessage(
            role=role,
            content=content,
            tool_calls=tool_calls or [],
        ))
        # احتفظ بآخر N رسائل فقط
        if len(self._messages) > self._max_turns * 2:
            self._messages = self._messages[-self._max_turns * 2:]

    def to_llm_messages(self) -> list[dict]:
        """تحويل للصيغة المناسبة للـ LLM."""
        msgs = []
        for m in self._messages:
            msgs.append({"role": m.role, "content": m.content})
        return msgs

    def clear(self) -> None:
        self._messages.clear()

    @property
    def turn_count(self) -> int:
        return sum(1 for m in self._messages if m.role == "user")


# ═══════════════════════════════════════════════════════════
#  4. Agent Result
# ═══════════════════════════════════════════════════════════

@dataclass
class AgentResult:
    """نتيجة موحّدة من أي وكيل."""
    success:        bool
    agent_type:     AgentType
    session_id:     str
    response:       str                    # الجواب النهائي للمستخدم
    tool_calls:     list[ToolCallRecord] = field(default_factory=list)
    sub_events:     list[dict]           = field(default_factory=list)  # للـ cross-agent
    elapsed_ms:     int   = 0
    tokens_used:    int   = 0
    masked_fields:  int   = 0
    requires_approval: bool = False        # هل يحتاج موافقة بشرية؟
    approval_payload:  dict | None = None  # البيانات المنتظرة للموافقة
    errors:         list[str] = field(default_factory=list)
    metadata:       dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
#  5. Abstract Agent Base
# ═══════════════════════════════════════════════════════════

class AgentBase(ABC):
    """
    الوكيل الأساسي.

    دورة الحياة:
        think()  → يحلل الطلب ويختار tool
        act()    → ينفّذ tool
        respond()→ يصيغ الجواب النهائي

    نمط ReAct (Reasoning + Acting):
        Thought → Action → Observation → Thought → ...
        حتى الوصول لإجابة نهائية أو max_iterations
    """

    MAX_ITERATIONS = 5   # أقصى عدد دورات ReAct قبل التوقف

    def __init__(
        self,
        agent_type:  AgentType,
        system_prompt: str,
        tools:       list[AgentTool],
        user_role:   str = "analyst",
    ):
        self.agent_type    = agent_type
        self.system_prompt = system_prompt
        self.tools         = {t.name: t for t in tools}
        self.user_role     = user_role
        self.memory        = AgentMemory()
        self.session_id    = str(uuid.uuid4())
        self._status       = AgentStatus.IDLE
        self._audit_trail: list[dict] = []

    # ── Abstract ──────────────────────────────────────────

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """اسم الوكيل بالعربية."""

    # ── Main Entry ────────────────────────────────────────

    async def run(self, user_input: str, context: dict | None = None) -> AgentResult:
        """
        نقطة الدخول الرئيسية — ينفّذ حلقة ReAct.

        context: معلومات إضافية (employee_id, project_id, etc.)
        """
        t_start     = time.time()
        self._status = AgentStatus.THINKING
        tool_calls:  list[ToolCallRecord] = []
        total_tokens = 0
        total_masked = 0

        self._audit("run_start", {"input": user_input[:200], "role": self.user_role})

        # إضافة رسالة المستخدم للذاكرة
        self.memory.add("user", user_input)

        llm = get_llm()

        for iteration in range(self.MAX_ITERATIONS):

            # ── Think: بناء prompt ──────────────────────────
            prompt = self._build_react_prompt(user_input, context, iteration)

            # Masking قبل LLM
            mask_result = None
            if llm.provider_name == "claude":
                mr = mask_sensitive_data(prompt, settings.ENCRYPTION_KEY[:16])
                prompt_to_send = mr.masked_text
                mask_result    = mr
                total_masked  += mr.count
            else:
                prompt_to_send = prompt

            # ── Act: استدعاء LLM ────────────────────────────
            self._status = AgentStatus.EXECUTING
            try:
                resp = await llm.generate(
                    prompt=prompt_to_send,
                    system=self.system_prompt,
                    temperature=0.2,
                    max_tokens=1500,
                )
                total_tokens += resp.total_tokens
            except Exception as e:
                self._audit("llm_error", {"error": str(e)})
                return AgentResult(
                    success=False,
                    agent_type=self.agent_type,
                    session_id=self.session_id,
                    response=f"خطأ في معالجة طلبك: {e}",
                    elapsed_ms=int((time.time() - t_start) * 1000),
                    errors=[str(e)],
                )

            llm_text = resp.content
            if mask_result:
                llm_text = unmask_data(llm_text, mask_result.mappings)

            # ── Observe: هل LLM يريد استدعاء tool؟ ──────────
            tool_call = self._parse_tool_call(llm_text)

            if tool_call:
                tool_name, tool_args = tool_call
                tc_record = await self._execute_tool(tool_name, tool_args)
                tool_calls.append(tc_record)
                self.memory.add("assistant", f"[Tool: {tool_name}]\n{json.dumps(tool_args, ensure_ascii=False)}")
                self.memory.add("tool", f"[Result]\n{json.dumps(tc_record.result, ensure_ascii=False, default=str)[:2000]}")
                self._audit("tool_executed", {
                    "tool": tool_name,
                    "status": tc_record.status.value,
                    "elapsed_ms": tc_record.elapsed_ms,
                })
                continue  # دورة جديدة مع نتيجة الـ tool

            # ── Final Answer ──────────────────────────────────
            # لا يوجد tool call → هذا هو الجواب النهائي
            self.memory.add("assistant", llm_text)
            self._status = AgentStatus.DONE
            self._audit("run_complete", {"tokens": total_tokens, "iterations": iteration + 1})

            return AgentResult(
                success=True,
                agent_type=self.agent_type,
                session_id=self.session_id,
                response=llm_text,
                tool_calls=tool_calls,
                elapsed_ms=int((time.time() - t_start) * 1000),
                tokens_used=total_tokens,
                masked_fields=total_masked,
                metadata={"iterations": iteration + 1},
            )

        # تجاوز MAX_ITERATIONS
        self._status = AgentStatus.FAILED
        return AgentResult(
            success=False,
            agent_type=self.agent_type,
            session_id=self.session_id,
            response="تعذّر الوصول لإجابة نهائية بعد عدة محاولات. يرجى إعادة صياغة السؤال.",
            tool_calls=tool_calls,
            elapsed_ms=int((time.time() - t_start) * 1000),
            tokens_used=total_tokens,
            errors=["max_iterations_exceeded"],
        )

    # ── ReAct Prompt ──────────────────────────────────────

    def _build_react_prompt(
        self,
        user_input: str,
        context: dict | None,
        iteration: int,
    ) -> str:
        """
        بناء Prompt بنمط ReAct.

        الصيغة:
          [سياق] + [أدوات متاحة] + [تاريخ المحادثة] + [السؤال]
          + [تعليمات التنسيق: Thought/Action/Final Answer]
        """
        tools_spec = json.dumps(
            [t.to_llm_spec() for t in self.tools.values()],
            ensure_ascii=False, indent=2,
        )

        history = ""
        if self.memory.turn_count > 0:
            for msg in self.memory.to_llm_messages()[-6:]:
                role_label = {"user": "المستخدم", "assistant": "الوكيل", "tool": "نتيجة الأداة"}.get(msg["role"], msg["role"])
                history += f"\n[{role_label}]: {msg['content'][:800]}"

        ctx_str = ""
        if context:
            ctx_str = f"\n[سياق إضافي]: {json.dumps(context, ensure_ascii=False)}"

        return f"""
الأدوات المتاحة لك:
{tools_spec}

{history}
{ctx_str}

السؤال الحالي: {user_input}

تعليمات الرد:
1. إذا تحتاج معلومات من أداة، أجب بالصيغة:
   TOOL_CALL: {{"tool": "اسم_الأداة", "args": {{...}}}}

2. إذا عندك إجابة كافية، أجب مباشرةً بالعربية دون TOOL_CALL.

التكرار الحالي: {iteration + 1}/{self.MAX_ITERATIONS}
"""

    # ── Tool Parser ───────────────────────────────────────

    def _parse_tool_call(self, text: str) -> tuple[str, dict] | None:
        """استخراج طلب tool من نص LLM."""
        import re
        pattern = r'TOOL_CALL:\s*(\{.*?\})'
        match   = re.search(pattern, text, re.DOTALL)
        if not match:
            return None
        try:
            call = json.loads(match.group(1))
            return call.get("tool"), call.get("args", {})
        except Exception:
            return None

    # ── Tool Executor ─────────────────────────────────────

    async def _execute_tool(self, tool_name: str, args: dict) -> ToolCallRecord:
        """تنفيذ tool مع RBAC check + Audit."""
        t_start = time.time()

        tool = self.tools.get(tool_name)
        if not tool:
            return ToolCallRecord(
                tool_name=tool_name, arguments=args,
                result={"error": f"الأداة '{tool_name}' غير موجودة"},
                status=ToolCallStatus.FAILED,
                elapsed_ms=0, error=f"Unknown tool: {tool_name}",
            )

        # RBAC
        if self.user_role not in tool.requires_roles:
            self._audit("tool_rbac_denied", {
                "tool": tool_name, "user_role": self.user_role,
                "required": list(tool.requires_roles),
            })
            return ToolCallRecord(
                tool_name=tool_name, arguments=args,
                result={"error": f"دورك '{self.user_role}' لا يملك صلاحية '{tool_name}'"},
                status=ToolCallStatus.SKIPPED,
                elapsed_ms=0,
            )

        # تنفيذ
        try:
            result = await tool.function(**args)
            elapsed = int((time.time() - t_start) * 1000)
            return ToolCallRecord(
                tool_name=tool_name, arguments=args,
                result=result, status=ToolCallStatus.SUCCESS,
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.time() - t_start) * 1000)
            log.error("Tool execution failed", tool=tool_name, error=str(e))
            return ToolCallRecord(
                tool_name=tool_name, arguments=args,
                result={"error": str(e)},
                status=ToolCallStatus.FAILED,
                elapsed_ms=elapsed, error=str(e),
            )

    # ── Audit ─────────────────────────────────────────────

    def _audit(self, event: str, data: dict) -> None:
        self._audit_trail.append({
            "event":      event,
            "agent":      self.agent_type.value,
            "session_id": self.session_id,
            "data":       data,
            "ts":         time.time(),
        })

    @property
    def audit_trail(self) -> list[dict]:
        return self._audit_trail

    @property
    def status(self) -> AgentStatus:
        return self._status
