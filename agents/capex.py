"""Run one governed Planning -> Finance/CapEx Agent transformation.

The Finance/CapEx Agent consumes the persisted Planning evidence artifact,
not a freshly recreated upstream model run.

The Planning claim must first earn eligibility for the finance_capex_input
boundary. The model may formulate an evaluation, but Python independently
verifies the threshold comparison before creating the CapEx child envelope.
"""

from decimal import Decimal
import json
import os
from pathlib import Path
import sys

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.assess import assess_for_capex
from agents.envelope import ResultEnvelope
from agents.runtime import load_registry, route_envelope
from agents.transform import create_child_envelope


ROOT = Path(__file__).resolve().parents[1]

PLANNING_ARTIFACT = (
    ROOT / "evals" / "agent_planning_gpt-5.6-terra.json"
)

TARGET_AGENT = "finance_capex"
CAPEX_CLAIM_ID = "claim-capex-001"

REVIEW_THRESHOLD = Decimal("40.00")


CAPEX_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "capex_evaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
                "decision": {
                    "type": "string",
                    "enum": [
                        "WITHIN_REVIEW_THRESHOLD",
                        "EXCEEDS_REVIEW_THRESHOLD",
                    ],
                },
                "evaluated_value": {"type": "string"},
                "threshold_value": {"type": "string"},
                "assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "claim",
                "decision",
                "evaluated_value",
                "threshold_value",
                "assumptions",
            ],
            "additionalProperties": False,
        },
    },
}


def load_planning_parent() -> ResultEnvelope:
    """Load the persisted Planning child envelope and assess it for CapEx."""
    if not PLANNING_ARTIFACT.exists():
        raise FileNotFoundError(
            f"Missing Planning artifact: {PLANNING_ARTIFACT}"
        )

    with PLANNING_ARTIFACT.open(encoding="utf-8") as source:
        artifact = json.load(source)

    child = artifact["child_envelope"]

    planning = ResultEnvelope(
        trace_id=child["trace_id"],
        claim_id=child["claim_id"],
        source_agent=child["source_agent"],
        claim=child["claim"],
        value=child["value"],
        evidence=child["evidence"],
        metric_id=child["metric_id"],
        trust_status=child["trust_status"],
        trust_boundary=child["trust_boundary"],
        trust_decision=child["trust_decision"],
        restrictions=child["restrictions"],
        parent_claim_ids=child["parent_claim_ids"],
    )

    assessed = assess_for_capex(planning)

    route = route_envelope(
        assessed,
        TARGET_AGENT,
    )

    if route["decision"] != "ALLOW_TRANSFER":
        raise PermissionError(
            f"Planning claim was not approved for Finance/CapEx: "
            f"{route['decision']}"
        )

    return assessed


def run_capex_agent(parent: ResultEnvelope) -> dict:
    """Ask Finance/CapEx to evaluate one bounded planning recommendation."""
    model = os.environ["OPENAI_MODEL"]
    registry = load_registry()
    role = registry[TARGET_AGENT]

    input_payload = {
        "role": {
            "agent_id": TARGET_AGENT,
            "name": role["name"],
            "objective": role["objective"],
        },
        "approved_parent_envelope": parent.to_dict(),
        "review_rule": {
            "instruction": (
                "Evaluate whether the supplied planning recommendation is "
                "less than or equal to the financial review threshold."
            ),
            "review_threshold": "40.00",
        },
    }

    instructions = (
        "Act only as the supplied Finance and CapEx Agent role. "
        "Use only the approved parent envelope and review threshold. "
        "Do not reinterpret the recommendation as authorization to spend. "
        "Do not invent additional financial facts. "
        "Return WITHIN_REVIEW_THRESHOLD if the recommendation is less than "
        "or equal to the supplied threshold; otherwise return "
        "EXCEEDS_REVIEW_THRESHOLD. "
        "This is an evaluation only, not a spending approval."
    )

    with OpenAI(max_retries=0) as client:
        response = client.responses.create(
            model=model,
            store=False,
            max_output_tokens=1000,
            instructions=instructions,
            input=json.dumps(input_payload),
            text=CAPEX_FORMAT,
        )

    if response.status != "completed" or not response.output_text:
        raise ValueError(
            "No completed Finance/CapEx response was returned."
        )

    result = json.loads(response.output_text)

    if (
        not isinstance(result, dict)
        or set(result)
        != {
            "claim",
            "decision",
            "evaluated_value",
            "threshold_value",
            "assumptions",
        }
        or result["decision"]
        not in {
            "WITHIN_REVIEW_THRESHOLD",
            "EXCEEDS_REVIEW_THRESHOLD",
        }
        or not isinstance(result["claim"], str)
        or not isinstance(result["evaluated_value"], str)
        or not isinstance(result["threshold_value"], str)
        or not isinstance(result["assumptions"], list)
        or not all(
            isinstance(item, str)
            for item in result["assumptions"]
        )
    ):
        raise ValueError(
            "Finance/CapEx response does not match the contract."
        )

    return {
        "model": response.model,
        "capex": result,
    }


def verify_capex(
    parent: ResultEnvelope,
    decision: str,
    evaluated_value: str,
    threshold_value: str,
) -> dict:
    """Independently verify the financial review decision."""
    parent_value = Decimal(str(parent.value))
    observed_value = Decimal(evaluated_value).quantize(
        Decimal("0.01")
    )
    observed_threshold = Decimal(threshold_value).quantize(
        Decimal("0.01")
    )

    expected_decision = (
        "WITHIN_REVIEW_THRESHOLD"
        if parent_value <= REVIEW_THRESHOLD
        else "EXCEEDS_REVIEW_THRESHOLD"
    )

    verified = (
        observed_value == parent_value
        and observed_threshold == REVIEW_THRESHOLD
        and decision == expected_decision
    )

    return {
        "planning_value": f"{parent_value:.2f}",
        "review_threshold": f"{REVIEW_THRESHOLD:.2f}",
        "observed_value": f"{observed_value:.2f}",
        "observed_threshold": f"{observed_threshold:.2f}",
        "expected_decision": expected_decision,
        "observed_decision": decision,
        "verified": verified,
    }


def run_experiment() -> dict:
    """Run the governed Planning -> Finance/CapEx transformation."""
    parent = load_planning_parent()

    observation = run_capex_agent(parent)

    verification = verify_capex(
        parent=parent,
        decision=observation["capex"]["decision"],
        evaluated_value=observation["capex"]["evaluated_value"],
        threshold_value=observation["capex"]["threshold_value"],
    )

    if not verification["verified"]:
        raise ValueError(
            "Finance/CapEx Agent produced an invalid review decision."
        )

    canonical_claim = (
        f"The planning recommendation of "
        f"{verification['observed_value']} is "
        f"{'within' if verification['observed_decision'] == 'WITHIN_REVIEW_THRESHOLD' else 'above'} "
        f"the financial review threshold of "
        f"{verification['observed_threshold']}. "
        f"This is a financial evaluation only and not authorization to spend."
    )

    child = create_child_envelope(
        parent=parent,
        target_agent=TARGET_AGENT,
        claim_id=CAPEX_CLAIM_ID,
        claim=canonical_claim,
        value=observation["capex"]["decision"],
        metric_id=None,
        evidence={
            "transformation": "financial_review",
            "review_threshold": "40.00",
            "numeric_verification": verification,
            "model": observation["model"],
            "model_claim": observation["capex"]["claim"],
            "model_assumptions": observation["capex"]["assumptions"],
        },
        restrictions=[
            "Financial evaluation is not spend authorization.",
            "No funds may be committed from this claim.",
        ],
    )

    return {
        "experiment": "planning_to_finance_capex",
        "agent_id": f"openai:{observation['model']}",
        "parent_envelope": parent.to_dict(),
        "route_decision": route_envelope(
            parent,
            TARGET_AGENT,
        ),
        "numeric_verification": verification,
        "child_envelope": child.to_dict(),
    }


if __name__ == "__main__":
    model = os.environ["OPENAI_MODEL"]

    artifact_path = (
        ROOT
        / "evals"
        / f"agent_capex_{model}.json"
    )

    if artifact_path.exists():
        raise FileExistsError(
            f"CapEx artifact already exists: {artifact_path}"
        )

    result = run_experiment()

    with artifact_path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")

    print(json.dumps(result, indent=2))
