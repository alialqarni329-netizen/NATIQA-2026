# ناطقة — NATIQA Enterprise AI Platform v4.0

> منصة ذكاء اصطناعي مؤسسية متكاملة: RAG + AES-256 + RBAC + IAM + Multi-Agent Orchestration

---

## 🏗 المكونات

```
natiqa/
├── backend/                    FastAPI (Python 3.11+)
│   ├── app/
│   │   ├── api/
│   │   │   ├── auth.py         JWT + 2FA + Rate Limiting
│   │   │   ├── main_routes.py  Projects / Documents / Chat
│   │   │   ├── user_routes.py  IAM — إدارة المستخدمين والصلاحيات
│   │   │   ├── agent_routes.py Multi-Agent Orchestration API
│   │   │   └── integration_routes.py Integration Hub
│   │   ├── core/
│   │   │   ├── config.py       إعدادات البيئة
│   │   │   ├── database.py     PostgreSQL async (SQLAlchemy 2.0)
│   │   │   ├── dependencies.py Auth guards + Rate limiter
│   │   │   └── security.py     JWT + AES-256-GCM + bcrypt + TOTP
│   │   ├── models/
│   │   │   ├── models.py       User, Project, Document, Conversation, Message, AuditLog
│   │   │   └── models_v2.py    Integration, Agent, Workflow models
│   │   ├── services/
│   │   │   ├── rag.py          RAG: Embed + ChromaDB + LLM
│   │   │   ├── rag_dept.py     ← NEW: Department-scoped RAG isolation
│   │   │   ├── document_processor.py Omni-Document (PDF/Word/Excel/PPT)
│   │   │   └── llm/
│   │   │       ├── factory.py   LLM Provider Factory
│   │   │       ├── claude_adapter.py  Anthropic Claude
│   │   │       ├── ollama_adapter.py  Local Ollama
│   │   │       ├── masking.py   7-Pattern Data Masking
│   │   │       └── base.py      Abstract LLM interface
│   │   ├── agents/
│   │   │   ├── router.py        RouterChain (2-layer routing)
│   │   │   ├── workflow.py      WorkflowEngine (Redis Pub/Sub)
│   │   │   ├── audit_trail.py   HMAC-chained audit logs
│   │   │   ├── agents.py        HR / Finance / Sales agents
│   │   │   └── orchestrator.py  Multi-agent coordinator
│   │   └── integrations/
│   │       ├── base.py          Integration base classes
│   │       ├── adapters.py      REST/GraphQL/DB adapters
│   │       ├── vault.py         Secret management
│   │       └── integration_manager.py
│   ├── migrations/
│   │   ├── v2_omni_processor.sql
│   │   ├── v3_integration_hub.sql
│   │   ├── v4_agent_orchestration.sql
│   │   └── v5_iam_departments.sql  ← Department RBAC schema
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                   Next.js 14 (TypeScript)
│   └── src/
│       ├── app/
│       │   ├── login/page.tsx  ← شاشة دخول (JWT + 2FA)
│       │   ├── dashboard/page.tsx ← لوحة تحكم + تبويبات RBAC
│       │   └── admin/page.tsx  ← لوحة المدير (IAM)
│       └── lib/
│           ├── api.ts          Axios + JWT auto-refresh
│           └── store.ts        Zustand (auth + permissions)
│
├── nginx/nginx.conf            Reverse proxy
├── docker-compose.yml          Full stack deployment
└── .env.example                متغيرات البيئة المطلوبة
