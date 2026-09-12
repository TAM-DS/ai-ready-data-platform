"""Deterministic routing for governed agent-to-agent transfers.

The runtime validates agent identities, declared topology, envelope structure,
and trust-boundary status before information may move to a downstream agent.

LLMs do not decide whether blocked evidence may cross this boundary.
"""

from pathlib import Path
from typing import Any

import yaml

from agents.envelope import ResultEnvelope


REGISTRY_PATH = Path(__file__).resolve().with_name("registry.yaml")


def load_registry() -> dict[str, dict[str, Any]]:
    """Load and validate the governed agent registry."""
    with REGISTRY_PATH.open(encoding="utf-8") as source:
        data = yaml.safe_load(source)

    agents = data["agents"]

    if not isinstance(agents, dict) or not agents:
        raise ValueError("Agent registry must contain governed agents")

    for agent_id, agent in agents.items():
        if not isinstance(agent.get("downstream"), list):
            raise TypeError(
                f"Agent {agent_id!r} must declare downstream as a list"
            )

        for downstream_id in agent["downstream"]:
            if downstream_id not in agents:
                raise KeyError(
                    f"Agent {agent_id!r} references unknown downstream "
                    f"agent {downstream_id!r}"
                )

    return agents


def route_envelope(
    envelope: ResultEnvelope,
    target_agent: str,
) -> dict[str, Any]:
    """Evaluate whether an envelope may move to one declared downstream agent."""
    envelope.validate()
    agents = load_registry()

    if envelope.source_agent not in agents:
        raise KeyError(
            f"Unknown source agent: {envelope.source_agent!r}"
        )

    if target_agent not in agents:
        raise KeyError(
            f"Unknown target agent: {target_agent!r}"
        )

    declared_downstream = agents[envelope.source_agent]["downstream"]

    if target_agent not in declared_downstream:
        return {
            "decision": "BLOCK_UNDECLARED_ROUTE",
            "source_agent": envelope.source_agent,
            "target_agent": target_agent,
            "claim_id": envelope.claim_id,
        }

    if envelope.trust_status == "BLOCKED_AT_BOUNDARY":
        return {
            "decision": "BLOCK_UNJUSTIFIED_INPUT",
            "source_agent": envelope.source_agent,
            "target_agent": target_agent,
            "claim_id": envelope.claim_id,
            "trust_boundary": envelope.trust_boundary,
            "trust_decision": envelope.trust_decision,
        }

    if envelope.trust_status != "ELIGIBLE_FOR_BOUNDARY":
        return {
            "decision": "BLOCK_UNASSESSED_INPUT",
            "source_agent": envelope.source_agent,
            "target_agent": target_agent,
            "claim_id": envelope.claim_id,
            "trust_status": envelope.trust_status,
        }

    required_boundary = agents[target_agent].get("input_boundary")

    if required_boundary is None:
        return {
            "decision": "BLOCK_UNDECLARED_BOUNDARY",
            "source_agent": envelope.source_agent,
            "target_agent": target_agent,
            "claim_id": envelope.claim_id,
        }

    if envelope.trust_boundary != required_boundary:
        return {
            "decision": "BLOCK_WRONG_TRUST_BOUNDARY",
            "source_agent": envelope.source_agent,
            "target_agent": target_agent,
            "claim_id": envelope.claim_id,
            "required_boundary": required_boundary,
            "observed_boundary": envelope.trust_boundary,
        }

    return {
        "decision": "ALLOW_TRANSFER",
        "source_agent": envelope.source_agent,
        "target_agent": target_agent,
        "claim_id": envelope.claim_id,
        "trace_id": envelope.trace_id,
        "restrictions": list(envelope.restrictions),
        "parent_claim_ids": list(envelope.parent_claim_ids),
    }
