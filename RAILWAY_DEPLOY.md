# NATIQA — Railway Deployment Guide
# Phase 2: First Cloud Deployment

## Architecture on Railway

```
┌─────────────────────────────────────────────────────────┐
│                    Railway Project                       │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Backend    │  │  PostgreSQL  │  │    Redis     │  │
│  │  (FastAPI)   │──│   Plugin     │  │   Plugin     │  │
│  │   Port $PORT │  │  Auto URL    │  │  Auto URL    │  │
│  └──────┬───────┘  └──────────────┘  └──────────────┘  │
│         │                                               │
│  ┌──────┴───────┐                                       │
│  │   Frontend   │  (separate Railway service)           │
│  │  (Next.js)   │                                       │
│  │   Port 3000  │                                       │
│  └──────────────┘                                       │
└─────────────────────────────────────────────────────────┘
```

---

## Step 1 — Push to GitHub

```bash
cd /path/to/natiqa_fixed

git init
git add .
git commit -m "Phase 1+2: B2B SaaS foundation + Railway deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/natiqa.git
git push -u origin main
```

> **Verify .env is NOT committed:**
> `git status` should not show `.env`. Check with: `cat .gitignore | grep .env`

---

## Step 2 — Create Railway Project

1. Go to [railway.app](https://railway.app) → **New Project**
2. Choose **"Deploy from GitHub repo"** → select your `natiqa` repo
3. Railway auto-detects the `railway.toml` in the root

---

## Step 3 — Add Database Plugins

In your Railway project dashboard:

### PostgreSQL
1. Click **"+ New"** → **"Database"** → **"PostgreSQL"**
2. Railway auto-injects `DATABASE_URL` into your backend service
3. Note the **public connection string** for migration (Step 5)

### Redis
1. Click **"+ New"** → **"Database"** → **"Redis"**
2. Railway auto-injects `REDIS_URL` into your backend service

---

## Step 4 — Set Environment Variables

In Railway → Backend Service → **Variables** tab, add:

| Variable | Value | Notes |
|----------|-------|-------|
| `SECRET_KEY` | `$(openssl rand -hex 32)` | Run locally, paste result |
| `ENCRYPTION_KEY` | `$(openssl rand -hex 32)` | Different from SECRET_KEY |
| `CLAUDE_API_KEY` | `sk-ant-...` | From console.anthropic.com |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | |
| `FIRST_ADMIN_EMAIL` | `admin@yourcompany.com` | |
| `FIRST_ADMIN_PASSWORD` | Strong password | Min 12 chars |
| `FIRST_ADMIN_NAME` | مدير النظام | |
| `CORS_ORIGINS` | `https://your-frontend.up.railway.app` | Add after frontend deploys |
| `ENVIRONMENT` | `production` | |
| `DEBUG` | `False` | |
| `RESEND_API_KEY` | `re_...` | Leave blank for mock mode |

> `DATABASE_URL` and `REDIS_URL` are **auto-set** by the plugins — do not add manually.

---

## Step 5 — Apply Database Migration ⚠ CRITICAL

**Run BEFORE the app receives any traffic.**

### Method A: Railway CLI (recommended)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Link to your project
railway link

# Get a temporary DB shell and run migration
railway run psql $DATABASE_URL < migrate_phase1.sql
```

### Method B: Direct psql via Railway public URL

Railway gives each Postgres plugin a **public URL** visible in the plugin dashboard.

```bash
# Copy the full connection string from Railway Postgres dashboard, then:
psql "postgresql://user:password@host.railway.internal:5432/dbname" \
  < migrate_phase1.sql
```

### Method C: Python runner (from Railway shell)

```bash
railway run python migrate_phase1.py
```

### Expected output (all steps should show OK):
```
>>> Step 3: Adding Phase 1 columns to users table
ALTER TABLE     (x12 times)
>>> Step 4: Creating indexes
CREATE INDEX
CREATE INDEX
>>> Step 5: Back-filling existing users
UPDATE N
>>> Step 6: Verification
 column_name     | data_type
 approval_status | USER-DEFINED
 business_name   | character varying
 document_number | character varying
 document_type   | USER-DEFINED
 is_verified     | boolean
 referral_code   | character varying
 ...
(12 rows)
```

---

## Step 6 — Verify Deployment

After Railway shows **"Deployed"** (green):

### Health check
```bash
curl https://your-backend.up.railway.app/api/health
# Expected:
# {"status":"ok","version":"4.1.0","environment":"production","database":"ok","debug":false}
```

### Registration test
```bash
curl -X POST https://your-backend.up.railway.app/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email":           "test@techcorp.sa",
    "password":        "Secure@2026",
    "full_name":       "أحمد محمد",
    "business_name":   "شركة تك",
    "document_type":   "cr",
    "document_number": "1010123456"
  }'
# Expected:
# {"message":"Registration successful. An OTP has been sent to your email address.","user_id":"..."}
```

---

## Step 7 — Deploy Frontend (Separate Service)

1. In Railway project → **"+ New"** → **"GitHub Repo"** → same repo
2. Set **Root Directory** to `frontend/`
3. Railway detects Next.js automatically
4. Add variable: `NEXT_PUBLIC_API_URL=https://your-backend.up.railway.app/api`
5. After frontend deploys, copy its URL and add to backend's `CORS_ORIGINS`

---

## Step 8 — Admin Approval Test (on Railway)

```bash
# List pending users
railway run python test_approve_user.py

# Approve a specific user
railway run python test_approve_user.py user@company.com

# Reject with reason
railway run python test_approve_user.py user@company.com reject "Incomplete documents"
```

---

## Step 9 — Enable Real Email (Phase 1.5)

1. Sign up at [resend.com](https://resend.com) (free tier: 3,000 emails/month)
2. Verify your domain (`natiqa.ai`)
3. Create API key → copy it
4. In Railway Variables: `RESEND_API_KEY=re_...`
5. In `backend/app/api/auth.py` → find `_send_otp_email()` → uncomment the 5 Resend lines

---

## Monitoring

| URL | Purpose |
|-----|---------|
| `GET /api/health` | Railway health check (DB + app status) |
| `GET /api/docs` | Swagger UI (only when `DEBUG=True`) |
| Railway Logs tab | Real-time structured logs (structlog JSON) |

---

## File Manifest (all committed to git)

```
natiqa/
├── railway.toml                    ← Railway build + deploy config
├── .env.example                    ← Variable reference (safe to commit)
├── .gitignore                      ← Excludes .env, __pycache__, etc.
├── migrate_phase1.sql              ← Run once on prod DB
├── migrate_phase1.py               ← Alternative Python runner
├── test_approve_user.py            ← Admin approval CLI tool
├── backend/
│   ├── Dockerfile                  ← Multi-stage, Railway-optimised
│   ├── requirements.txt
│   └── app/
│       ├── main.py                 ← /api/health (DB-aware)
│       ├── core/config.py          ← Railway URL normalisation + Resend
│       ├── models/models.py        ← Phase 1 User model (12 new fields)
│       └── api/
│           ├── auth.py             ← /register /verify-email /resend-otp /login
│           └── admin_routes.py     ← /admin/pending /approve /reject
└── frontend/
    ├── Dockerfile                  ← Next.js standalone build
    └── next.config.js              ← output: standalone
```
