"""The agent registry must describe the code, not aspire to it.

A hand-maintained architecture map is read as documentation, so one that has
drifted is worse than none. These tests are what stop `agents/registry.py`
becoming a wish list: every entry point must import, every declared
`invoked_by` must resolve to a real callable, and the declared workflow must
match the agent sequence the orchestrator actually logs at runtime.
"""

import importlib

import pytest
from sqlalchemy import text

from agents.base import BaseAgent
from agents.registry import (
    AGENTS,
    AGENTS_BY_NAME,
    WORKFLOWS_BY_NAME,
    describe,
    unwired,
)

V1 = "/api/v1"

# Agents that are built and tested but that no code path in `app/` reaches.
# Pinned so that wiring one without updating the registry fails, and so that
# the list cannot silently grow.
# Empty since Phase 9: every agent is reachable from a code path in `app/`.
# Pinned in both directions, so an agent that becomes unreachable fails here
# rather than quietly becoming decoration in the AI Center.
KNOWN_UNWIRED: set[str] = set()


def resolve(path: str):
    """Resolve a dotted path that may end in `Class.method`."""

    parts = path.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:split]))
        except ModuleNotFoundError:
            continue
        target = module
        for attribute in parts[split:]:
            target = getattr(target, attribute)
        return target
    raise ModuleNotFoundError(path)


class TestEntryPoints:
    @pytest.mark.parametrize("spec", AGENTS, ids=lambda s: s.name)
    def test_every_declared_agent_imports(self, spec):
        module = importlib.import_module(spec.module)
        assert hasattr(module, spec.entry_class), f"{spec.module}.{spec.entry_class} missing"

    @pytest.mark.parametrize("spec", AGENTS, ids=lambda s: s.name)
    def test_every_agent_implements_the_shared_interface(self, spec):
        """`BaseAgent.run(dict) -> dict` is what makes the brief's "structured
        JSON, not only text" true — and what lets a supervisor sequence them
        without knowing what any of them do."""

        entry = getattr(importlib.import_module(spec.module), spec.entry_class)
        assert issubclass(entry, BaseAgent)
        assert callable(getattr(entry, "run", None))

    @pytest.mark.parametrize("spec", AGENTS, ids=lambda s: s.name)
    def test_declared_version_matches_the_module(self, spec):
        """A registry reporting a stale model version would misattribute every
        output row a reader traced back through it."""

        module = importlib.import_module(spec.module)
        declared_name = getattr(module, "MODEL_NAME", None)
        if declared_name is not None:
            assert declared_name == spec.name, f"{spec.module} calls itself {declared_name!r}"


class TestWiring:
    @pytest.mark.parametrize(
        "spec", [s for s in AGENTS if s.invoked_by], ids=lambda s: s.name
    )
    def test_invoked_by_resolves_to_a_real_callable(self, spec):
        assert callable(resolve(spec.invoked_by)), spec.invoked_by

    def test_unwired_agents_are_exactly_the_known_ones(self):
        """The honesty guard in both directions: wiring an agent without
        updating the registry fails here, and so does declaring one wired that
        isn't."""

        assert {spec.name for spec in unwired()} == KNOWN_UNWIRED

    def test_unwired_agents_say_so_in_their_notes(self):
        for spec in unwired():
            assert "UNWIRED" in spec.notes, f"{spec.name} is unreachable but does not say so"

    def test_the_outreach_gap_is_closed(self):
        """Module 1 recorded this as the largest hole in the Phase 9 workflow:
        the Gate 2 state machine was complete and tested but nothing produced a
        draft for it to gate. Module 2 wired it, and this asserts it stays
        wired — with the gate still declared, since a reachable outreach agent
        that lost its gate would be strictly worse than an unreachable one."""

        spec = AGENTS_BY_NAME["outreach"]
        assert spec.invoked_by is not None
        assert spec.human_gate == "gate_2_exec_approves_send"


class TestDeterminism:
    def test_exactly_one_agent_calls_a_language_model(self):
        """Not a coincidence — the one nondeterministic agent is the one whose
        output a human approves before it reaches a customer."""

        llm_agents = [spec.name for spec in AGENTS if spec.determinism == "llm"]
        assert llm_agents == ["outreach"]

    def test_the_llm_agent_is_human_gated(self):
        for spec in AGENTS:
            if spec.determinism == "llm":
                assert spec.human_gate is not None, spec.name

    def test_live_agents_are_labelled_as_such(self):
        """The Research Agent is deterministic logic over data that changes
        underneath it. Labelling it `rules` would tell a reader two reports
        differing is a bug, when the world simply moved."""

        assert AGENTS_BY_NAME["research"].determinism == "live"

    def test_scoring_is_gated_before_it_affects_assignment(self):
        assert AGENTS_BY_NAME["lead_scoring"].human_gate == "gate_1_manager_assigns"


class TestWorkflowDeclaration:
    def test_every_workflow_step_names_a_real_agent(self):
        for flow in WORKFLOWS_BY_NAME.values():
            for step in flow.steps:
                assert step.agent in AGENTS_BY_NAME, f"{flow.name} -> {step.agent}"

    def test_steps_only_read_from_earlier_steps(self):
        """The dependency order is the reason the sequence is fixed. A step
        reading a later one would be a cycle, not a workflow."""

        for flow in WORKFLOWS_BY_NAME.values():
            seen: set[str] = set()
            for step in flow.steps:
                assert set(step.reads) <= seen, f"{flow.name}: {step.agent} reads a later step"
                seen.add(step.agent)

    def test_the_intelligence_chain_stops_at_the_manager_gate(self):
        """Scoring is where automation ends and Gate 1 begins — the workflow
        must not run on into campaign or outreach behind a rep's back."""

        flow = WORKFLOWS_BY_NAME["lead_intelligence"]
        assert flow.steps[-1].agent == "lead_scoring"
        assert flow.ends_at == "gate_1_manager_assigns"

    async def test_the_declaration_matches_what_the_orchestrator_runs(self, db, tenant):
        """The test that stops the map drifting from the territory.

        `AIInteractionLog` records every agent call in order, so the declared
        workflow can be compared against what actually executed rather than
        against a reading of the method body.
        """

        from app.models.job import Job, JobStatus
        from app.models.lead import Lead
        from app.services.ai_orchestrator import AIOrchestrator

        lead = await db.get(Lead, tenant.lead_id)
        job = Job(
            company_id=tenant.company_id,
            job_type="lead_intelligence",
            lead_id=lead.id,
            created_by_user_id=tenant.exec_id,
            status=JobStatus.PENDING,
        )
        db.add(job)
        await db.commit()
        await AIOrchestrator(db).generate_lead_intelligence(lead=lead, job=job)

        logged = [
            row[0]
            for row in (
                await db.execute(
                    text("SELECT agent_name FROM ai_interaction_logs ORDER BY created_at, rowid")
                )
            ).all()
        ]
        declared = [step.agent for step in WORKFLOWS_BY_NAME["lead_intelligence"].steps]
        assert logged == declared


class TestAgentsEndpoint:
    def test_the_map_is_served(self, client, tenant):
        r = client.get(f"{V1}/ai/agents", headers=tenant.headers("admin"))
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert len(data["agents"]) == len(AGENTS)
        assert data["human_gates"] == ["gate_1_manager_assigns", "gate_2_exec_approves_send"]

    def test_unwired_agents_are_surfaced_not_hidden(self, client, tenant):
        """An AI Center listing twelve agents implies twelve working agents."""

        data = client.get(f"{V1}/ai/agents", headers=tenant.headers("admin")).json()["data"]
        assert set(data["unwired_agents"]) == KNOWN_UNWIRED
        assert all(a["wired"] is False for a in data["agents"] if a["name"] in KNOWN_UNWIRED)

    def test_sales_executives_cannot_read_the_architecture(self, client, tenant):
        assert (
            client.get(f"{V1}/ai/agents", headers=tenant.headers("sales_executive")).status_code
            == 403
        )

    def test_describe_is_json_serialisable(self):
        import json

        assert json.loads(json.dumps(describe()))["agents"]


class TestRerunEndpoint:
    """Until Phase 9 this created a job nothing dispatched — a spinner that
    never cleared once Phase 8 finished."""

    async def test_rerun_actually_dispatches(self, client, db, tenant, monkeypatch):
        calls: list[tuple] = []

        class _Task:
            def delay(self, *args):
                calls.append(args)

        monkeypatch.setattr("app.routers.ai.run_lead_intelligence", _Task())
        r = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/research",
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code in (200, 202), r.text
        assert calls, "the job must reach the worker, not sit pending forever"
        assert "research" in r.json()["message"]

    async def test_an_unknown_agent_is_404(self, client, tenant):
        r = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/telepathy",
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 404
        assert r.json()["error_code"] == "UNKNOWN_AGENT"

    async def test_the_catchall_does_not_shadow_its_siblings(self, client, db, tenant, monkeypatch):
        """`/leads/{id}/{agent}` is declared last for this reason; declared
        first it would swallow run-intelligence."""

        class _Task:
            def delay(self, *args):
                pass

        monkeypatch.setattr("app.routers.ai.run_lead_intelligence", _Task())
        r = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/run-intelligence",
            headers=tenant.headers("sales_manager"),
        )
        assert "Intelligence pipeline" in r.json()["message"]
