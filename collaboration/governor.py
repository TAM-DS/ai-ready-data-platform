"""Assess independently, then reconcile semantic conflicts without voting."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from collaboration.contracts import Candidate, Fact, Task, digest
from platform_agents.envelope import ResultEnvelope
from platform_agents.runtime import route_envelope
from policy.authorize import authorization_decision


def same_value(fact: Fact, value: str) -> bool:
    if fact.metric_id is None:
        return value == fact.value
    try:
        observed, expected = Decimal(value), Decimal(fact.value)
        return observed.is_finite() and expected.is_finite() and observed == expected
    except InvalidOperation:
        return False


def assess(task: Task, candidate: Candidate, claim_id: str, trace_id: str) -> dict:
    """Caller-owned task identity and evidence decide candidate eligibility."""
    reasons = []
    facts = {f.fact_id: f for f in task.facts}
    fact = facts.get(candidate.fact_id)
    try:
        permission = authorization_decision(task.role, candidate.requested_capability)
    except (KeyError, ValueError):
        permission = "deny"
    if permission != "allow" or candidate.requested_capability != task.capability:
        reasons.append("CAPABILITY_DENIED")
    if candidate.spend_authorized:
        reasons.append("SPEND_AUTHORITY_DENIED")
    if fact is None:
        reasons.append("EVIDENCE_OUTSIDE_TASK_SCOPE")
    else:
        if candidate.metric_id != fact.metric_id or candidate.grain != fact.grain:
            reasons.append("SEMANTIC_IDENTITY_MISMATCH")
        if candidate.time_basis != fact.time_basis:
            reasons.append("TEMPORAL_MISMATCH")
        if candidate.kind != fact.kind:
            reasons.append("FACT_SCENARIO_MISMATCH")
        if not same_value(fact, candidate.value):
            reasons.append("VALUE_NOT_SUPPORTED")
        if not set(fact.restrictions).issubset(candidate.restrictions):
            reasons.append("RESTRICTIONS_REMOVED")
    envelope = None
    if not reasons:
        envelope = ResultEnvelope(
            trace_id=trace_id, claim_id=claim_id, source_agent=task.agent_id,
            claim=fact.canonical_claim, value=fact.value, metric_id=fact.metric_id,
            evidence={"fact": fact.to_dict(), "fact_digest": digest(fact.to_dict()),
                      "task_input_digest": task.input_digest, "model_claim": candidate.model_claim},
            trust_status="ELIGIBLE_FOR_BOUNDARY", trust_boundary="forecasting_input",
            trust_decision="ALLOW_SCOPED_VERIFIED_FACT", restrictions=list(fact.restrictions),
        )
        route = route_envelope(envelope, "forecasting")
        if route["decision"] != "ALLOW_TRANSFER":
            reasons.append(route["decision"])
            envelope = None
    return {"claim_id": claim_id, "agent_id": task.agent_id,
            "candidate": candidate.to_dict(), "reasons": reasons,
            "eligible_envelope": envelope.to_dict() if envelope else None}


def reconcile(assessments: list[dict]) -> tuple[list[dict], list[dict]]:
    """Two eligible observations can still conflict; retain all provenance."""
    groups = defaultdict(list)
    for item in assessments:
        if item["eligible_envelope"]:
            envelope = item["eligible_envelope"]
            raw = envelope["evidence"]["fact"]
            fact = Fact(**{**raw, "restrictions": tuple(raw["restrictions"])})
            groups[fact.semantic_key].append(envelope)
    accepted, conflicts = [], []
    for key, envelopes in groups.items():
        values = {str(Decimal(e["value"]).normalize()) if e["metric_id"]
                  else e["value"] for e in envelopes}
        if len(values) > 1:
            conflicts.append({"semantic_key": list(key),
                              "claim_ids": [e["claim_id"] for e in envelopes],
                              "values": sorted(values), "decision": "WITHHOLD_CONFLICTING_CLAIMS"})
        else:
            # Agreement does not create new authority; each envelope retains its own gate.
            accepted.extend(envelopes)
    return accepted, conflicts
