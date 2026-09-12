"""Create downstream claim envelopes while preserving provenance."""

from typing import Any

from agents.envelope import ResultEnvelope
from agents.runtime import route_envelope


def create_child_envelope(
    parent: ResultEnvelope,
    target_agent: str,
    claim_id: str,
    claim: str,
    value: Any,
    evidence: dict[str, Any],
    restrictions: list[str] | None = None,
) -> ResultEnvelope:
    """Create one downstream claim only after the parent transfer is allowed."""
    route = route_envelope(parent, target_agent)

    if route["decision"] != "ALLOW_TRANSFER":
        raise PermissionError(
            f"Parent claim cannot be routed to {target_agent!r}: "
            f"{route['decision']}"
        )

    inherited_restrictions = list(parent.restrictions)
    if restrictions:
        inherited_restrictions.extend(restrictions)

    return ResultEnvelope(
        trace_id=parent.trace_id,
        claim_id=claim_id,
        source_agent=target_agent,
        claim=claim,
        value=value,
        metric_id=parent.metric_id,
        evidence={
            "parent_claim_id": parent.claim_id,
            "parent_source_agent": parent.source_agent,
            "parent_evidence": parent.evidence,
            **evidence,
        },
        trust_status="UNASSESSED",
        restrictions=inherited_restrictions,
        parent_claim_ids=[
            *parent.parent_claim_ids,
            parent.claim_id,
        ],
    )
