"""Evidence envelope passed between governed agents.

The envelope preserves claim provenance, evidence, trust-boundary status,
restrictions, and lineage as information moves through the multi-agent system.

It carries governance evidence. It does not itself make policy decisions.
"""

from dataclasses import asdict, dataclass, field
from typing import Any


TRUST_STATUSES = {
    "UNASSESSED",
    "ELIGIBLE_FOR_BOUNDARY",
    "BLOCKED_AT_BOUNDARY",
}


@dataclass(frozen=True)
class ResultEnvelope:
    """Represent one claim and the evidence supporting its use."""

    trace_id: str
    claim_id: str
    source_agent: str
    claim: str
    value: Any
    evidence: dict[str, Any]

    metric_id: str | None = None
    trust_status: str = "UNASSESSED"
    trust_boundary: str | None = None
    trust_decision: str | None = None

    restrictions: list[str] = field(default_factory=list)
    parent_claim_ids: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """Validate the structural contract without judging business truth."""
        if not self.trace_id:
            raise ValueError("trace_id must not be empty")

        if not self.claim_id:
            raise ValueError("claim_id must not be empty")

        if not self.source_agent:
            raise ValueError("source_agent must not be empty")

        if not self.claim:
            raise ValueError("claim must not be empty")

        if not isinstance(self.evidence, dict):
            raise TypeError("evidence must be a dictionary")

        if self.trust_status not in TRUST_STATUSES:
            raise ValueError(
                f"Unknown trust_status: {self.trust_status!r}"
            )

        if self.trust_status in {
            "ELIGIBLE_FOR_BOUNDARY",
            "BLOCKED_AT_BOUNDARY",
        }:
            if not self.trust_boundary:
                raise ValueError(
                    "A boundary decision requires trust_boundary"
                )

            if not self.trust_decision:
                raise ValueError(
                    "A boundary decision requires trust_decision"
                )

        if not isinstance(self.restrictions, list):
            raise TypeError("restrictions must be a list")

        if not isinstance(self.parent_claim_ids, list):
            raise TypeError("parent_claim_ids must be a list")

    def to_dict(self) -> dict[str, Any]:
        """Return a validated serializable representation."""
        self.validate()
        return asdict(self)
