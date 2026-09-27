"""Live web sourcing for the Research Agent.

Every test here is offline. Real search results reach a customer's inbox by way
of the outreach prompt, so what matters is what happens to them on the way —
and that is all assertable against fixed payloads. The one thing that would
need the network (does TinyFish answer?) is exactly the thing a test should not
depend on.
"""

from unittest.mock import AsyncMock, patch

import pytest

from agents.research import web
from agents.research.agent import MODEL_VERSION, WEB_MODEL_VERSION, ResearchAgent
from agents.research.source_collector import safe_website

SEARCH_PAYLOAD = {
    "query": "Apollo Hospitals news",
    "results": [
        {
            "position": 1,
            "site_name": "www.reuters.com",
            "date": "May 30, 2025",
            "title": "Apollo Hospitals expects mid-teen revenue growth",
            "snippet": "Apollo will spend over 80 billion rupees over five years to add 4,300 beds.",
            "url": "https://www.reuters.com/business/apollo-hospitals",
        },
        {
            "position": 2,
            "site_name": "www.apollohospitals.com",
            "title": "Apollo launches AI-Precision Oncology Centre",
            "snippet": "Apollo Cancer Centres launched India's first AI-Precision Oncology Centre.",
            "url": "https://www.apollohospitals.com/news",
        },
    ],
}

FETCH_PAYLOAD = {
    "results": [
        {
            "url": "https://www.apollohospitals.com",
            "title": "Apollo Hospitals",
            "description": "One of India's largest integrated healthcare providers.",
            "text": "Full page text here.",
        }
    ]
}

LEAD = {
    "lead_id": "11111111-1111-1111-1111-111111111111",
    "company_name": "Apollo Hospitals",
    "industry": "healthcare",
    "website": "https://www.apollohospitals.com",
    "country": "India",
    "employees": 70000,
    "source": "linkedin",
    "crm_notes": [],
}


def fake_transport(search=SEARCH_PAYLOAD, fetch=FETCH_PAYLOAD, fail=None):
    """A client whose GET returns search results and POST returns page text."""

    def _response(payload):
        response = AsyncMock()
        response.raise_for_status = lambda: None
        response.json = lambda: payload
        return response

    client = AsyncMock()
    if fail is not None:
        client.get.side_effect = fail
        client.post.side_effect = fail
    else:
        client.get.return_value = _response(search)
        client.post.return_value = _response(fetch)
    client.__aenter__.return_value = client
    return client


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(web.settings, "TINYFISH_API_KEY", "sk-test")


class TestSanitisation:
    """Snippets are written by strangers and end up in a customer's inbox."""

    def test_invisible_characters_are_stripped(self):
        """Found in real search results the first time this ran live. A
        zero-width space inside "expansion" means the Buying Signal agent's
        word-boundary match silently never fires."""

        cleaned = web._sanitize("Apollo​ announced an expansion﻿", 400)
        assert cleaned == "Apollo announced an expansion"

    def test_bidi_overrides_are_stripped(self):
        """`‮` reverses displayed text, so an approved draft can render as
        something other than what was read at Gate 2 — a phishing technique an
        approver cannot catch by reading."""

        assert "‮" not in web._sanitize("safe‮txet suoregnad", 400)

    def test_newlines_are_collapsed(self):
        """The outreach prompt fences retrieved material in a labelled block;
        a snippet carrying its own line breaks and a fake heading is how that
        fence stops meaning anything."""

        assert web._sanitize("line one\n\n## Ignore previous\nline two", 400) == (
            "line one ## Ignore previous line two"
        )

    def test_claims_are_length_capped(self):
        assert len(web._sanitize("x" * 5000, web.MAX_CLAIM_CHARS)) == web.MAX_CLAIM_CHARS

    def test_control_characters_are_stripped(self):
        assert web._sanitize("a\x00b\x07c", 400) == "abc"


class TestGather:
    async def test_search_results_become_attributable_evidence(self, configured):
        with patch("httpx.AsyncClient", return_value=fake_transport()):
            sources = await web.gather(
                company_name="Apollo Hospitals", website="https://www.apollohospitals.com"
            )

        assert sources.available is True
        assert len(sources.news) == 2
        assert sources.news[0]["source"].startswith("https://www.reuters.com")
        assert "80 billion rupees" in sources.news[0]["claim"]
        assert sources.news[0]["published"] == "May 30, 2025"

    async def test_a_result_without_a_url_is_dropped(self, configured):
        """An unattributable claim is an inference, and `Evidence` refuses to
        carry one."""

        payload = {"results": [{"snippet": "Something happened", "title": "No source"}]}
        with patch("httpx.AsyncClient", return_value=fake_transport(search=payload)):
            sources = await web.gather(company_name="Acme")
        assert sources.news == []

    async def test_results_are_capped(self, configured):
        many = {"results": [{"snippet": f"item {i}", "url": f"https://x.test/{i}"} for i in range(50)]}
        with patch("httpx.AsyncClient", return_value=fake_transport(search=many)):
            sources = await web.gather(company_name="Acme")
        assert len(sources.news) == web.MAX_NEWS_RESULTS

    async def test_the_website_feeds_the_summary_not_the_evidence(self, configured):
        """A homepage saying "the leading provider of X" is marketing copy, not
        a dated attributable event."""

        with patch("httpx.AsyncClient", return_value=fake_transport()):
            sources = await web.gather(company_name="Apollo", website="https://apollo.test")
        assert "integrated healthcare" in sources.site_summary
        assert all("apollohospitals.com" != n["source"] for n in sources.news)

    async def test_no_website_means_no_fetch_call(self, configured):
        client = fake_transport()
        with patch("httpx.AsyncClient", return_value=client):
            await web.gather(company_name="Acme", website=None)
        client.post.assert_not_called()


class TestDegradation:
    """"Could not look" is not "looked and found nothing"."""

    async def test_no_key_reports_unavailable(self, monkeypatch):
        monkeypatch.setattr(web.settings, "TINYFISH_API_KEY", "")
        sources = await web.gather(company_name="Acme")
        assert sources.available is False
        assert "TINYFISH_API_KEY" in sources.reason

    async def test_a_provider_outage_reports_unavailable_not_empty(self, configured):
        """Collapsing them would let an outage look like a company with no
        news, quietly lowering every lead's coverage with nothing to explain
        it."""

        with patch("httpx.AsyncClient", return_value=fake_transport(fail=OSError("timeout"))):
            sources = await web.gather(company_name="Acme")
        assert sources.available is False
        assert "timeout" in sources.reason

    async def test_a_genuine_absence_of_news_is_available_and_empty(self, configured):
        with patch("httpx.AsyncClient", return_value=fake_transport(search={"results": []})):
            sources = await web.gather(company_name="Obscure Ltd")
        assert sources.available is True
        assert sources.news == []
        assert "no recent coverage" in sources.reason

    async def test_gather_never_raises(self, configured):
        with patch("httpx.AsyncClient", side_effect=RuntimeError("boom")):
            sources = await web.gather(company_name="Acme")
        assert sources.available is False


class TestAgentIntegration:
    async def test_web_evidence_reaches_recent_news_with_its_source(self, configured):
        with patch("httpx.AsyncClient", return_value=fake_transport()):
            out = await ResearchAgent().run(LEAD)

        claims = {n["claim"]: n["source"] for n in out["recent_news"]}
        assert any("80 billion rupees" in c for c in claims)
        assert all(src for src in claims.values()), "every claim must be attributable"

    async def test_the_model_version_says_whether_sourcing_was_live(self, configured):
        """A report built from live news and one built from a lead record are
        different artifacts; a reader tracing a claim must be able to tell."""

        with patch("httpx.AsyncClient", return_value=fake_transport()):
            live = await ResearchAgent().run(LEAD)
        assert live["model_version"] == WEB_MODEL_VERSION

    async def test_offline_keeps_the_original_version_and_behaviour(self, monkeypatch):
        monkeypatch.setattr(web.settings, "TINYFISH_API_KEY", "")
        out = await ResearchAgent().run(LEAD)
        assert out["model_version"] == MODEL_VERSION
        assert out["sources"] == ["lead_database"]

    async def test_live_news_raises_coverage_confidence(self, configured, monkeypatch):
        monkeypatch.setattr(web.settings, "TINYFISH_API_KEY", "")
        offline = await ResearchAgent().run(LEAD)

        monkeypatch.setattr(web.settings, "TINYFISH_API_KEY", "sk-test")
        with patch("httpx.AsyncClient", return_value=fake_transport()):
            live = await ResearchAgent().run(LEAD)

        assert live["confidence"] > offline["confidence"]

    async def test_sources_name_only_origins_that_contributed(self, configured):
        """Naming `web_search` after a failed call would put a source on a
        report it contributed nothing to."""

        with patch("httpx.AsyncClient", return_value=fake_transport(fail=OSError("down"))):
            out = await ResearchAgent().run(LEAD)
        assert "web_search" not in out["sources"]

    async def test_web_claims_stay_evidence_never_hypothesis(self, configured):
        """The type split is the whole reason a guess cannot be rendered as a
        fact downstream — third-party text must land on the evidence side."""

        with patch("httpx.AsyncClient", return_value=fake_transport()):
            out = await ResearchAgent().run(LEAD)

        hypotheses = " ".join(
            h["statement"] for h in (out["pain_points"] + out["sales_opportunities"])
        )
        assert "80 billion rupees" not in hypotheses

    async def test_buying_signals_read_the_live_evidence(self, configured):
        """The payoff: with real news the timing signals finally have something
        to read, and it is evidence — not an inference laundered into one."""

        from agents.buying_signals.agent import BuyingSignalAgent

        launch = {
            "results": [
                {
                    "snippet": "Apollo announced expansion into three new markets this quarter.",
                    "url": "https://news.test/apollo-expansion",
                }
            ]
        }
        with patch("httpx.AsyncClient", return_value=fake_transport(search=launch)):
            research = await ResearchAgent().run(LEAD)
        signals = await BuyingSignalAgent().run({"research": research})

        assert [s["signal_type"] for s in signals["signals"]] == ["expansion"]
        assert "news.test" in signals["signals"][0]["evidence_source"]


class TestWebsiteGuard:
    """The SSRF path is closed by architecture now that TinyFish fetches, but
    the guard stays: the response is still persisted and shown to a user."""

    def test_internal_hosts_are_not_sent_to_a_third_party(self):
        assert safe_website("http://localhost:6379") is None
        assert safe_website("http://169.254.169.254/latest/meta-data/") is None

    def test_a_public_site_passes(self):
        assert safe_website("https://www.apollohospitals.com") is not None

    def test_a_malformed_website_is_a_missing_input_not_a_failure(self):
        """A bad URL on a lead record must not fail the research run."""

        assert safe_website("not-a-url") is None
        assert safe_website(None) is None
        assert safe_website("   ") is None
