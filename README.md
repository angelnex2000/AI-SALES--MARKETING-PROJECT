# AI Marketing & Sales Teammate 3.0

A multi-agent SaaS platform that automates B2B sales workflows — lead research, qualification, scoring, personalized outreach, reply handling, meeting scheduling, and revenue forecasting. It does not replace a salesperson or a CRM; it's an AI layer that prepares work for human approval before anything customer-facing happens.

See [`CLAUDE.md`](./CLAUDE.md) for the full product/architecture spec and [`FOLDER_STRUCTURE.md`](./FOLDER_STRUCTURE.md) for the complete file tree with rationale for every non-obvious structural decision.

## What it does

Marketing Campaign → Lead Capture → CRM Import → **Research Agent** → **Buying Signal Agent** → **ICP Matching** → **Lead Scoring** → **[Gate 1: Sales Manager assigns]** → **Campaign Agent** → **Outreach Draft** → **[Gate 2: Sales Exec approves]** → Email Send → **Reply Intent Agent** → **Meeting Scheduler** → CRM Update → **Revenue Forecasting** → **Feedback Learning**

The two human gates are non-negotiable: everything else is automated, but a lead is never assigned and an email is never sent without a human clicking approve.

## Tech stack

- **Frontend:** Next.js 14 (App Router) + TypeScript + Tailwind + Zustand
- **Backend:** FastAPI (Python), async SQLAlchemy 2.0, Alembic migrations
- **Database:** PostgreSQL (+ `pgvector` for RAG grounding)
- **Background jobs:** Celery + Redis
- **AI agents:** Python modules under `apps/api/agents/`, each independently testable with mock input — rule-based, ML/DL, or LLM-backed depending on the agent (see the agent table in `CLAUDE.md`)
- **Auth:** JWT in an httpOnly cookie (not `localStorage`), read server-side by Next.js `middleware.ts` for role-based route redirects; `require_role()` in the FastAPI backend is the actual authorization boundary

## Architecture at a glance

- **Multi-tenant.** Every business table carries `company_id`; every query filters by it. A `Company` (our paying customer) and a `Lead` (that customer's prospect) never share a table or FK path.
- **RBAC.** Four roles — Admin, Sales Manager, Sales Executive, Marketing — each with a distinct page-permission matrix (`CLAUDE.md`). Sales Executives see assigned leads only, enforced at the API/DB layer.
- **AI Orchestrator, not scattered agent calls.** `app/services/ai_orchestrator.py` sequences agent calls (Research → Buying Signals → ICP Matching → Lead Scoring) and persists results; nothing else calls an agent directly.
- **Every AI result is explainable.** `LeadScore`, `BuyingSignal`, and `ICPScore` all carry `model_version` + `confidence` + `explanation` — never a bare number.
- **RAG grounds outreach, not general chat.** Personalized Outreach retrieves a tenant's own case studies/product docs/playbooks (`KnowledgeDocument`/`KnowledgeChunk`, pgvector) before drafting; if nothing relevant is found, it falls back to a generic message rather than inventing a claim.
- **CRM-integrated, not CRM-replacing.** The customer's existing CRM (Salesforce/HubSpot/Zoho) is the source of truth for master data; we own AI insights and sync status/notes/meetings back through a single `integration_service.py`, never ad hoc.
- **Background AI jobs are async.** `POST /leads/{id}/research` returns a `Job` id immediately; a Celery worker runs the agents; the frontend polls `GET /jobs/{id}`.

## Local development

Requires Docker (recommended) or a local Python 3.12 + Node 20 + PostgreSQL 16 + Redis setup.

### With Docker

```bash
cp .env.example .env      # fill in SECRET_KEY, ENCRYPTION_KEY, OPENAI_API_KEY, etc.
docker compose up --build
```

This starts `db` (Postgres), `redis`, `api` (FastAPI, :8000), `worker` (Celery), and `web` (Next.js, :3000).

Generate an encryption key for CRM credentials before setting `ENCRYPTION_KEY`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Enable the `pgvector` extension once the database is up (required for RAG's `KnowledgeChunk` table):

```bash
docker compose exec db psql -U postgres -d ai_sales -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Without Docker

```bash
# Backend
cd apps/api
pip install -r requirements.txt
cp .env.example .env   # or use the root .env.example
alembic upgrade head    # once migrations exist — see Current Status below
uvicorn app.main:app --reload

# Celery worker (separate terminal)
celery -A app.core.celery_app.celery_app worker --loglevel=info

# Frontend
cd apps/web
npm install
npm run dev
```

## Data model

The full schema (Phase 4) lives in `apps/api/app/models/` as SQLAlchemy models, grouped:

- **SaaS + Users:** `companies`, `users` (role is a fixed enum, not a permissions table)
- **Sales CRM:** `leads` (status enum, `external_crm_id`), `contacts`, `deal_outcomes`, `crm_activities`, `notes`, `meetings`
- **Marketing + Outreach:** `campaigns`, `campaign_templates`, `audience_segments`, `email_drafts` (Gate 2), `sent_emails`, `replies`
- **AI Results:** `ai_research_reports`, `lead_scores`, `buying_signals`, `icp_scores`, `reply_intent_results`, `revenue_forecasts`, `jobs`, `ai_interaction_logs`, `model_registry_entries`
- **RAG:** `knowledge_documents`, `knowledge_chunks`, `knowledge_embeddings` (pgvector), `rag_retrieval_logs`
- **Production Support:** `integrations`, `integration_sync_logs`, `audit_logs`, `billing_subscriptions`, `usage_records`

Every business table carries `company_id` (multi-tenant isolation); AI-output tables are append-only history carrying `model_name`/`model_version`/`confidence`/`explanation`. See `CLAUDE.md` → "Database Schema" for the design rationale.

## Current status

This is a design-first build: Phases 1–4 (business understanding, product design/wireframes, system architecture, database design) are done and documented in `CLAUDE.md`. The code scaffold in `apps/web` and `apps/api` reflects those decisions — the full data model, auth, tenant isolation, the AI orchestrator, and RAG/CRM/logging/billing infrastructure are implemented, with placeholder agent logic (`*-stub-v0` model versions) so the request flow is demonstrable end-to-end before real LLM/ML models are trained and plugged in.

Known gaps, tracked rather than silently assumed:
- No Alembic migration versions have been generated yet (`migrations/versions/` is empty) — run `alembic revision --autogenerate` now that the schema is stable for this phase.
- Agent implementations (`agents/*/agent.py`, `model.py`) are placeholders returning fixed shapes, not real LLM calls or trained models.
- `CRMAdapter` subclasses (Salesforce/HubSpot/Zoho) raise `NotImplementedError` — no external CRM API client is wired up yet.
- Whether ML models (lead scoring, reply intent, forecasting) train globally or per-tenant is an open decision (`ModelRegistryEntry` currently assumes global).
- `system_logs` is intentionally not a DB table — generic application logging is a deployment/observability concern (log aggregator), not primary-database data.

## Repository layout

See [`FOLDER_STRUCTURE.md`](./FOLDER_STRUCTURE.md) for the full annotated tree.