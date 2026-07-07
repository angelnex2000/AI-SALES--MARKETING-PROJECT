# Project Folder Structure

Stack: Next.js (frontend) · FastAPI (backend) · Python AI Agents · PostgreSQL · Monorepo

```
ai-sales-teammate/
│
├── apps/
│   ├── web/                              # Next.js 14 frontend (App Router)
│   │   ├── src/
│   │   │   ├── app/
│   │   │   │   ├── (auth)/               # Unauthenticated route group
│   │   │   │   │   ├── login/
│   │   │   │   │   ├── signup/
│   │   │   │   │   ├── forgot-password/
│   │   │   │   │   ├── verify-email/
│   │   │   │   │   └── reset-password/
│   │   │   │   │
│   │   │   │   └── (app)/                # Authenticated route group
│   │   │   │       ├── layout.tsx        # Sidebar + nav shell
│   │   │   │       ├── dashboard/
│   │   │   │       │
│   │   │   │       ├── leads/
│   │   │   │       │   ├── page.tsx      # Lead list table
│   │   │   │       │   └── [id]/
│   │   │   │       │       ├── page.tsx          # Lead details (Overview tab)
│   │   │   │       │       ├── research/         # AI Research tab
│   │   │   │       │       ├── buying-signals/
│   │   │   │       │       ├── activities/
│   │   │   │       │       ├── notes/
│   │   │   │       │       └── timeline/
│   │   │   │       │
│   │   │   │       ├── campaigns/
│   │   │   │       │   ├── page.tsx      # Campaign list
│   │   │   │       │   ├── [id]/
│   │   │   │       │   ├── templates/
│   │   │   │       │   └── audience/
│   │   │   │       │
│   │   │   │       ├── outreach/
│   │   │   │       │   ├── drafts/
│   │   │   │       │   ├── scheduled/
│   │   │   │       │   ├── sent/
│   │   │   │       │   └── replies/
│   │   │   │       │
│   │   │   │       ├── meetings/
│   │   │   │       ├── crm/
│   │   │   │       │
│   │   │   │       ├── analytics/
│   │   │   │       ├── pipeline/
│   │   │   │       ├── forecast/
│   │   │   │       │
│   │   │   │       ├── team/
│   │   │   │       │
│   │   │   │       └── settings/
│   │   │   │           ├── page.tsx
│   │   │   │           ├── integrations/
│   │   │   │           ├── ai-config/
│   │   │   │           ├── billing/
│   │   │   │           └── audit-logs/
│   │   │   │
│   │   │   ├── components/
│   │   │   │   ├── ui/               # Primitive components (Button, Input, Modal, Badge)
│   │   │   │   ├── layout/           # Sidebar, Topbar, PageShell
│   │   │   │   ├── leads/            # LeadTable, LeadCard, LeadScoreBadge
│   │   │   │   ├── ai/               # AIResearchPanel, BuyingSignalCard, OutreachDraftBox
│   │   │   │   ├── campaigns/        # CampaignBuilder, AudienceSelector
│   │   │   │   ├── outreach/         # EmailDraftEditor, ReplyIntentBadge
│   │   │   │   ├── meetings/         # MeetingSlotPicker, CalendarView
│   │   │   │   └── analytics/        # ForecastChart, PipelineKanban
│   │   │   │
│   │   │   ├── hooks/                # useLeads, useAIResearch, useOutreach, useAuth
│   │   │   ├── lib/
│   │   │   │   ├── api.ts            # Axios client (httpOnly cookie auth via withCredentials)
│   │   │   │   ├── auth.ts           # canAccess() — nav-hiding convenience only
│   │   │   │   └── utils.ts
│   │   │   ├── middleware.ts         # Role-based route redirect (convenience, not the security boundary)
│   │   │   ├── store/                # Zustand stores (authStore, leadStore)
│   │   │   └── types/                # TypeScript interfaces (Lead, Campaign, User, etc.)
│   │   │
│   │   ├── public/
│   │   ├── .env.local.example
│   │   ├── next.config.ts
│   │   ├── tailwind.config.ts
│   │   └── package.json
│   │
│   └── api/                              # FastAPI backend
│       ├── app/
│       │   ├── main.py                   # App entry point, router registration
│       │   │
│       │   ├── core/
│       │   │   ├── config.py             # Env vars via pydantic-settings
│       │   │   ├── security.py           # JWT, password hashing, encrypt/decrypt_secret (CRM credentials)
│       │   │   ├── database.py           # SQLAlchemy async engine + session
│       │   │   └── celery_app.py         # Celery app (Redis broker/backend) for background AI jobs
│       │   │
│       │   ├── models/                   # SQLAlchemy ORM models — every business table has company_id via TenantMixin
│       │   │   ├── base.py               # Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin
│       │   │   ├── company.py            # Company (+ CompanyStatus) — the SaaS tenant (never confuse with Lead)
│       │   │   ├── user.py               # User (+ last_login_at), Role (fixed enum)
│       │   │   ├── lead.py               # Lead (+ LeadStatus/LeadPriority, external_crm_id), Contact, AIOutputMixin, ResearchReport, LeadScore, BuyingSignal, ICPScore
│       │   │   ├── campaign.py           # Campaign, CampaignTemplate (reusable, versioned), AudienceSegment
│       │   │   ├── outreach.py           # EmailDraft (Gate 2), SentEmail, Reply, ReplyIntentResult
│       │   │   ├── meeting.py            # Meeting
│       │   │   ├── crm.py                # CRMActivity, Note
│       │   │   ├── feedback.py           # DealOutcome (won/lost + structured loss reason)
│       │   │   ├── forecast.py           # RevenueForecast — company-scoped AI forecast history
│       │   │   ├── job.py                # Job — background AI task status (+ started_at/completed_at)
│       │   │   ├── audit_log.py          # AuditLog (business + security category; entity/old/new-value diff)
│       │   │   ├── ai_log.py             # AIInteractionLog — raw input/output per agent call
│       │   │   ├── model_registry.py     # ModelRegistryEntry — trained model versions (not tenant-scoped)
│       │   │   ├── integration.py        # Integration (CRM/email/calendar/chat, encrypted OAuth), IntegrationSyncLog
│       │   │   ├── knowledge.py          # KnowledgeDocument, KnowledgeChunk, KnowledgeEmbedding (pgvector), RAGRetrievalLog
│       │   │   └── billing.py            # BillingSubscription, UsageRecord
│       │   │
│       │   ├── schemas/                  # Pydantic request/response schemas
│       │   │   ├── auth.py
│       │   │   ├── lead.py
│       │   │   ├── campaign.py
│       │   │   ├── outreach.py
│       │   │   ├── meeting.py
│       │   │   └── analytics.py
│       │   │
│       │   ├── routers/                  # FastAPI route handlers (one file per domain)
│       │   │   ├── auth.py               # login (sets httpOnly cookie) / logout / me
│       │   │   ├── leads.py              # list/get (tenant + assigned-only scoped), POST .../research
│       │   │   ├── campaigns.py
│       │   │   ├── outreach.py
│       │   │   ├── meetings.py
│       │   │   ├── crm.py
│       │   │   ├── analytics.py
│       │   │   ├── team.py
│       │   │   ├── settings.py
│       │   │   ├── billing.py
│       │   │   └── jobs.py               # GET /jobs/{id} — poll AI job status
│       │   │
│       │   ├── services/                 # Business logic (called by routers)
│       │   │   ├── ai_orchestrator.py    # Sequences agent calls, persists results, logs AIInteractionLog, updates Job
│       │   │   ├── lead_service.py       # Tenant + assigned-only scoped queries
│       │   │   ├── audit_service.py      # log_action() — single entry point for AuditLog writes
│       │   │   ├── integration_service.py # CRMAdapter base + Salesforce/HubSpot/Zoho stubs, sync_leads()
│       │   │   ├── campaign_service.py
│       │   │   ├── outreach_service.py
│       │   │   ├── meeting_service.py
│       │   │   └── analytics_service.py
│       │   │
│       │   └── dependencies/             # FastAPI Depends() helpers
│       │       ├── auth.py               # get_current_user, require_role()
│       │       └── db.py                 # get_db session
│       │
│       ├── tasks.py                      # Celery tasks (run_lead_intelligence) — replaces BackgroundTasks stopgap
│       │
│       ├── agents/                       # AI agents — each independently runnable + testable
│       │   ├── base.py                   # BaseAgent class (shared interface)
│       │   │
│       │   ├── research/
│       │   │   ├── agent.py              # ResearchAgent
│       │   │   ├── prompts.py
│       │   │   └── tests/
│       │   │
│       │   ├── buying_signals/
│       │   │   ├── agent.py
│       │   │   ├── signals.py            # Signal definitions / rules
│       │   │   └── tests/
│       │   │
│       │   ├── icp_matching/
│       │   │   ├── agent.py
│       │   │   ├── rules.py              # ICP attribute weights
│       │   │   └── tests/
│       │   │
│       │   ├── lead_scoring/
│       │   │   ├── model.py              # Sklearn/XGBoost scoring model
│       │   │   ├── features.py           # Feature engineering
│       │   │   ├── train.py              # Training script
│       │   │   ├── artifacts/            # Saved model files (.pkl / .joblib)
│       │   │   └── tests/
│       │   │
│       │   ├── campaign/
│       │   │   ├── agent.py
│       │   │   ├── rules.py              # Industry → campaign mapping rules
│       │   │   └── tests/
│       │   │
│       │   ├── embeddings/
│       │   │   └── agent.py              # EmbeddingsAgent — shared by RAG retrieval and text similarity
│       │   │
│       │   ├── rag/
│       │   │   └── retriever.py          # RAGRetriever — grounds Outreach in KnowledgeChunk; NO_VERIFIED_PROOF fallback
│       │   │
│       │   ├── outreach/
│       │   │   ├── agent.py              # LLM-powered email drafting, grounded via agents/rag/retriever.py
│       │   │   ├── prompts.py
│       │   │   └── tests/
│       │   │
│       │   ├── reply_intent/
│       │   │   ├── model.py              # Text classifier (BERT / sklearn)
│       │   │   ├── train.py
│       │   │   ├── labels.py             # Intent enum: interested / follow_up / rejected / info_request
│       │   │   ├── artifacts/
│       │   │   └── tests/
│       │   │
│       │   ├── meeting_scheduler/
│       │   │   ├── agent.py
│       │   │   ├── calendar.py           # Calendar availability logic
│       │   │   └── tests/
│       │   │
│       │   ├── forecasting/
│       │   │   ├── model.py              # Revenue forecasting model
│       │   │   ├── features.py
│       │   │   ├── train.py
│       │   │   ├── artifacts/
│       │   │   └── tests/
│       │   │
│       │   └── feedback_learning/
│       │       ├── agent.py              # Reads DealOutcome → triggers retraining
│       │       ├── loss_reasons.py       # LossReason enum (budget / competitor / timing / no_need)
│       │       └── tests/
│       │
│       ├── migrations/                   # Alembic DB migrations
│       │   ├── env.py
│       │   └── versions/
│       │
│       ├── tests/                        # API-level integration tests
│       ├── Dockerfile
│       ├── .env.example
│       ├── requirements.txt              # + celery, redis, cryptography, pgvector
│       ├── alembic.ini
│       └── pyproject.toml
│
├── docs/                                 # Architecture notes, API contracts, agent specs
├── scripts/                              # Dev setup scripts (seed data, db reset)
├── docker-compose.yml                    # Postgres + Redis + API + Celery worker + Web
├── .env.example                          # Root-level shared env vars
└── README.md
```

## Key Structural Decisions

| Decision | Reason |
|---|---|
| `(auth)/` and `(app)/` route groups in Next.js | Separate layouts — auth pages have no sidebar; app pages do |
| Lead tabs as sub-routes (`/leads/[id]/research`) | Matches the design rule: AI Research is a tab, not a top-level page |
| `agents/` inside `api/` | Agents are Python services called by FastAPI routers — not microservices |
| `base.py` in agents | Shared interface so all agents are independently testable with mock input |
| `artifacts/` per ML agent | Each model's saved weights stay next to its training code |
| `loss_reasons.py` as enum | Enforces structured loss reasons for model retraining (no free text) |
| `dependencies/auth.py` with `require_role()` | Central RBAC enforcement for all FastAPI routes |
| `models/feedback.py` | DealOutcome is a first-class model — not a field on Lead |
| `models/base.py::TenantMixin` (`company_id`) | Multi-tenant SaaS — every tenant-scoped table and every query must filter by it |
| `models/company.py` separate from `models/lead.py` | `Company` (tenant/customer) and `Lead` (tenant's prospect) must never share a table or FK path |
| `models/lead.py::AIOutputMixin` | Every AI-produced table gets model_version + confidence + explanation, not just a number |
| `models/job.py` + `routers/jobs.py` | Slow AI tasks run in the background; frontend polls job status instead of blocking a request |
| `services/ai_orchestrator.py` calls into `agents/` | Orchestration (which module, what order, persistence) is a backend service; agent logic stays independently testable in `agents/` |
| httpOnly cookie (not `localStorage`) for the JWT | Lets `middleware.ts` read the role server-side for redirect UX while keeping the token itself inaccessible to client-side JS |
| `KnowledgeDocument`/`KnowledgeChunk` use `pgvector`, not a dedicated vector DB | Per-tenant document volume (case studies, playbooks) doesn't justify the extra operational surface |
| `agents/embeddings/` shared by `agents/rag/` | One embedding model, not duplicated per feature that needs text similarity |
| `ModelRegistryEntry` has no `TenantMixin` | Default: one shared model per model_name across all tenants, not per-customer training — revisit deliberately if that changes |
| `AuditLog` has a `category` field instead of a separate security-log table | Two overlapping logging systems drift out of sync; one table with a category doesn't |
| `AIInteractionLog` separate from `AIOutputMixin` result tables | Raw input/output for debugging hallucinations vs. the structured, user-facing result — different consumers, different shape |
| `CRMConnection.encrypted_credentials` via `Fernet`, not plaintext | CRM OAuth tokens are a customer's credentials to a third-party system — never stored or logged in the clear |
| `Lead.external_crm_id` / `external_crm_source` | The external CRM is the source of truth for customer master data; we own AI insights and push status/notes/meetings back |
| Celery + Redis (`core/celery_app.py`, `tasks.py`, `worker` service) replaces `BackgroundTasks` | Real retries and concurrency control for AI jobs — decided in Module 9 once BackgroundTasks' limits became a repeated flag (job orchestration, then CRM sync retries) |
