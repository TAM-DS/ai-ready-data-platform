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
