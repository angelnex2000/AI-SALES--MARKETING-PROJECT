"""Prompt for the LLM-backed Research Agent (Phase 8, not yet wired).

Kept beside the rule-based agent so the instruction and the output contract
evolve together — the JSON this asks for is exactly `ResearchOutput`.

Two things the naive version of this prompt gets wrong:

1. **"Do not invent facts" and "identify pain points" contradict each other.**
   Pain points are inferences by definition; under a blanket no-invention rule
   a well-behaved model returns "unknown" for the field outreach needs most.
   The fix is to give inference its own channel with a required basis, rather
   than banning it outright.

2. **Never ask the model for its confidence.** Self-reported confidence is
   uncalibrated and looks authoritative. Confidence is computed from evidence
   coverage in `confidence.py` and is deliberately not part of this contract.
"""

SYSTEM_PROMPT = """\
You are a B2B sales research analyst preparing a briefing for a sales rep who \
will contact this company.

Use ONLY the context provided. You have no other knowledge of this company.

Separate what you FOUND from what you INFER:

- recent_news: only claims present in the context, each with the source it \
came from. If the context contains no news, return an empty list — do not \
fill it with plausible-sounding items.
- pain_points / sales_opportunities: inferences ARE expected here, but each \
must record the basis you reasoned from (e.g. "industry = Healthcare"). Never \
state an inference as an established fact.

If a field cannot be supported, omit it or return an empty list. An honest \
short report is more useful than a padded one: a rep who repeats an invented \
claim to a prospect loses both the deal and the trust.

Return valid JSON only, matching this shape:

{
  "company_summary": str,
  "industry_insights": str | null,
  "company_size_estimate": str | null,
  "recent_news": [{"claim": str, "source": str}],
  "pain_points": [{"statement": str, "basis": str}],
  "sales_opportunities": [{"statement": str, "basis": str}],
  "sources": [str],
  "explanation": str
}

Do not include a confidence value; it is computed separately.
"""

USER_PROMPT_TEMPLATE = """\
Company: {company_name}
Industry: {industry}
Website: {website}
Location: {city}, {country}
Employees: {employees}
Lead source: {lead_source}

CRM notes recorded by the sales team:
{crm_notes}

Additional retrieved context:
{retrieved_context}
"""


def build_user_prompt(context: dict) -> str:
    notes = context.get("crm_notes") or []
    return USER_PROMPT_TEMPLATE.format(
        company_name=context.get("company_name") or "unknown",
        industry=context.get("industry") or "unknown",
        website=context.get("website") or "unknown",
        city=context.get("city") or "unknown",
        country=context.get("country") or "unknown",
        employees=context.get("employees") or "unknown",
        lead_source=context.get("lead_source") or "unknown",
        crm_notes="\n".join(f"- {n}" for n in notes) or "(none recorded)",
        retrieved_context=context.get("retrieved_context") or "(none)",
    )
