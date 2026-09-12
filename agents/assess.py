"""Deterministically assess whether a claim may cross a named trust boundary."""

from dataclasses import replace

from agents.envelope import ResultEnvelope


def assess_for_planning(
    envelope: ResultEnvelope,
) -> ResultEnvelope:
    """Assess one Forecasting claim for the planning_input boundary."""
    envelope.validate()

    if envelope.source_agent != "forecasting":
        return replace(
            envelope,
            trust_status="BLOCKED_AT_BOUNDARY",
            trust_boundary="planning_input",
            trust_decision="BLOCK_WRONG_SOURCE_AGENT",
        )

    numeric_verification = envelope.evidence.get(
        "numeric_verification",
        {}
    )

    if numeric_verification.get("verified") is not True:
        return replace(
            envelope,
            trust_status="BLOCKED_AT_BOUNDARY",
            trust_boundary="planning_input",
            trust_decision="BLOCK_UNVERIFIED_TRANSFORMATION",
        )

    if (
        "Scenario projection is not an observed business fact."
        not in envelope.restrictions
    ):
        return replace(
            envelope,
            trust_status="BLOCKED_AT_BOUNDARY",
            trust_boundary="planning_input",
            trust_decision="BLOCK_MISSING_SCENARIO_RESTRICTION",
        )

    return replace(
        envelope,
        trust_status="ELIGIBLE_FOR_BOUNDARY",
        trust_boundary="planning_input",
        trust_decision="ALLOW_VERIFIED_SCENARIO",
    )


def assess_for_capex(
    envelope: ResultEnvelope,
) -> ResultEnvelope:
    """Assess one Planning claim for the finance_capex_input boundary."""
    envelope.validate()

    if envelope.source_agent != "planning":
        return replace(
            envelope,
            trust_status="BLOCKED_AT_BOUNDARY",
            trust_boundary="finance_capex_input",
            trust_decision="BLOCK_WRONG_SOURCE_AGENT",
        )

    numeric_verification = envelope.evidence.get(
        "numeric_verification",
        {}
    )

    if numeric_verification.get("verified") is not True:
        return replace(
            envelope,
            trust_status="BLOCKED_AT_BOUNDARY",
            trust_boundary="finance_capex_input",
            trust_decision="BLOCK_UNVERIFIED_PLANNING_TRANSFORMATION",
        )

    if (
        "Recommendation is not authorization to spend."
        not in envelope.restrictions
    ):
        return replace(
            envelope,
            trust_status="BLOCKED_AT_BOUNDARY",
            trust_boundary="finance_capex_input",
            trust_decision="BLOCK_MISSING_SPEND_RESTRICTION",
        )

    return replace(
        envelope,
        trust_status="ELIGIBLE_FOR_BOUNDARY",
        trust_boundary="finance_capex_input",
        trust_decision="ALLOW_PLANNING_RECOMMENDATION",
    )


def assess_for_executive_reporting(
    envelope: ResultEnvelope,
) -> ResultEnvelope:
    """Assess one Finance/CapEx claim for executive_reporting_input."""
    envelope.validate()

    if envelope.source_agent != "finance_capex":
        return replace(
            envelope,
            trust_status="BLOCKED_AT_BOUNDARY",
            trust_boundary="executive_reporting_input",
            trust_decision="BLOCK_WRONG_SOURCE_AGENT",
        )

    numeric_verification = envelope.evidence.get(
        "numeric_verification",
        {}
    )

    if numeric_verification.get("verified") is not True:
        return replace(
            envelope,
            trust_status="BLOCKED_AT_BOUNDARY",
            trust_boundary="executive_reporting_input",
            trust_decision="BLOCK_UNVERIFIED_FINANCIAL_REVIEW",
        )

    if (
        "No funds may be committed from this claim."
        not in envelope.restrictions
    ):
        return replace(
            envelope,
            trust_status="BLOCKED_AT_BOUNDARY",
            trust_boundary="executive_reporting_input",
            trust_decision="BLOCK_MISSING_EXECUTION_RESTRICTION",
        )

    return replace(
        envelope,
        trust_status="ELIGIBLE_FOR_BOUNDARY",
        trust_boundary="executive_reporting_input",
        trust_decision="ALLOW_FINANCIAL_EVALUATION_REPORTING",
    )
