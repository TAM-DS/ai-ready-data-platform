"""Translate independent evidence into scoped interventions, without scoring."""

import json
from pathlib import Path
import sys

# Support direct execution with python evals/justify.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.evidence import collect_evidence


def justify_evidence(record):
    """Preserve every applicable intervention; list order is not a priority.

    Missing observation fields do not establish a control outcome. An empty
    intervention list makes no claim that execution or an answer is permitted.
    """
    observations = record["observations"]
    interventions = []

    ambiguous = {
        field: observations[field]
        for field in ("metric_matches", "dimension_matches")
        if observations.get(field) == []
    }
    if ambiguous:
        interventions.append({"justification": "CLARIFY", "details": ambiguous})

    if observations.get("temporal_mismatch") is True:
        interventions.append({
            "justification": "REFUSE_UNSUPPORTED_CLAIM",
            "details": {"temporal_mismatch": True},
        })

    if observations.get("fanout_detected") is True:
        interventions.append({
            "justification": "BLOCK_EXECUTION_PATH",
            "details": {"fanout_detected": True},
        })

    denied = [
        capability
        for capability, decision in observations.get("authorization", {}).items()
        if decision == "deny"
    ]
    if denied:
        interventions.append({
            "justification": "BLOCK_DENIED_CAPABILITIES",
            "details": {"denied_capabilities": denied},
        })

    resolved = observations.get("identity_resolved")
    target_exists = observations.get("target_exists")
    if resolved is True and target_exists is True:
        interventions.append({
            "justification": "PASS_IDENTITY_GATE",
            "details": {
                field: observations[field]
                for field in ("identity_resolved", "canonical_id", "target_exists")
                if field in observations
            },
        })
    elif resolved is False or target_exists is False:
        interventions.append({
            "justification": "IDENTITY_GATE_FAILED",
            "details": {
                field: observations[field]
                for field in ("identity_resolved", "canonical_id", "target_exists")
                if field in observations
            },
        })

    return {"case_id": record["case_id"], "interventions": interventions}


def collect_justifications():
    """Return one justification record per independently observed case."""
    return [justify_evidence(record) for record in collect_evidence()]


if __name__ == "__main__":
    print(json.dumps(collect_justifications(), indent=2))
