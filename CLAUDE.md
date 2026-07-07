# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AI Marketing & Sales Teammate 3.0** — A multi-agent SaaS platform that automates B2B sales workflows: lead research, qualification, scoring, personalized outreach, reply handling, meeting scheduling, and revenue forecasting.

This is a greenfield project currently in the planning/design phase. Architecture and tech stack decisions are being made as the project progresses.

## Product Context

The platform targets B2B sales and marketing teams who manage large lead volumes. It does not replace salespeople — it acts as an AI layer that prepares work for human approval before action is taken (e.g., outreach emails are AI-drafted but human-approved before sending).

### 15-Step Workflow (Two Human Gates)

Marketing Campaign → Lead Capture → CRM Import → **Research Agent** → **Buying Signal Agent** → **ICP Matching** → **Lead Scoring** → **[GATE 1: Sales Manager assigns]** → **Campaign Agent** → **Outreach Draft** → **[GATE 2: Sales Exec approves]** → Email Send → **Reply Intent Agent** → **Meeting Scheduler** → CRM Update → **Revenue Forecasting** → **Feedback Learning**

The two human gates are non-negotiable design constraints. Everything outside them is automated.

### AI Agent Specifications

| Agent | Implementation | Input → Output |
|---|---|---|
| Research Agent | Rule-based + LLM | Company name → profile (industry, size, news, pain points) |
| Buying Signal Agent | Rule-based + LLM | Research + news → signals list + confidence % |
| ICP Matching Agent | Rule-based + LLM | Lead + research → per-attribute scores + overall % |
| Lead Scoring Model | **ML/DL primary** | All prior outputs + history → score 0–100 |
| Campaign Agent | Rule-based + LLM | Industry/ICP → campaign selection |
| Personalized Outreach Agent | **LLM primary** | Research + campaign + pain points → email draft |
| Reply Intent Agent | **ML/DL primary** | Reply text → intent label + next action |
| Meeting Scheduler | Rule-based | Calendars → meeting slot + invite |
| Revenue Forecasting Agent | **ML/DL primary** | Pipeline + win rates → revenue estimate + confidence |
| Feedback Learning Agent | Rule-based + ML/DL | Won/lost outcomes → updated recommendations |

Agents are internal services/functions — they have no user accounts or permissions. They support human actors, not replace them.

## Product Structure (Phase 2)

Five workspaces, each owned by a primary role:

| Workspace | Primary User | Key Pages |
|---|---|---|
| Authentication | All (unauthenticated) | Login, Signup, Forgot Password, Verify Email, Reset Password |
| Sales Workspace | Sales Executive | Dashboard, Leads, Lead Details, Outreach, Meetings, CRM Timeline |
| Marketing Workspace | Marketing Executive | Campaign Studio, Templates, Audience Segments, Campaign Analytics |
| Management Workspace | Sales Manager | Sales Dashboard, Revenue Forecast, Pipeline, Team Performance, Approvals |
| Company Workspace | Admin | Settings, Team Management, Billing, Integrations, AI Center, Audit Logs |

### Navigation & AI Integration Points

AI is embedded at the point of decision — there is no standalone "AI page."

```
Dashboard          → AI alerts
Leads (list)       → Lead score per row
Lead Details
  ├── Overview      → Lead score + reasons, ICP %, buying signals summary, links to Outreach/Meetings
  ├── AI Research   → Full AI report + ICP breakdown           ← AI tab, NOT a separate route
  ├── Activities    → Human-logged interaction history
  ├── Timeline      → Unified chronological story (CRM events + AI actions + human activity)
  ├── Emails        → Read-only history/status for this lead (sending happens in Outreach Center)
  ├── Meetings      → Read-only view of this lead's scheduled meetings (booking happens in Meetings page)
  └── Notes         → Free-text, human-only
Campaign Studio    → Campaign recommendations
Outreach Center    → AI-generated email draft + Gate 2 approval
Meetings           → Scheduling suggestions
CRM Pipeline       → Stage-by-stage deal view (New → Qualified → ... → Closed Won/Lost)
Analytics          → Revenue forecasting, campaign performance
AI Center          → Agent health, usage stats, scoring-weight config, explainability, audit log
Integrations       → CRM / Email / Calendar / Slack connections (kept separate from Settings)
```

**Design rule:** Lead Details is the single source of truth for a lead. Its tabs (Overview, AI Research, Activities, Timeline, Emails, Meetings, Notes) never become separate top-level pages. Buying Signals has no dedicated tab — it's surfaced inline in the Overview/AI Research AI Insights card, expandable on demand, per the "AI should assist, not interrupt" principle. The Emails and Meetings tabs are lead-scoped, read-only status views; the actual send/schedule workflows (and Gate 2 approval) live only on the Outreach Center and Meetings pages, so there is exactly one place an email can be approved and sent.

## User Roles & Access Control

RBAC is a hard requirement. Four roles:

| Role | Key Constraints |
|---|---|
| Admin | Configures platform (users, AI, CRM, billing). Read-only on leads. Cannot send emails. |
| Sales Manager | Assigns leads, approves campaigns, views full analytics and forecasts. Cannot manage users/billing. |
| Sales Executive | Sees **assigned leads only**. Reviews AI research, approves and sends outreach, books meetings. |
| Marketing Executive | Owns Campaign Studio. Can draft outreach but not send. Read-only on leads/CRM. |
| Customer | External actor. No platform login. Interacts via email, forms, and meeting invites only. |

### Page-Level Permissions

| Page | Admin | Sales Manager | Sales Exec | Marketing |
|---|---|---|---|---|
| Dashboard | ✅ | ✅ | ✅ | ✅ |
| Leads | Read | ✅ | Assigned Only | Read |
| Lead Details | Read | ✅ | Assigned Only | Read |
| Campaign Studio | Read | Approve | View | ✅ |
| Outreach | ❌ | Review | ✅ | Draft |
| Meetings | Read | View | ✅ | ❌ |
| CRM Pipeline | Read | ✅ | Assigned Only | Read |
| Analytics | ✅ | ✅ | Limited | ✅ |
| AI Center | ✅ | View | ❌ | ❌ |
| Team | ✅ | View | ❌ | ❌ |
| Integrations | ✅ | ❌ | ❌ | ❌ |
| Settings | ✅ | ❌ | ❌ | ❌ |
| Billing | ✅ | ❌ | ❌ | ❌ |

### Problem-to-Module Mapping

| Business Problem | AI Module That Solves It |
|---|---|
| Manual company research (30 min/lead) | Research Agent |
| Poor lead qualification | ICP Matching Agent |
| No lead prioritization | Lead Scoring Model |
| Generic outreach emails | Personalized Outreach Agent |
| Missed buying signals | Buying Signal Detection Agent |
| Slow reply handling | Reply Intent Agent |
| Manual meeting scheduling | Meeting Scheduler |
| Outdated CRM records | CRM Integration (auto-update) |
| No campaign performance insight | Analytics Dashboard |
| Uncertain sales pipeline | Revenue Forecasting Agent |

## Business Impact Targets

These are the measurable outcomes the platform must deliver. Use them to validate agent performance during testing.

| Metric | Before | After |
|---|---|---|
| Research time per lead | 30 min | ~2 min |
| Lead prioritization | Guesswork | AI scoring |
| Email personalization | Manual | AI-generated |
| Lead qualification | Manual | Automatic |
| CRM updates | Manual | Automated |
| Follow-up speed | Hours / days | Minutes |

Reference scale: 250 qualified leads/month ≈ 125 hours of manual research eliminated per month.

## Tech Stack & Folder Structure

**Stack:** Next.js 14 (App Router) · FastAPI · PostgreSQL · Python AI agents · Monorepo

```
ai-sales-teammate/
├── apps/
│   ├── web/          # Next.js frontend
│   │   └── src/
│   │       ├── app/
│   │       │   ├── (auth)/       # login, signup, forgot-password, verify-email, reset-password
│   │       │   └── (app)/        # all authenticated pages (shared sidebar layout)
│   │       ├── components/       # ui/, layout/, leads/, ai/, campaigns/, outreach/, analytics/
│   │       ├── hooks/
│   │       ├── lib/              # api.ts, auth.ts
│   │       ├── store/            # Zustand stores
│   │       └── types/
│   │
│   └── api/          # FastAPI backend
│       ├── app/
│       │   ├── core/             # config.py, security.py, database.py
│       │   ├── models/           # SQLAlchemy ORM (user, lead, campaign, outreach, meeting, feedback)
│       │   ├── schemas/          # Pydantic request/response schemas
│       │   ├── routers/          # One file per domain (auth, leads, campaigns, outreach, …)
│       │   ├── services/         # Business logic called by routers
│       │   └── dependencies/     # auth.py (get_current_user, require_role()), db.py
│       ├── agents/               # AI agents — each independently runnable + testable
│       │   ├── base.py           # BaseAgent shared interface
│       │   ├── research/
│       │   ├── buying_signals/
│       │   ├── icp_matching/
│       │   ├── lead_scoring/     # ML model + train.py + artifacts/
│       │   ├── campaign/
│       │   ├── outreach/         # LLM-powered + prompts.py
│       │   ├── reply_intent/     # ML classifier + labels.py + artifacts/
│       │   ├── meeting_scheduler/
│       │   ├── forecasting/      # ML model + artifacts/
│       │   └── feedback_learning/  # loss_reasons.py enum
│       └── migrations/           # Alembic
├── docs/
├── scripts/
└── docker-compose.yml
```

See `FOLDER_STRUCTURE.md` for the full tree with all files listed.

## Multi-Tenancy & Security (hard requirements)

- **Tenant isolation is a hard requirement**, same tier as RBAC: this is a multi-tenant SaaS. Every tenant-scoped table carries `company_id` (`app/models/base.py::TenantMixin`), and every query in every service must filter by it — enforced in code (see `lead_service.py`), never assumed from the URL or trusted from the client. A `Lead` (a tenant's prospect company) must never be confused with or joined against `Company` (the tenant itself, i.e. our paying customer) — they are deliberately separate tables with no shared FK path.
- **Role-based routing mechanism:** `apps/web/src/middleware.ts` decodes the `role` claim from the httpOnly `access_token` cookie to redirect for UX only. The actual authorization boundary is `require_role()` in `apps/api/app/dependencies/auth.py`. Auth uses an httpOnly cookie (set by `POST /auth/login`), not `localStorage` — this is what lets `middleware.ts` read the role server-side while keeping the raw token invisible to client-side JS.
- **AI Orchestrator:** lives at `apps/api/app/services/ai_orchestrator.py`. Routers never call an agent directly — they call the orchestrator, which sequences the agent modules and persists results. Agent implementations stay in the separate top-level `apps/api/agents/` directory (confirmed layer-first, not vertical-slice — see Tech Stack section), independently testable with mock input.
- **AI output shape:** every AI-produced table (`ResearchReport`, `LeadScore`, `BuyingSignal`, `ICPScore`, and any future one) carries `model_name` + `model_version` + `confidence` + `explanation`, never just a raw number (`app/models/lead.py::AIOutputMixin`). AI outputs are append-only history tables, never mutable fields on the parent record — this is why reply-intent classification lives in `ReplyIntentResult` (keyed to `Reply`), not as columns on `Reply`.
- **Background AI jobs:** `Job` model (`app/models/job.py`) tracks `pending/running/completed/failed` (+ `started_at`/`completed_at`) so the frontend can poll `GET /jobs/{id}` instead of blocking on slow agent calls. Runs on Celery + Redis (see the dedicated bullet below).
- **RAG is scoped to grounding Personalized Outreach** (case studies, product docs, pricing, FAQs, playbooks, past successful emails), not a general-purpose feature. `app/models/knowledge.py` (`KnowledgeDocument`, `KnowledgeChunk`) is tenant-scoped like any other business data — one tenant's case studies must never ground another tenant's outreach. Vector storage uses `pgvector` on the existing Postgres (`CREATE EXTENSION IF NOT EXISTS vector;` required), not a dedicated vector DB — document volume per tenant doesn't justify the extra ops surface. `agents/embeddings/` and `agents/rag/retriever.py` are stubs; the retriever's safety rule is explicit: if nothing relevant is found, return `NO_VERIFIED_PROOF` so the caller falls back to a generic message rather than inventing a claim. "Objection Handling" and "Sales Assistant" from the RAG discussion are **not** separate agents — only the existing Personalized Outreach Agent (`agents/outreach/agent.py`) consumes RAG context so far; revisit explicitly if those need to become first-class agents.
- **Model registry** (`app/models/model_registry.py::ModelRegistryEntry`) tracks `model_name`/`model_version`/`file_path`/`metrics`/`status`. Deliberately **not** tenant-scoped — the default is one shared model per `model_name` trained on aggregated data across all tenants, not a model per customer. This is a default, not a settled decision; revisit if per-tenant training is ever required.
- **AI interaction logging**: `app/models/ai_log.py::AIInteractionLog` captures the raw input/output of every agent call (via `AIOrchestrator._log_interaction`) — distinct from `AIOutputMixin`, which stores the structured *result*. Use this table for debugging hallucinations and auditing what an agent actually saw and returned.
- **Audit and security events share one table.** `app/models/audit_log.py::AuditLog` has a `category` (`business` / `security`), rather than two separate logging systems that would drift out of sync. Log through `app/services/audit_service.py::log_action`, not by writing to `AuditLog` directly.
- **CRM integration is bidirectional but CRM-authoritative for master data.** `app/models/integration.py::Integration` is one row per tenant's connected external tool — generalized beyond CRM to cover email/calendar/chat (`integration_type` + `provider`), since the Integrations page has covered Gmail/Calendar/Slack since the Phase 2 wireframes. OAuth tokens (`access_token_encrypted`/`refresh_token_encrypted`) are encrypted at rest via `core/security.py::encrypt_secret`/`decrypt_secret`. `IntegrationSyncLog` holds retry-friendly sync history. `app/services/integration_service.py` has a `CRMAdapter` base class, one subclass per provider (Salesforce/HubSpot/Zoho — all currently `NotImplementedError` stubs). Conflict policy: the external CRM owns customer master data; we own AI insights (lead score, signals, ICP match, embeddings, prompt versions — these stay internal, never synced out). `Lead.external_crm_id` / `external_crm_source` link a local lead to its CRM record. Nothing talks to a CRM directly except through this service.
- **Background AI jobs now run on Celery + Redis**, not FastAPI `BackgroundTasks` — decided in Module 9. `app/core/celery_app.py` defines the app; `app/tasks.py::run_lead_intelligence` is the task; `docker-compose.yml` has a `worker` service running `celery ... worker`. `REDIS_URL` is required.

## Database Schema (Phase 4)

Full table set, grouped. Every table except `companies`, `model_registry_entries`, and the pure join/child tables that carry it explicitly is tenant-scoped via `company_id`. No `roles`/`permissions`/`pipeline_stages`/`deals` tables — role and lead status are fixed enums, and a lead *is* its own deal (Phase 4 Modules 2 & 4 decisions).

| Group | Tables (model file) |
|---|---|
| SaaS + Users | `companies`, `users` (`role` is a fixed enum column) |
| Sales CRM | `leads` (status enum + `external_crm_id`), `contacts`, `deal_outcomes`, `crm_activities`, `notes`, `meetings` |
| Marketing + Outreach | `campaigns`, `campaign_templates` (reusable, versioned), `audience_segments`, `email_drafts` (Gate 2), `sent_emails`, `replies` |
| AI Results | `ai_research_reports`, `lead_scores`, `buying_signals`, `icp_scores` (fixed per-attribute columns), `reply_intent_results`, `revenue_forecasts`, `jobs`, `ai_interaction_logs`, `model_registry_entries` |
| RAG | `knowledge_documents`, `knowledge_chunks`, `knowledge_embeddings` (pgvector, separate from chunks), `rag_retrieval_logs` |
| Production Support | `integrations`, `integration_sync_logs`, `audit_logs`, `billing_subscriptions`, `usage_records` |

Deliberately **not** built as tables: `system_logs` (generic app logging belongs in an external aggregator, not Postgres — only queryable logs like `audit_logs`/`ai_interaction_logs` earn a table). No Alembic migration versions have been generated yet — run `alembic revision --autogenerate` once the schema is stable.

## Development Notes

- **Current phase:** Phases 1–4 complete as of 2026-07-07 — Business Understanding, Product Design (wireframes), System Design (9 architecture modules), and Database Design (full schema, implemented as SQLAlchemy models — see Database Schema section above). Next: Phase 5 (API Design). Migrations not yet generated; agent/CRM logic is still placeholder stubs.
- Each AI agent must be independently testable with mock lead data.
- Sales Exec lead isolation ("assigned leads only") must be enforced at the API/DB layer, not just the UI.
- **Feedback learning requires structured loss reasons** — closed-lost outcomes must store reason as an enum (e.g. `budget_constraint`, `chose_competitor`, `timing`, `no_current_need`), not free text. Free-text reasons cannot be used for model retraining.
- Phase 8 will decide which agents use BERT-style models vs. traditional ML vs. LLM API calls.
