# ناطقة — NATIQA Enterprise AI Platform v4.0
## دليل البنية المعمارية الشاملة

---

## ملخص المشروع

منصة ذكاء اصطناعي مؤسسية بأعلى معايير الأمان، تعمل كـ **مركز عمليات ذكي** يجمع بين:
- معالجة الوثائق بجميع صيغها
- الربط بأنظمة ERP و HR الخارجية
- نظام وكلاء متعدد يُنسّق العمليات تلقائياً

---

## هيكل الملفات الكامل

```
natiqa/
├── backend/
│   ├── app/
│   │   ├── agents/                          # ← المرحلة 3
│   │   │   ├── base.py          (459 سطر)  # AgentBase + ReAct Loop
│   │   │   ├── agents.py        (511 سطر)  # HR / Finance / Sales Agents
│   │   │   ├── router.py        (367 سطر)  # Router Chain (طبقتان)
│   │   │   ├── workflow.py      (667 سطر)  # Redis Pub/Sub + Celery
│   │   │   ├── audit_trail.py   (826 سطر)  # Audit Trail (HMAC Chained)
│   │   │   └── orchestrator.py  (251 سطر)  # نقطة الدخول المركزية
│   │   │
│   │   ├── integrations/                    # ← المرحلة 2
│   │   │   ├── base.py          (494 سطر)  # Zero Trust Interfaces
│   │   │   ├── vault.py         (497 سطر)  # Secure Vault (PBKDF2+AES)
│   │   │   ├── adapters.py      (819 سطر)  # ERP + HR Adapters
│   │   │   └── integration_manager.py       # Intent Detection + Reports
│   │   │
│   │   ├── services/                        # ← المرحلة 1
│   │   │   ├── document_processor.py        # Omni-Document Processor
│   │   │   └── llm/
│   │   │       ├── masking.py               # Data Masking (7 أنواع)
│   │   │       ├── claude_adapter.py        # Claude API
│   │   │       ├── ollama_adapter.py        # Ollama (محلي)
│   │   │       └── factory.py               # Adapter Pattern
│   │   │
│   │   ├── api/
│   │   │   ├── agent_routes.py              # /api/agents/*
│   │   │   ├── integration_routes.py        # /api/integrations/*
│   │   │   ├── main_routes.py               # /api/projects|documents|chat
│   │   │   └── auth.py                      # /api/auth/*
│   │   │
│   │   ├── models/
│   │   │   ├── models.py                    # v1 (أساسي)
│   │   │   └── models_v2.py                 # v2 (Omni-Doc + RBAC)
│   │   │
│   │   └── core/
│   │       ├── security.py                  # AES-256-GCM + JWT + 2FA
│   │       ├── config.py                    # Settings
│   │       └── dependencies.py              # FastAPI deps
│   │
│   └── migrations/
│       ├── v2_omni_processor.sql
│       ├── v3_integration_hub.sql
│       └── v4_agent_orchestration.sql
│
├── frontend/                                # Next.js 14
├── nginx/
└── docker-compose.yml
```

---

## المراحل الثلاث — تدفق البيانات

### المرحلة 1: Omni-Document Processor

```
رفع ملف (PDF/Excel/Word/PPT)
        ↓
SHA-256 Hash (للتحقق)
        ↓
AES-256-GCM تشفير فوري → القرص
        ↓
استخراج النص (PyMuPDF / Pandas / docx / pptx)
        ↓
تقطيع ذكي (chunk_size=900, overlap=120)
        ↓
Data Masking (7 أنواع) → قبل الإرسال للـ LLM
        ↓
Embeddings → ChromaDB (مع RBAC metadata)
        ↓
Secure Wipe (3 مرور عشوائي + أصفار)
```

**RBAC على مستوى الـ Chunk:**
```
قسم Payroll  → sensitivity=confidential → super_admin فقط
قسم HR       → sensitivity=restricted   → admin + hr_analyst
قسم Finance  → sensitivity=internal     → analyst وفوق
قسم General  → sensitivity=public       → جميع الأدوار
```

---

### المرحلة 2: Integration Hub (Zero Trust)

```
POST /api/integrations/chat
{"query": "كم ميزانية قسم IT؟"}
        ↓
IntentDetector (regex, ~3ms, بدون tokens)
→ BUDGET_QUERY (confidence: 0.87)
        ↓
RBAC Check (analyst ✓)
        ↓
Vault.get_secret("erp_prod", "api_key")
→ PBKDF2 (480,000 iter) → AES-256-GCM decrypt
→ Cache 5 دقائق
        ↓
ERPAdapter.get_budget_status()
+ HMAC-SHA256 Request Signature
+ Zero Trust Security Headers
+ Circuit Breaker (5 failures → OPEN)
        ↓
Data → Masking → Claude API → Unmask
        ↓
تقرير تنفيذي عربي مع الأرقام الدقيقة
```

**Circuit Breaker States:**
```
CLOSED   → الطلبات تمر طبيعياً
OPEN     → محجوب (بعد 5 فشل متتالي) → رسالة خطأ فورية
HALF_OPEN → بعد 60 ثانية، طلب واحد تجريبي
```

---

### المرحلة 3: Multi-Agent Orchestration

#### Router Chain — طبقتان

```
سؤال المستخدم
        ↓
┌────────────────────────────────────┐
│  الطبقة 1: Fast Router (~3ms)      │
│  Keyword Scoring + Pattern Match    │
│  إذا confidence > 0.75 → يوجّه     │
└────────────────┬───────────────────┘
                 │ إذا غامض (confidence ≤ 0.75)
                 ↓
┌────────────────────────────────────┐
│  الطبقة 2: LLM Router (~400ms)     │
│  Claude يختار الوكيل الأنسب        │
│  من قائمة وصف موجزة                │
└────────────────┬───────────────────┘
                 ↓
         RouteDecision
    ┌────────────────────────┐
    │ primary_agent          │
    │ strategy               │
    │   SINGLE_AGENT  ─┐     │
    │   MULTI_AGENT    │     │
    │   ORCHESTRATED  ─┼─→   │
    │   REJECT         │     │
    └──────────────────┘     │
                             ↓
                      Orchestrator
```

#### مثال: طلب شراء عبر وكيل المبيعات

```
"أريد شراء خوادم بـ 200,000 ريال"
         ↓
Router → SALES_AGENT (confidence: 0.91)
Strategy: ORCHESTRATED (مبلغ > 100,000 يحتاج موافقة مالية)
         ↓
Sales Agent (ReAct Loop):
  Thought: "طلب شراء كبير → يحتاج موافقة Finance"
  Action:  get_sales_context()
  Obs:     {team: "enterprise", quota: 85%}
  Thought: "سأرسل للـ Finance عبر Workflow"
  Final:   "تم إرسال طلبك للاعتماد المالي"
         ↓
WorkflowEvent → Redis Channel "workflow:purchase_approval"
         ↓
Celery Worker يستقبل الحدث
         ↓
Finance Agent يراجع الطلب:
  get_budget_status() → IT has 1,160,000 SAR remaining ✓
  Thought: "الميزانية كافية → الموافقة مبدئية"
  يطلب موافقة بشرية نهائية (requires_approval=True)
         ↓
إشعار للمدير المالي عبر النظام
```

#### ReAct Loop (Reasoning + Acting)

```python
for iteration in range(MAX_ITERATIONS=5):
    prompt = build_react_prompt(history, tools, question)
    
    # Masking قبل LLM
    masked = mask_sensitive_data(prompt)
    
    llm_response = await llm.generate(masked)
    
    # Unmask
    response = unmask_data(llm_response, mappings)
    
    if "TOOL_CALL:" in response:
        tool_name, args = parse_tool_call(response)
        # RBAC check
        result = await execute_tool(tool_name, args)
        memory.add("tool", result)
        continue   # دورة جديدة
    else:
        return final_answer   # إجابة نهائية
```

---

## سجل التدقيق — Audit Trail

### الخصائص

| الخاصية | التفاصيل |
|---------|----------|
| **Immutable** | لا حذف، لا تعديل بعد الكتابة |
| **HMAC-SHA256** | كل سجل موقّع → كشف أي تلاعب |
| **Chained** | كل سجل يحتوي `prev_hash` (مثل Blockchain) |
| **Tamper Detection** | فحص فوري: `verify_record_integrity(id)` |
| **Retention** | 7 سنوات (متطلب SAMA) |
| **معايير** | ISO 27001 / SOC 2 / SAMA CSF / NCA ECC |

### ما يُسجَّل

```python
# كل استعلام AI
AuditAction.AI_DECISION
→ {agent, query, tool_calls, tokens, response_summary}

# كل رفض RBAC
AuditAction.RBAC_VIOLATION
→ {user_role, required_role, resource, ip_address}

# كل workflow
AuditAction.WORKFLOW_STARTED / WORKFLOW_COMPLETED
→ {from_agent, to_agent, event_type, payload_summary}

# كل وصول للـ Vault
AuditAction.VAULT_ACCESS
→ {system_id, key_name, requester}

# كل تغيير إعدادات
AuditAction.SETTINGS_CHANGE
→ {field, old_value, new_value, changed_by}
```

### هيكل السجل

```json
{
  "record_id":    "550e8400-e29b-41d4-a716-446655440000",
  "sequence_num": 1247,
  "prev_hash":    "3a7f2b1c...",
  "record_hash":  "8e4d9f0a...",
  "action":       "ai_decision",
  "category":     "ai_operation",
  "severity":     "medium",
  "actor_id":     "user-id",
  "actor_role":   "analyst",
  "actor_type":   "user",
  "description":  "Finance Agent: استعلام الميزانية",
  "ai_decision":  "الميزانية المتبقية 1,160,000 SAR",
  "tool_calls":   [{"tool": "get_budget_status", "success": true}],
  "session_id":   "sess-xyz",
  "ip_address":   "10.0.1.15",
  "success":      true,
  "response_ms":  342,
  "tokens_used":  487,
  "masked_fields": 0,
  "created_at":   "2025-02-25T14:30:00Z"
}
```

---

## Workflow Engine — Redis Pub/Sub

### أنواع الـ Workflows

| النوع | الوصف | يحتاج موافقة بشرية؟ |
|-------|-------|-------------------|
| `purchase_approval` | طلب شراء > 100K ريال | ✓ (مالية) |
| `leave_approval` | طلب إجازة | ✓ (HR) |
| `budget_alert` | تجاوز 80% من الميزانية | لا (إشعار فقط) |
| `cross_dept_query` | استعلام يشمل قسمين | لا |

### قنوات Redis

```
workflow:purchase_approval  → Finance Agent يستمع
workflow:leave_approval     → HR Agent يستمع
workflow:budget_alert       → Notification Service
workflow:completed          → Audit Trail يستمع
```

### Celery Tasks

```python
# celery_app.py (مستقبلاً)
@celery.task(name="process_purchase_approval")
async def process_purchase_approval(event_data: dict):
    event   = WorkflowEvent(**event_data)
    finance = FinanceAgent(user_role="admin")
    result  = await finance.run(
        f"راجع طلب الشراء: {event.payload}"
    )
    if result.requires_approval:
        notify_manager(result.approval_payload)
    else:
        complete_workflow(event.event_id, result)
```

---

## API Endpoints الكاملة

### Agents (المرحلة 3)

| Method | Endpoint | الوصف | الأدوار |
|--------|----------|-------|---------|
| POST | `/api/agents/chat` | سؤال طبيعي → وكيل ذكي | جميع الأدوار |
| GET | `/api/agents/status` | حالة الوكلاء والـ Router | جميع الأدوار |
| GET | `/api/agents/workflows` | الـ Workflows المعلّقة | admin+ |
| GET | `/api/agents/workflows/{id}` | حالة workflow محدد | admin+ |
| GET | `/api/agents/audit` | بحث في سجل التدقيق | admin+ |
| GET | `/api/agents/audit/compliance` | تقرير الامتثال | super_admin |
| GET | `/api/agents/audit/{id}/verify` | التحقق من سلامة سجل | super_admin |

### Integrations (المرحلة 2)

| Method | Endpoint | الوصف |
|--------|----------|-------|
| POST | `/api/integrations/chat` | استعلام ERP/HR طبيعي |
| GET | `/api/integrations/erp/budget` | ميزانية السنة الحالية |
| GET | `/api/integrations/erp/budget/{cc}` | ميزانية مركز تكلفة |
| GET | `/api/integrations/erp/purchase-orders` | طلبات الشراء |
| GET | `/api/integrations/hr/leave-balance/{id}` | رصيد الإجازات |
| POST | `/api/integrations/hr/leave-request` | تقديم طلب إجازة |
| POST | `/api/integrations/vault/store` | تخزين سر مشفّر |
| POST | `/api/integrations/vault/rotate` | تدوير مفتاح |

---

## التشغيل السريع

```bash
# 1. استنساخ وإعداد
git clone <repo>
cd natiqa
cp .env.example .env
# أضف CLAUDE_API_KEY في .env

# 2. تشغيل جميع الخدمات
docker compose up -d

# 3. تطبيق migrations
docker compose exec db psql -U natiqa_admin -d natiqa \
  -f /migrations/v2_omni_processor.sql
docker compose exec db psql -U natiqa_admin -d natiqa \
  -f /migrations/v3_integration_hub.sql
docker compose exec db psql -U natiqa_admin -d natiqa \
  -f /migrations/v4_agent_orchestration.sql

# 4. اختبار النظام
curl -X POST http://localhost/api/agents/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"query": "ما حالة ميزانية قسم تقنية المعلومات؟"}'
```

---

## التبعيات الجديدة (v4)

```
# Celery + Redis
celery[redis]==5.4.0
redis[asyncio]==5.0.4   # موجود مسبقاً

# Monitoring
flower==2.0.1           # Celery dashboard
```

---

## الخارطة الأمنية

```
طبقة 1: Network         → nginx + TLS + Rate Limiting
طبقة 2: Auth            → JWT + 2FA (TOTP) + bcrypt
طبقة 3: RBAC            → 5 أدوار (viewer → super_admin)
طبقة 4: Data Masking    → 7 أنماط → قبل كل LLM call
طبقة 5: Encryption      → AES-256-GCM (ملفات + Vault)
طبقة 6: Zero Trust      → HMAC signing + mTLS ready
طبقة 7: Audit Trail     → Immutable + HMAC Chained
```

---

*NATIQA Enterprise AI Platform v4.0 — فبراير 2025*
