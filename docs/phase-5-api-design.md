# Phase 5 — API Design

**Status:** Complete & scaffolded in `apps/api/app/routers/`. This documents the implemented HTTP contract.
**Base path:** `/api/v1` · **Framework:** FastAPI · **Auth:** httpOnly cookie (browser) + `Bearer` (API clients) · **Docs:** `/docs` (OpenAPI).

---

## 1. Conventions

- **Versioning:** every route under `/api/v1` (main.py). A future `/api/v2` can land without breaking clients.
- **IDs are UUIDs** (`UUIDPrimaryKeyMixin`). **Timestamps** are ISO-8601 with timezone.
- **Response envelope** (`app/schemas/common.py`): success `{success, message, data}`; error `{success, message, error_code, details}`. `ok(data, message)` builds the success body; errors are produced by global handlers.
- **Error handling** (`app/core/exceptions.py`): raise an `AppError` subclass (`NotFoundError`, `DuplicateError`, `ForbiddenError`, `ValidationError`, `RateLimitError`). Three handlers serialise `AppError`, `HTTPException`, and Pydantic `RequestValidationError` (which overrides FastAPI's default 422) into the envelope.
- **Business-action endpoints** over generic CRUD where a state change is a business event: `/leads/{id}/assign`, `/deals/{id}/stage`, `/outreach/drafts/{id}/approve`.

## 2. Status codes

`200` ok · `201` created · **`202`** accepted (async → `job_id`) · `400` · `401` · `403` (role categorically denied) · **`404`** (also used for cross-tenant/unassigned access) · `409` conflict · `422` validation · **`429`** rate limit · `500`.

## 3. Auth model

- **Browser:** `POST /auth/login` sets httpOnly `access_token` + `refresh_token` cookies; the body returns only the user. `middleware.ts` reads `role` server-side; JS never sees the token.
- **API clients:** `Authorization: Bearer <token>` accepted by `get_current_user`.
- **Webhooks** (`/outreach/replies/webhook`, `/billing/webhook`) carry no user auth — signature-verified, tenant resolved server-side.
- Real authorization boundary: `require_role()` in `app/dependencies/auth.py`.

## 4. Roles & RBAC

`Role` enum wire values: **`admin` · `sales_manager` · `sales_executive` · `marketing`** (`customer` is external, no login, never assignable).

| Domain | admin | sales_manager | sales_executive | marketing |
|---|---|---|---|---|
| Leads / Deals | read | full | **assigned only** | read |
| Campaigns | read | approve | view | full (create/edit) |
| Outreach | ❌ | review | **✅ approve+send (assigned)** | draft only |
| Meetings | read | view | ✅ (assigned) | ❌ |
| Analytics | full | full | limited (assigned) | campaign |
| AI Center / Users / Integrations / Billing | ✅ / ✅ / ✅ / ✅ | view / view / ❌ / ❌ | ❌ | ❌ |

## 5. Tenant isolation

Every tenant-scoped query filters `company_id = current_user.company_id` in the service layer (`lead_service.py`). A `sales_executive`'s `owner_id` filter is **forced server-side** and overrides any `owner_id` query param. Cross-tenant/unassigned access → **404, never 403**. Flat sub-resource routes (`/contacts/{id}`, `/notes/{id}`, `/deals/{id}`, `/drafts/{id}`) re-derive the parent lead and re-run the isolation check before writing.

---

## 6. Endpoint map (as implemented)

### Auth — `app/routers/auth.py`
`POST /auth/signup` (new company + first admin) · `POST /auth/login` · `POST /auth/logout` · `POST /auth/refresh-token` · `GET /auth/me` · `POST /auth/verify-email` · `POST /auth/resend-verification` · `POST /auth/forgot-password` · `POST /auth/reset-password`. *(Email-driven flows validate input; dispatch wired with the email integration.)*

### Users / Roles / Permissions — `app/routers/users.py`
`GET/POST /users` · `GET/PUT/DELETE /users/{id}` (create/update/delete = admin; list/get = admin+manager; delete = soft-deactivate; last-admin guarded; `role: customer` rejected) · `GET /roles` · `GET /permissions` (both **constants**, no roles/permissions tables).

### Leads & Contacts — `app/routers/leads.py`
`GET/POST /leads` · `GET/PUT/DELETE /leads/{id}` · `POST /leads/{id}/assign` (**Gate 1**, manager only, assignee must be a same-company `sales_executive`) · `POST /leads/import-csv` (202 + job) · `GET/POST /leads/{id}/contacts` · `PUT/DELETE /contacts/{id}` (single-primary enforced) · `GET/POST /leads/{id}/activities` · `GET/POST /leads/{id}/notes` · `DELETE /notes/{id}` · `GET /leads/{id}/deals` · `GET /leads/{id}/timeline` (computed).

### Deals & Pipeline — `app/routers/deals.py`
`GET/POST /deals` · `GET/PUT/DELETE /deals/{id}` · `PATCH /deals/{id}/stage` (reopen closed_won = manager only; closed_lost requires enum `loss_reason` → `deal_outcomes`; enqueues async forecast job) · `GET /pipeline/board` · `GET /pipeline/stages`. `DealStage`: `new · qualified · demo_scheduled · proposal_sent · negotiation · closed_won · closed_lost`.

### Campaigns & Templates — `app/routers/campaigns.py`
`GET/POST /campaigns` · `GET/PUT/DELETE /campaigns/{id}` · `POST /campaigns/{id}/approve` (manager) · `GET /campaigns/templates/all` · `POST /campaigns/templates` · `PUT /campaigns/templates/{id}` (**creates a new version**). Create/edit = marketing.

### Outreach — `app/routers/outreach.py`
`POST /outreach/generate` (202 + job; exec assigned / marketing draft) · `GET /outreach/drafts` · `GET/PUT /outreach/drafts/{id}` · `POST /outreach/drafts/{id}/approve` (**Gate 2**, exec) · `.../reject` · `.../send` (exec; approved-only; via integration svc) · `GET /outreach/emails` · `POST /outreach/replies/webhook` (unauthenticated, signature-verified, tenant resolved from thread → saves `Reply` + queues intent classification).

### Meetings — `app/routers/meetings.py`
`GET/POST /meetings` · `GET/PUT/DELETE /meetings/{id}` · `GET /meetings/availability` · `POST /meetings/suggest-slots` (Scheduler agent) · `POST /meetings/{id}/outcome` (business event → activity + forecast job) · `POST /meetings/{id}/sync-calendar` (202). Booking = **sales_executive only**; manager/admin read; marketing none.

### AI — `app/routers/ai.py`
`POST /ai/leads/{id}/run-intelligence` (full pipeline, 202) · `POST /ai/leads/{id}/{agent}` (research|buying-signals|icp-score|score) · `GET /ai/leads/{id}/{research|buying-signals|icp-score|score}` (append-only history) · `GET /ai/jobs` · `GET /ai/jobs/{id}` · `POST /ai/forecast/run` · `GET /ai/forecast` · `POST /ai/replies/{id}/classify` · **AI Center:** `GET /ai/models` · `GET /ai/health` · `GET /ai/interactions` (admin) · `GET/PUT /ai/scoring-config` (admin). All agent calls go through the orchestrator/worker, never router→agent directly.

### RAG — `app/routers/rag.py`
`POST /rag/documents` (202, async index; marketing+admin) · `GET /rag/documents` · `GET /rag/documents/{id}` · `DELETE /rag/documents/{id}` (admin) · `POST /rag/search` (empty = valid 200) · `GET /rag/retrievals/{id}`. **No `/rag/generate`** — generation stays behind `/outreach/generate`.

### Analytics — `app/routers/analytics.py`
`GET /analytics/dashboard` · `/leads` · `/campaigns` (role-scoped; exec = assigned) · `/revenue` · `/team-performance` (manager+admin).

### Integrations — `app/routers/integrations.py` (admin only)
`GET /integrations` · `POST /integrations/connect` (returns OAuth URL) · `GET /integrations/oauth/callback` (stores encrypted tokens) · `POST /integrations/{id}/disconnect` · `POST /integrations/{id}/sync` (202) · `GET /integrations/{id}/sync-logs`. AI insights never sync outward.

### Billing — `app/routers/billing.py` (admin only)
`GET /billing/subscription` · `/usage` · `/invoices` · `POST /billing/upgrade` · `/cancel` · `POST /billing/webhook` (provider-signed, no user auth).

### Jobs — `app/routers/jobs.py`
`GET /jobs/{id}` (also available as `/ai/jobs/{id}`).

---

## 7. Cross-cutting (Module 11)

- **Rate limiting** (Redis-backed, `429` + `Retry-After`): login (per-IP/email), `/outreach/generate`, `/rag/search`, `/leads/import-csv`, `/outreach/drafts/{id}/send`. *(Design; middleware to be wired.)*
- **Audit** via `audit_service.log_action` → single `audit_logs` table with `category` (`business`/`security`). Gate 1/Gate 2 crossings are logged. Distinct from `ai_interaction_logs` (raw agent I/O).
- **AI safety:** every AI result carries `model_name`/`model_version`/`confidence`/`explanation`, append-only; customer-facing output requires Gate 2 approval.

## 8. Schema deltas still required

The Module 5 **Deal reversal** is implemented (`app/models/deal.py`), but these follow-ups remain (code still reflects the old lead-as-deal shape in places):

1. **`Lead.status`** (`lead.py`) still carries pipeline stages (`demo_scheduled`, `proposal`, `closed_won`, `closed_lost`). These belong on `Deal.stage`; `Lead.status` should reduce to a lead lifecycle (`new · researching · ready · qualified`).
2. ~~**`DealOutcome`** keyed to `lead_id`~~ — **DONE (Phase 7 Module 11).** Re-keyed to `deal_id` with `lead_id` retained as a denormalised column for per-account aggregation. `deal_service.change_stage` writes both. In the migration, `deals` is now created before `deal_outcomes` (and dropped after it) because of the new FK.
3. **Revenue Forecasting** should read `deals` (Σ open-deal `amount × win-rate-by-stage`). Note `Deal.amount` is now `NUMERIC(14,2)` → `Decimal`, so the forecasting agent must not cast to `float` before summing.
4. **No Alembic migrations generated yet** — superseded: `92f0cac4322f_initial_schema.py` exists and is hand-maintained in step with the models. Verify parity with `alembic upgrade head --sql` rather than regenerating, which would drop the hand-added `DROP TYPE` block in `downgrade()`.
5. **Stubs:** agent workers, integration/CRM adapters, RAG retriever, email/billing providers, and Redis-backed rate limiting/refresh-denylist are placeholders; endpoints are contract-complete and enqueue jobs but the workers are not yet functional.
