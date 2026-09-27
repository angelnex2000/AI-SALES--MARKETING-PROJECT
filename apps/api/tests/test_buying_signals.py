"""Buying Signal Agent: provenance, negation, confidence scaling, persistence.

The rule under test throughout: a buying signal is a claim about *timing*, so
it must come from something that actually happened. Inferred pain points are
not evidence.
"""

import pytest
from sqlalchemy import text

from agents.buying_signals.agent import MODEL_VERSION, BuyingSignalAgent
from agents.buying_signals.signals import RULES, SignalType, is_negated


def research(evidence=None, hypotheses=None, confidence=1.0) -> dict:
    """A research-agent-shaped payload."""

    return {
        "recent_news": evidence or [],
        "pain_points": hypotheses or [],
        "sales_opportunities": [],
        "confidence": confidence,
    }


async def detect(**kwargs) -> dict:
    return await BuyingSignalAgent().run({"research": research(**kwargs)})


class TestProvenance:
    """The central rule — signals come from evidence, never from inference."""

    async def test_evidence_produces_a_signal(self):
        out = await detect(
            evidence=[{"claim": "Announced expansion into three new markets", "source": "crm_notes"}]
        )
        assert [s["signal_type"] for s in out["signals"]] == [SignalType.EXPANSION.value]

    async def test_inferred_pain_points_produce_nothing(self):
        """The circularity this prevents: industry=Healthcare makes Research
        infer "High patient inquiry volume", which contains a support-load
        phrase. Scanning it would turn one industry field into a confident
        claim that the company is ready to buy."""

        out = await detect(
            hypotheses=[
                {
                    "statement": "High patient inquiry volume",
                    "basis": "industry = Healthcare",
                }
            ]
        )
        assert out["signals"] == []

    async def test_explanation_says_why_nothing_fired(self):
        out = await detect()
        assert "no evidenced claims" in out["explanation"]
        assert "assumption" in out["explanation"]

    async def test_signal_cites_the_phrase_and_source_it_came_from(self):
        out = await detect(
            evidence=[{"claim": "Raised a Series B round", "source": "https://news.example.com/x"}]
        )
        signal = out["signals"][0]
        assert signal["matched_phrase"].lower() in "raised a series b round".lower()
        assert signal["evidence_source"] == "https://news.example.com/x"
        assert signal["source_url"] == "https://news.example.com/x"

    async def test_non_url_source_is_not_stored_as_a_url(self):
        out = await detect(evidence=[{"claim": "Expanding to Pune", "source": "crm_notes"}])
        assert out["signals"][0]["source_url"] is None


class TestNegation:
    """A phrase can contain a keyword and mean the opposite."""

    @pytest.mark.parametrize(
        "claim",
        [
            "Announced a hiring freeze",
            "Company confirmed layoffs this quarter",
            "Expansion plans postponed",
            "Cost-cutting programme underway",
        ],
    )
    async def test_negated_claims_produce_no_signal(self, claim):
        out = await detect(evidence=[{"claim": claim, "source": "news"}])
        assert out["signals"] == [], f"{claim!r} should not read as a buying signal"

    def test_negation_helper(self):
        assert is_negated("hiring freeze announced")
        assert not is_negated("hiring 40 engineers")


class TestWordBoundaries:
    """Substring matching produces false positives that push leads up a queue
    for no reason."""

    @pytest.mark.parametrize(
        "claim",
        ["Processing customer refunding requests", "The feature is unsupported on mobile"],
    )
    async def test_substrings_do_not_match(self, claim):
        out = await detect(evidence=[{"claim": claim, "source": "news"}])
        assert out["signals"] == [], f"{claim!r} matched on a substring"

    async def test_real_word_still_matches(self):
        out = await detect(evidence=[{"claim": "Closed a funding round", "source": "news"}])
        assert out["signals"][0]["signal_type"] == SignalType.FUNDING.value


class TestConfidence:
    async def test_signal_cannot_exceed_the_report_it_came_from(self):
        thin = await detect(
            evidence=[{"claim": "Announced expansion", "source": "news"}], confidence=0.2
        )
        rich = await detect(
            evidence=[{"claim": "Announced expansion", "source": "news"}], confidence=1.0
        )
        assert thin["signals"][0]["confidence"] < rich["signals"][0]["confidence"]

    async def test_confidence_is_bounded(self):
        out = await detect(
            evidence=[{"claim": "Raised funding and announced expansion", "source": "news"}],
            confidence=1.0,
        )
        assert all(0.0 <= s["confidence"] <= 1.0 for s in out["signals"])

    async def test_run_confidence_is_the_strongest_signal(self):
        out = await detect(
            evidence=[{"claim": "Raised a funding round and is hiring", "source": "news"}]
        )
        assert out["confidence"] == max(s["confidence"] for s in out["signals"])

    async def test_no_signals_means_zero_confidence(self):
        assert (await detect())["confidence"] == 0.0


class TestDeduplication:
    async def test_one_signal_per_type_per_run(self):
        """Three news items about expansion is one expansion signal."""

        out = await detect(
            evidence=[
                {"claim": "Expansion into Kerala", "source": "news"},
                {"claim": "Expanding the Pune office", "source": "news"},
                {"claim": "New branch opening in Delhi", "source": "news"},
            ]
        )
        assert len(out["signals"]) == 1

    async def test_distinct_types_all_reported(self):
        out = await detect(
            evidence=[
                {"claim": "Raised a Series B", "source": "news"},
                {"claim": "Hiring 40 engineers", "source": "news"},
            ]
        )
        assert {s["signal_type"] for s in out["signals"]} == {
            SignalType.FUNDING.value,
            SignalType.HIRING.value,
        }


class TestRuleTable:
    def test_every_rule_has_a_usable_confidence(self):
        assert all(0.0 < r.base_confidence <= 1.0 for r in RULES)

    def test_signal_types_are_unique_across_rules(self):
        kinds = [r.signal_type for r in RULES]
        assert len(kinds) == len(set(kinds))

    async def test_model_version_is_reported(self):
        assert (await detect())["model_version"] == MODEL_VERSION


class TestPersistence:
    """The orchestrator writes signals; they were previously generated and
    logged but never stored, so the AI Research tab always showed none."""

    async def _run_pipeline(self, db, tenant, note_body: str | None = None):
        from app.models.crm import Note
        from app.models.job import Job, JobStatus
        from app.models.lead import Lead
        from app.services.ai_orchestrator import AIOrchestrator

        if note_body:
            db.add(
                Note(
                    company_id=tenant.company_id,
                    lead_id=tenant.lead_id,
                    author_id=tenant.exec_id,
                    body=note_body,
                )
            )
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

    async def test_signals_are_written_to_the_table(self, db, tenant):
        await self._run_pipeline(db, tenant, "They confirmed expansion into two new cities")
        rows = (
            await db.execute(text("SELECT signal_type, confidence, explanation FROM buying_signals"))
        ).all()
        assert rows, "expansion in a CRM note should produce a stored signal"
        assert rows[0][0] == SignalType.EXPANSION.value
        assert "Matched" in rows[0][2], "each row explains the phrase it matched"

    async def test_no_evidence_writes_no_rows(self, db, tenant):
        await self._run_pipeline(db, tenant)
        count = (await db.execute(text("SELECT count(*) FROM buying_signals"))).scalar()
        assert count == 0

    async def test_endpoint_returns_latest_per_type_not_every_run(self, client, db, tenant):
        note = "They confirmed expansion into two new cities"
        await self._run_pipeline(db, tenant, note)
        await self._run_pipeline(db, tenant)

        stored = (await db.execute(text("SELECT count(*) FROM buying_signals"))).scalar()
        assert stored >= 2, "history is append-only, so re-running adds rows"

        r = client.get(
            f"/api/v1/ai/leads/{tenant.lead_id}/buying-signals",
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 200, r.text
        kinds = [s["signal_type"] for s in r.json()["data"]]
        assert len(kinds) == len(set(kinds)), "a rep must not see the same signal twice"

    async def test_history_flag_returns_the_full_trail(self, client, db, tenant):
        note = "They confirmed expansion into two new cities"
        await self._run_pipeline(db, tenant, note)
        await self._run_pipeline(db, tenant, note)

        current = client.get(
            f"/api/v1/ai/leads/{tenant.lead_id}/buying-signals",
            headers=tenant.headers("sales_executive"),
        ).json()["data"]
        full = client.get(
            f"/api/v1/ai/leads/{tenant.lead_id}/buying-signals?history=true",
            headers=tenant.headers("sales_executive"),
        ).json()["data"]
        assert len(full) > len(current)
