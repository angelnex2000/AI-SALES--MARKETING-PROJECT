
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
- **AI Orchestrator, not scattered agent calls.** `app/services/ai_orchestrator.py` sequences agent calls and persists results; routers never call an agent directly. Every call goes through `run_agent()`, which records the attempt to `ai_interaction_logs` — status, error, timings, retry attempt, run id — whether it succeeds or fails.
- **The agent map is data, verified by test.** `agents/registry.py` declares all thirteen agents and their workflows; `tests/test_agent_registry.py` checks the declaration against what the orchestrator actually runs, so the architecture cannot drift from the code in silence.
- **Every AI result is explainable.** `LeadScore`, `BuyingSignal`, `ICPScore`, `ReplyIntentResult` and `RevenueForecast` all carry `model_version` + `confidence` + `explanation` — never a bare number.
- **RAG grounds outreach, not general chat.** Personalized Outreach retrieves a tenant's own case studies/product docs/playbooks (`KnowledgeDocument`/`KnowledgeChunk`, pgvector) before drafting; if nothing relevant is found, it falls back to a generic message rather than inventing a claim.
- **CRM-integrated, not CRM-replacing.** The customer's existing CRM (Salesforce/HubSpot/Zoho) is the source of truth for master data; we own AI insights and sync status/notes/meetings back through a single `integration_service.py`, never ad hoc.
- **Background AI jobs are async.** `POST /api/v1/ai/leads/{id}/run-intelligence` returns a `Job` id immediately; a Celery worker runs the agents; the frontend polls `GET /api/v1/ai/jobs/{id}`.

## API (Phase 5)

The HTTP contract is designed and scaffolded — see [`docs/phase-5-api-design.md`](./docs/phase-5-api-design.md) for the full route map, RBAC per endpoint, and the schema deltas the Deal reversal introduced. Highlights:

- **Versioned:** everything is under **`/api/v1`** so a future `/api/v2` won't break clients. OpenAPI docs at `/docs`.
- **One response envelope:** `{success, message, data}` on success, `{success, message, error_code, details}` on error — enforced by global handlers (`app/core/exceptions.py`), so every endpoint (and every validation/permission failure) looks the same.
- **Business-action endpoints**, not just CRUD: `POST /leads/{id}/assign` (Gate 1), `PATCH /deals/{id}/stage`, `POST /outreach/drafts/{id}/approve` (Gate 2) — auditable state changes that trigger orchestrated side effects.
- **Isolation returns 404, not 403.** A Sales Executive hitting a lead/deal they aren't assigned to gets `NOT_FOUND`, so the API never leaks that a resource exists.
- **Async by default for slow work:** imports, CRM/calendar sync, AI generation, and doc indexing return **`202 Accepted` + a `job_id`** and run on Celery.
- **Webhooks are signature-verified, not user-authed:** `POST /api/v1/outreach/replies/webhook` and `/api/v1/billing/webhook` resolve the tenant server-side and never trust ids in the body.

Router files live in `apps/api/app/routers/` (one per domain: `auth`, `users`, `leads`, `deals`, `campaigns`, `outreach`, `meetings`, `ai`, `rag`, `analytics`, `integrations`, `billing`).

## Backend (Phase 7)

Phase 7 turned the Phase 5 contract into working, tested code. The layering rule throughout: **routers receive requests, services make business decisions, agents only return predictions.** There is deliberately **no repository layer** — services own their SQLAlchemy queries, because `company_id` filtering is safer as one visible rule per service than split across two layers.

**Foundation**

- **Config** (`app/core/config.py`) is the only module that reads the environment, and it validates at import time — a `DATABASE_URL` without an async driver or an empty `SECRET_KEY` fails at boot, not at the first request. `ENVIRONMENT` drives real behaviour: production disables `/docs` and switches logs to JSON.
- **Structured logging** (`app/core/logging.py`) to stdout only, with a per-request correlation id exposed as `X-Request-ID`. It never logs bodies, headers, or query strings — those carry credentials and lead PII. The Celery worker shares the same config.
- **Ops endpoints** are unversioned and return plain JSON, since load balancers consume them: `/health` (liveness, touches no dependency) and `/health/ready` (pings Postgres and Redis, returns **503** when either is down).

**Invariants enforced in code, not convention**

| Rule | Where | Why |
|---|---|---|
| Cross-tenant access returns **404, never 403** | every service's `_visible()` / `require_*()` | a 403 confirms the resource exists |
| Sales Executives see **assigned leads only** | `lead_service._visible()` | inherited by deals, drafts, meetings, analytics via the parent lead |
| **Gate 1** — only a Sales Manager assigns, only to a Sales Exec in the same company | `lead_service.assign_lead` | `LeadUpdate` has no `owner_id`, so a plain PUT can't bypass it |
| **Gate 2** — editing an approved draft **voids the approval** | `outreach_service.update_draft` | approval binds to content, not the row; otherwise Marketing could rewrite an approved body and the send would deliver unapproved text |
| Leads, contacts and deals are **soft-deleted** | `archived_at` | 17 tables reference `leads.id` with no `ON DELETE`, and cascading would destroy append-only AI history |
| Money is **`Decimal`/`NUMERIC`, reported per currency** | `Deal.amount`, `pipeline_board`, analytics | the column is summed across a pipeline into forecasts; float error compounds, and USD + INR is not a number |
| Enums persist **by value** (`sales_executive`, not `SALES_EXECUTIVE`) | `models/base.py::Base.type_annotation_map` | the DB must match the JWT claim, `require_role()`, and the frontend |
| Activities are **append-only**; notes are **author-owned** | `crm_service` | correcting history means logging a new event; a note keeps showing its author's name |
| Background jobs **dedupe and fail loudly** | `job_service` | a double-click ran the pipeline twice; a dead broker left jobs `pending` forever |

**Testing**

```bash
cd apps/api
pip install -r requirements-dev.txt
pytest                  # 130 tests, ~30s
ruff check app agents tests
```

Tests run against a real SQLite database rather than mocks — the rules above are enforced in SQL `WHERE` clauses, so a mocked session would prove nothing. The full schema builds on SQLite because `JSONColumn` and the `Vector` column declare SQLite variants (`app/models/base.py`); Postgres still gets real `JSONB` and `VECTOR`. `tests/test_migration_parity.py` compiles the migration to DDL offline and diffs it against the models, which is the safety net for the hand-maintained parts of `92f0cac4322f_initial_schema.py`.

Anything needing real Postgres (pgvector similarity, native ENUM behaviour) is marked `@pytest.mark.postgres`.

## Local development

Requires Docker (recommended) or a local Python 3.12 + Node 20 + PostgreSQL 16 + Redis setup.

### With Docker

```bash
cp .env.example .env      # fill in SECRET_KEY, ENCRYPTION_KEY, and at least one LLM key
                          # (LLM_PROVIDER picks anthropic/openai for drafts;
                          #  OPENAI_API_KEY is also required for RAG embeddings)
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

Python **3.12** is required — the code uses `X | None` annotations without `from __future__ import annotations`, so it will not import on 3.9.

```bash
# Backend
cd apps/api
python -m venv .venv && .venv/Scripts/activate   # or `source .venv/bin/activate`
pip install -r requirements-dev.txt              # includes runtime deps
cp .env.example .env                             # documents every setting
alembic upgrade head
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
- **Sales CRM:** `leads` (status enum, `external_crm_id`), `deals` (stage enum, `amount`/`expected_close_date`, 1 Lead : N Deal), `contacts`, `deal_outcomes`, `crm_activities`, `notes`, `meetings`
- **Marketing + Outreach:** `campaigns`, `campaign_templates`, `audience_segments`, `email_drafts` (Gate 2), `sent_emails`, `replies`
- **AI Results:** `ai_research_reports`, `lead_scores`, `buying_signals`, `icp_scores`, `reply_intent_results`, `revenue_forecasts`, `jobs`, `ai_interaction_logs`, `model_registry_entries`
- **RAG:** `knowledge_documents`, `knowledge_chunks`, `knowledge_embeddings` (pgvector), `rag_retrieval_logs`
- **Production Support:** `integrations`, `integration_sync_logs`, `audit_logs`, `billing_subscriptions`, `usage_records`

Every business table carries `company_id` (multi-tenant isolation); AI-output tables are append-only history carrying `model_name`/`model_version`/`confidence`/`explanation`. See `CLAUDE.md` → "Database Schema" for the design rationale.

## Frontend (Phase 6)

`apps/web` — **Next.js 14 App Router · TypeScript · Tailwind · Zustand**. Built mock-first per the plan: each page renders against local mock data with the real `/api/v1` endpoint annotated at the data site, ready to swap in.

- **App shell** — `app/(app)/layout.tsx` renders the sidebar + topbar around every authenticated page. The sidebar is **role-aware** (`lib/auth.ts::canAccess`) and `middleware.ts` redirects by the cookie's `role` claim — both convenience only; the real gate is the backend `require_role()`.
- **Auth** (`app/(auth)/*`) — login, signup, forgot/reset password, verify email — wired to the real `/auth/*` endpoints.
- **Pages across all five workspaces** — Dashboard, Leads (list + **tabbed** Lead Details: Overview · AI Research · Activities · Timeline · Emails · Meetings · Notes), Pipeline (deals board), Outreach Center (Gate 2 approve/send), Meetings, Campaign Studio, Analytics (KPIs + revenue-forecast chart), Team, and Settings → Integrations / Billing.
- **Data flow** — `lib/api.ts` (axios, httpOnly-cookie auth via `withCredentials`, same-origin `/api` proxied to the backend by `next.config.mjs`, response interceptor that unwraps the `{success, data}` envelope) → service (`lib/*Api.ts`) → hook (`hooks/use*.ts`) → page. **Leads is wired to live data**; the rest are mock pending the same treatment.
- **State & access** — global state is Zustand (`authStore`, `uiStore`); local state is `useState`. Route protection is two-layer (`middleware.ts` server redirect + a client backstop in the app layout), both deriving allowed routes from one list (`lib/nav.ts`). Privileged actions use `<RequireRole roles={[…]}>` (e.g. Gate 2 approve/send = Sales Exec only). All UI-side only — the backend `require_role()` is the real gate.

```bash
cd apps/web && npm install && npm run dev   # http://localhost:3000
```

The app is **mock-first**: `NEXT_PUBLIC_MOCK_ROLE` in `.env.local` seeds a fake user so every page renders without a backend (change the role — `admin` / `sales_manager` / `sales_executive` / `marketing` — to see RBAC). Remove it for real cookie auth, which needs the backend up (`docker compose up`) and a user (`POST /api/v1/auth/signup`). `npm run build` passes.

## AI agents (Phase 8)

Agents live in `apps/api/agents/`, one package each, and are **independently testable with mock input** — they take a plain payload and return a dict, never a database session. `ai_orchestrator.py` gathers their inputs, sequences them, and persists results.

**Module 1 — Research Agent** (`agents/research/`) is built. It is a pipeline, not a prompt:

```
payload → source_collector → derive claims → confidence → schema validation
```

Three design rules that will apply to every agent after it:

- **Evidence and inference are different types.** `recent_news` holds `Evidence{claim, source}`; `pain_points` and `sales_opportunities` hold `Hypothesis{statement, basis}`. A guess can't be rendered as a fact downstream because the shape differs — which matters, because these feed the Outreach Agent and pass Gate 2 into a customer's inbox. With nothing to cite, the agent returns an empty list rather than a plausible-sounding filler.
- **Confidence is evidence coverage, computed — never self-reported by a model.** An LLM's confidence is uncalibrated and looks authoritative, and this number is consumed by Lead Scoring, so a fabricated one would propagate into how a Sales Manager prioritises work.
- **Never fetch `Lead.website` without `validate_fetchable_url()`.** It's user input, and a fetched page gets persisted and shown to a user — so an unguarded fetch is an exfiltration channel, not just SSRF. The guard resolves DNS and rejects private/loopback/link-local addresses, because a public-looking hostname can resolve to `127.0.0.1`.

The current implementation reasons over lead data and CRM notes only. Swapping in the LLM replaces the `_derive_*` methods; the contract, confidence maths, and validation stay put. `prompts.py` holds the instruction it will use.

**Module 2 — Buying Signal Detection** (`agents/buying_signals/`) answers "is something happening here *now*", as opposed to ICP matching's "are they a good fit". It reads **only** the evidenced half of the research report, which is the direct payoff of Module 1's type split — scanning inferred pain points would make the pipeline circular:

```
industry = "Healthcare"  →  Research infers "High patient inquiry volume"
                         →  Signals matches "inquiry volume"
                         →  Lead Scoring raises the score
```

One industry field would become a confident claim that a company is ready to buy. So a lead with no news and no CRM notes yields **zero signals**, which is the honest answer. Matching is word-boundary anchored with a negation list, because `"hiring"` matches `"hiring freeze"` — the opposite signal.

**Module 3 — ICP Matching** (`agents/icp_matching/`) answers "should we sell to this company at all", scoring industry, size, region and need separately so a client renders each without parsing. Two rules:

- **The ICP belongs to the tenant** (`Company.icp_config`). A German logistics vendor and an Indian health-tech startup target different customers, so a hardcoded target market would tell every customer their best leads are whichever match someone else's business. Defaults apply until a workspace configures its own; weights are normalised so custom values can't push scores past 100.
- **"Unknown" ≠ "bad fit".** A missing attribute scores neutral and lowers *confidence*; only a known mismatch scores low. Otherwise reps deprioritise every lead nobody has researched yet — a lead with no data outranks one we know is wrong.

Need is scored from buying signals rather than research pain points, because those are inferred *from* industry — scoring both would let one field drive half the ICP score while looking like two independent confirmations.

**Module 4 — Embeddings** (`agents/embeddings/`) gives the system semantic comparison: `"patient support automation"` and `"handling hospital customer queries"` share almost no keywords but nearly the same meaning. **OpenAI `text-embedding-3-small`, 1536 dimensions**, matching the existing pgvector column — a local model (MiniLM, 384-d) would keep tenant documents in-house but adds torch to every image; `embedding_model` is stored per row so that swap stays possible.

- **One model platform-wide.** Vectors from different models aren't comparable even at the same width — cosine similarity between them returns a meaningless number.
- **Failure is loud.** A missing key raises rather than returning a zero vector, which is a valid point in the space that matches nothing or everything. The RAG retriever reports `available=False` so *"we couldn't look"* stays distinguishable from *"we looked and found nothing"* — conflating them silently downgrades a grounded email.
- **A relevance floor is what makes `NO_VERIFIED_PROOF` real.** Similarity always returns a closest match; without a threshold the retriever hands back the least-irrelevant document and outreach cites it as proof.

**Module 5 — Lead Scoring** (`agents/lead_scoring/`) ranks a rep's queue. Gradient-boosted trees on scikit-learn rather than a PyTorch MLP: ~45k rows of mostly-categorical tabular data is where GBDTs win, tree attribution feeds the explainability module directly, and torch would add 800MB–2.5GB to every image.

```bash
python -m agents.lead_scoring.train --db ../../data/crm.db
```

**Measured on a temporal holdout: ROC-AUC 0.62, lift 1.48× in the top decile** — top-decile leads convert at 45% against a 30.5% base rate. That's the honest headline, not a per-lead "94% likely". Confidence is derived from the holdout AUC, so a weak model can't present as a certain one.

- **Only cold-lead features.** `stage` separates the label perfectly in the training data, so a model using it reports ~1.00 AUC and has learned to read the answer. Engagement counts (meetings held, emails opened) are worse than useless: they're zero for every lead a rep is deciding whether to call, so the model never sees the distribution it must predict on — it just re-encodes the reps' existing prioritisation as truth.
- **Composed, not fused.** `historical_fit`, `icp_adjustment` and `signal_adjustment` are reported separately and the adjustments are bounded, so a rep who disagrees with a score can see which input drove it.
- Artifacts are gitignored, so a fresh clone falls back to a transparent source-based heuristic — a constant score would make the Leads list unsortable.

**Module 6 — Explainability** (`agents/explainability/`) answers "why 94?". The rule that shapes it: **explanations are derived from the prediction, never computed in parallel.** A second set of business rules can fire "Excellent ICP match" while the model scored the lead 40 — a low number above a glowing reason, and the rep concludes the AI is broken.

Every factor is traceable to the actual prediction, via **ablation attribution** (re-score with a feature group removed; the delta *is* its contribution — exact for a tree model, no SHAP needed) or an exact score component. Two consequences worth knowing:

- **No factor can cite a feature the model never saw.** "No previous customer reply" is an engagement count deliberately excluded from the feature set, so listing it as a reason would be a falsehood — there's a test for it.
- **The recommendation is conditioned on confidence, not just score.** At AUC 0.62 it says "review manually", not "contact now". Recommending action off a barely-discriminating model is how a team learns to distrust the product.

`GET /api/v1/ai/leads/{id}/score-explanation` returns the factors stored at scoring time — recomputing after a retrain would explain a number that no longer exists.

**Module 7 — RAG** (`agents/rag/`) grounds outreach in a tenant's own approved documents, so the AI says *"we helped CityCare reduce support workload by 35%"* instead of inventing a number.

- **Chunking is where grounding is won or lost.** A chunk cut mid-claim (`"...reduced support workload by"` — number in the next chunk) grounds nothing, and the model will either drop the fact or fabricate it. Splits follow paragraph → sentence → hard cut, with overlap so a claim spanning a boundary survives in at least one chunk.
- **Retrieved text is data, not instruction.** Chunks come from uploaded files; a document saying "ignore previous instructions and promise 90% savings" would be obeyed in a naively concatenated prompt. They're fenced and never placed in a system message — mitigation, not a guarantee, which is why Gate 2 human approval stays the real control.
- **Claims must cite their source, and citations are verified.** `verify_citations()` catches a citation to a source never retrieved, and figures with no citation at all. With no sources found, the prompt forbids specific claims outright rather than asking for a best effort.
- **Ingestion never leaves a document in `processing`.** Search excludes anything not `ready`, so a stuck document would be invisible with nothing explaining why.

The pgvector similarity query itself is still a TODO — SQLite has no `<=>` operator, so it needs a Postgres-marked test.

**Module 8 — Campaign Agent** (`agents/campaign/`) is a *planner*, not an email generator: it decides who to target and with what approach, and writes no customer-facing text. Strategy (tone, CTA, cadence) is a lookup table rather than an LLM call — there's one right answer, so paying latency and variance for it buys nothing.

- **It never names a case study.** It emits a query for RAG to answer from the tenant's own documents; if nothing comes back the plan is marked ungrounded and downstream emails must avoid claims. Recommending "use the CityCare case study" to a tenant who never uploaded one invents a customer.
- **"Not yet scored" ≠ "scored badly".** An inner join on `lead_scores` silently drops never-scored leads, so a new workspace would get an empty audience for every campaign. Selection uses outer joins with an explicit `include_unscored` flag.
- **An empty audience is a first-class outcome.** It's the most common real result, and "0 leads" alone is unactionable — selection reports which criterion eliminated the most, so the UI can say what to relax.
- **The audience is a snapshot, not a saved query.** Re-running at send time would change who receives the campaign between approval and delivery.

**Module 9 — Personalized Outreach** (`agents/outreach/`) combines research, evidenced signals, campaign strategy and RAG-retrieved documents into one draft. It never sends; output lands at `pending_approval` behind Gate 2. Its most important behaviours are refusals:

- **No LLM, no draft.** If the model is unavailable or returns malformed JSON, the job fails. A template with the company name substituted in *is* the generic email this feature replaces.
- **No proof, no claims.** With nothing retrieved, the prompt forbids specific claims rather than asking for a best effort.
- **The validator catches structure, not untruth.** Uncited figures, citations to sources never retrieved, unfilled `{{placeholders}}`, and guarantee/risk-free language all block. But a sentence can cite `[S1]` correctly and still misrepresent it — nothing automated closes that gap, which is why Gate 2 is the control and nothing in the validator can advance a draft's status.
- **Every draft is reproducible.** `llm_model`, `prompt_version` and `rag_sources` are stored, because a complaint about a claim must be traceable to the model, instructions *and* documents that produced it — and prompt wording moves output as much as a model swap does.

The prompt labels evidence and inference separately, so an inferred pain point gets hedged rather than asserted — Module 1's type split reaching the point where it actually matters: a customer's inbox.

**Module 10 — Reply Intent** (`agents/reply_intent/`) turns a customer's reply into a label and a suggested next step. The load-bearing part is not the classifier — it is `preprocess.py`:

```
No thanks.

On Tue, 4 Aug 2026 at 09:12, Priya <priya@acme.com> wrote:
> Hi Ravi, would you be open to a quick demo? Happy to share pricing too.
```

Classify the raw body and `demo`, `pricing` and `calendar` all match — **our own outreach copy**. A flat refusal becomes `meeting_request` → `schedule_meeting`. So the quoted thread, signature and confidentiality footer are stripped before anything else runs. (That footer matters too: the standard wording is "if you have received this in error please *call* the sender".)

- **Precedence encodes cost asymmetries.** `out_of_office` pre-empts everything — an absence notice is not a reply, and "for urgent matters call Priya" fires every positive rule. `unsubscribe` outranks even a warm reply and is never downgraded by low confidence: suppressing one lead in error costs a lead, continuing to email someone who asked you to stop is a compliance matter.
- **Negation is clause-scoped.** "We're not looking for a demo" and "I don't need pricing" are ordinary weekly replies where the keyword means its opposite — but a plain look-back window breaks "I'm not sure I follow, but let's book a demo", which *is* a booking.
- **`suggested_action` is a suggestion.** The course workflow has "CRM status updated" follow automatically; that step is deliberately not implemented. `mark_closed_lost` here comes from a regex reading of someone's phrasing, and a lead auto-closed by a false positive vanishes from every list a rep works from with no prompt that a decision was made.

**Module 11 — Meeting Scheduler** (`agents/meeting_scheduler/`) proposes bookable slots. "Working hours 10–6" is not a fact until you say *where*: every datetime here is stored in UTC, so treating that window as UTC offers an Asia/Kolkata rep meetings from 15:30 to 23:30 local. Hours are evaluated in a named IANA zone held per-tenant (`Company.scheduling_config`), and slot iteration runs over **local** calendar days — 03:00 IST Tuesday is 21:30 UTC *Monday*, so walking UTC days offers the customer the wrong weekday.

- **"Prefer the earliest slot" needs three guards.** Taken literally it proposes a demo fifteen minutes out. `min_notice_minutes` (120), `slot_spread_minutes` (10:00 and 10:30 is the same slot twice, not a choice), and a per-day cap so one free morning doesn't consume the whole list.
- **Preferred days are honoured strictly** — an empty list plus the reason, never a quiet widening to a day nobody asked for. `limiting_constraint` is ranked by specificity rather than count, or a customer who asks for Tuesday and finds it booked gets told to "widen preferred_days".
- **It proposes; it never books.** `POST /meetings` stays the human step and re-runs the clash check, because slots are a snapshot the rep may invalidate before the customer accepts. `availability_sources: ["internal"]` is on every response until the calendar integration lands — a Google standup is invisible to us.

**Module 12 — Revenue Forecasting** (`agents/forecasting/`) is **weighted pipeline, not the monthly regression the course specifies — and that's a measurement, not an opinion.** The historical CRM yields 43 monthly rows. `train.py` fits and backtests both on a 12-month holdout:

| method | MAPE | R² |
|---|---|---|
| **weighted pipeline** | **0.161** | **0.35** |
| naive (last month) | 0.220 | −0.06 |
| monthly GBDT | 0.241 | **−0.54** |

R² of −0.54 means the trees are worse than predicting the mean. Tree ensembles predict the mean of a training leaf, so they cannot extrapolate — a growing pipeline is forecast flat at the historical maximum, confidently low, every month.

- **`P(win | stage)` is not measurable from this data.** Closed deals keep only their *current* stage; there is no stage history. Anything claiming to have measured it is reading `probability` or `forecast_category`, which are set post-outcome. So stage *ordering* is a business prior and the *level* is rescaled onto the measured overall win rate — recorded as `prior_shape_measured_level` in the artifact.
- **Confidence is `1 − backtested MAPE`**, reduced for missing deal amounts, thin stage support and forecast horizon. A fresh clone has no artifacts and reports 0.25 with a warning rather than presenting guessed weights as measured ones.
- **Overdue deals are excluded and reported.** Counting open deals whose close date already passed is the largest source of optimistic bias in hand-built forecasts.
- **One forecast row per (period, currency).** Adding an INR deal to a USD deal produces a figure that is not money, and there is no FX source here.

**Module 13 — Feedback Learning** (`agents/feedback_learning/`) closes the loop, and its first act was to make the loop possible at all: `update_draft` overwrote `EmailDraft.body` in place, so the first human keystroke destroyed what the AI wrote and **every edit-distance metric would have compared a draft against itself**, reporting a flattering 0.0 forever. `ai_original_subject`/`ai_original_body` are snapshotted on first edit.

- **Every metric is measured or absent.** The course dashboard shows "Research Accuracy 92%"; nothing here can compute that — there is no ground truth for whether a report was *correct*, only whether a human liked it. So research/ICP/scoring report **satisfaction**, and every metric carries `available`, `sample_size` and an `unavailable_reason`. 100% acceptance across two drafts reports as insufficient data.
- **Reply-intent accuracy is a lower bound and says so** — people correct errors far more readily than they confirm successes, so the reviewed sample is biased.
- **Forecast error is the one metric with real ground truth**, and it skips periods still running. It is the payoff for making `revenue_forecasts` append-only.
- **`FeedbackRecord` stores only what is not derivable.** `edited` / `meeting_booked` / `deal_closed` already exist as first-class facts; a copy goes stale the moment a meeting is cancelled — and this is the table a retraining run reads, so that is a mislabelled training example, not a display bug.
- **Retraining is never triggered.** Readiness is reported against sample thresholds and stops. This feedback is a biased sample of a system humans already steer; retraining on it without a held-out evaluation teaches the model to agree with the reps and calls that an improvement.

## Multi-agent system (Phase 9)

Phase 8 built thirteen agents. Phase 9 makes them a system.

**The architecture is data, and tests hold it to the code.** `agents/registry.py` declares every agent — role, inputs, outputs, determinism class, human gate, and the dotted path of whatever invokes it. `tests/test_agent_registry.py` asserts every entry point imports, every `invoked_by` resolves to a real callable, and — the guard that matters — **the declared workflow matches the `agent_name` sequence `AIInteractionLog` actually records at runtime**. A hand-maintained architecture map gets read as documentation, so a drifted one is worse than none. Served at `GET /api/v1/ai/agents`.

That map immediately found three agents that were built, tested, and reachable from nowhere — `campaign`, `outreach`, `embeddings`. All three are wired now; `unwired()` is empty and pinned empty by test.

**The supervisor plans; it does not perform.** `agents/supervisor/` has no database handle, imports no other agent, and returns a plan rather than a result — asserted by a test that reads the module source. `AIOrchestrator` executes the plan. That split is what makes "should this step run?" assertable without a database, a broker, or an LLM key.

- **Staleness tolerance belongs to the consumer.** `research` appears in two workflows with two TTLs: `lead_intelligence` reuses a report up to 30 days (it feeds a ranking), `outreach_draft` only 7 (it becomes "I noticed you recently expanded" in a customer's inbox — a claim about *when*). When a report is reused, its age is written into the draft's explanation.
- **Age is not the only way a result goes stale.** An ICP score computed before the tenant edited `icp_config` is not old, it is *wrong*.
- **Payload scope is the memory-permission model.** Each step declares the context keys it may receive, and undeclared context **raises** rather than being filtered — silently dropping a key turns a wiring mistake into an agent running on incomplete input.

**Every agent task is recorded, including the ones that fail.** `ai_interaction_logs` used to be written *after* an agent returned, at nine call sites — so a raising agent left nothing behind, and the table built for auditing agent calls was blind to the only case anyone opens it for. Every call now goes through `AIOrchestrator.run_agent()`, which records status, error, timings, attempt and a `run_id` whether it works or not, and commits the failure row immediately (the surrounding workflow is about to roll back). Transient failures retry, permanent ones don't — classification walks the `__cause__` chain and denies by default. `GET /api/v1/ai/interactions?run_id=` replays a run in order.

**CrewAI is implemented and cannot be installed here.** `agents/crew/` is a real `Crew` over the existing agents, guarded so the API boots without the dependency and only `POST /ai/leads/{id}/crew-run` returns 503. Measured 2026-08-06: `pip install crewai` upgraded `starlette` past what `fastapi 0.111.0` allows and **every route failed at import**. `requirements-crewai.txt` documents the conflict and the two ways out. Two deviations from the standard skeleton:

- **Crew agents get tools, not personalities.** `Agent(role=…, goal=…, backstory=…)` with no tools means an LLM *produces* the "lead intelligence report" — so the lead score would come from a language model's impression instead of the trained model, and the email would skip the validator.
- **Two crews, split at the human gate.** A single crew running research → intelligence → outreach drafts an email for a lead no manager has assigned, automating straight through Gate 1.

## Current status

**Phases 1–8 complete. Phase 9 Modules 1–4 done.** Business understanding, product design, system architecture, database design, API design, the Next.js frontend, the backend, all thirteen AI agents, and the multi-agent layer around them. **828 backend tests** (`cd apps/api && pytest`, ~60s), `ruff check app/ agents/` clean.

The workflow runs end to end on the backend: lead → research → signals → ICP → scoring → **Gate 1** → campaign → RAG → outreach draft → **Gate 2** → send → reply intent → meeting slots → forecast → feedback. Both gates are enforced in service-layer state machines with tests, not in the UI.

Known gaps, tracked rather than silently assumed:

**Real, and blocking for production**
- **`POST /outreach/replies/webhook` has no signature verification** (`TODO(security)`). Anyone who guesses a `sent_email_id` can inject a fake customer reply, which then feeds the Reply Intent Agent. This is the most serious open item.
- **Logout does not revoke.** No Redis denylist, so a stolen token stays valid until it expires; clearing cookies only ends the session in that browser.
- **The pgvector similarity query is still a TODO** (`agents/rag/retriever.py`). Ingestion is wired end to end — upload → chunk → embed → store, with per-row `embedding_model` — but retrieval returns no chunks, so outreach currently takes its ungrounded path. SQLite has no `<=>` operator, so finishing it needs a `@pytest.mark.postgres` test.
- **The migration chain has never been applied to a real database.** It is verified by compiling to DDL offline and diffing against `Base.metadata` (`tests/test_migration_parity.py`), which catches column, enum-member and ordering drift — but no Postgres exists on this machine.

**Integrations still stubbed (expected)**
- `CRMAdapter` subclasses (Salesforce/HubSpot/Zoho) raise `NotImplementedError`; email delivery and calendar sync are stubs. `sent_emails` records the intent to send; nothing leaves the building.
- The Meeting Scheduler computes availability from **this system's** meetings only — `availability_sources: ["internal"]` says so on every response.
- Research **does** fetch live now (TinyFish search + fetch). With no `TINYFISH_API_KEY` it degrades to lead data and CRM notes, reports `research-rules-v1` instead of `research-web-v1`, and scores lower coverage — a thinner report, not a broken one.
- Email verification and password reset validate input but perform no action.
- Campaign analytics aggregation is pending the outreach tracking pipeline.

**Model quality, stated plainly**
- Lead scoring is **ROC-AUC 0.62, 1.48× top-decile lift** — real and useful for ranking, not a per-lead probability. Its `recommend()` says "review manually" at this confidence rather than "contact now".
- Revenue forecasting backtests at **MAPE 0.161** on 12 held-out months; confidence is derived from that number, not chosen.
- Artifacts are gitignored, so a fresh clone falls back to documented heuristics and reports `calibration_source: "default"` rather than presenting guessed weights as measured.

**Decisions deliberately left open**
- `Lead.status` still carries deal-stage values (`demo_scheduled`, `proposal`, `closed_won`) that belong on `Deal.stage` after the Phase 5 Module 5 reversal; it should reduce to a lead lifecycle. Deferred because it changes an enum the frontend filters on.
- Whether ML models train globally or per-tenant (`ModelRegistryEntry` assumes one shared model per `model_name`).
- `Job` is keyed to a nullable `lead_id`, which fits company-wide forecast jobs poorly.
- `system_logs` is intentionally **not** a DB table — generic application logging belongs in an aggregator, not primary Postgres.
- **CrewAI cannot share this environment.** It needs `starlette>=0.49`, `pydantic>=2.11.9` and `openai>=2.0`; `fastapi 0.111.0` pins `starlette<0.38`. Either run the crew from a separate service against the same database, or do a deliberate web-stack upgrade with the existing suite as the acceptance check — `openai` 1.x → 2.x changes client APIs the Outreach and Embeddings agents use.

**Frontend**
- Mock-first: only the Leads list is wired to the live API. The Phase 8/9 endpoints (AI quality, agent map, crew runs, forecasts, reply intents, knowledge base) have no UI yet. A few secondary routes (`crm`, `forecast`, `campaigns/[id]`, `outreach/{drafts,sent,…}`, `settings/{ai-config,audit-logs}`) are still placeholder pages.

**Test suite note**
- ~828 tests each build the full schema in a fresh in-memory SQLite database (`conftest.py`), which is what keeps isolation and state-machine tests honest but now dominates runtime. Worth revisiting before the suite doubles again.

## Repository layout

See [`FOLDER_STRUCTURE.md`](./FOLDER_STRUCTURE.md) for the full annotated tree.