"""Run one governed Forecasting -> Planning Agent transformation.

The Forecasting claim must first earn eligibility for the planning_input
boundary. The Planning Agent receives only that approved claim plus one
explicit planning rule.

The model may formulate the recommendation, but Python independently verifies
the numeric transformation before creating the Planning child envelope.
"""

from decimal import Decimal
import json
import os
from pathlib import Path
import sys

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.assess import assess_for_planning
from agents.envelope import ResultEnvelope
from agents.forecasting import (
    build_parent_envelope,
    run_forecasting_agent,
    verify_forecast,
)
from agents.runtime import load_registry, route_envelope
from agents.transform import create_child_envelope


TARGET_AGENT = "planning"

TRACE_ID = "trace-plan-001"
PLANNING_CLAIM_ID = "claim-plan-001"

BUDGET_RATIO = Decimal("0.30")


PLANNING_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "planning_claim",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
                "recommended_value": {"type": "string"},
                "assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "claim",
                "recommended_value",
                "assumptions",
            ],
            "additionalProperties": False,
        },
    },
}


def build_forecasting_envelope() -> ResultEnvelope:
    """Recreate the governed Forecasting claim and assess it for Planning."""
    financial_parent = build_parent_envelope()

    forecasting_observation = run_forecasting_agent(financial_parent)

    verification = verify_forecast(
        financial_parent,
        forecasting_observation["forecast"]["forecast_value"],
    )

    if not verification["verified"]:
        raise ValueError(
            "Forecasting transformation failed independent verification."
        )

    forecast_child = create_child_envelope(
        parent=financial_parent,
        target_agent="forecasting",
        claim_id="claim-forecast-plan-001",
        claim=forecasting_observation["forecast"]["claim"],
        value=forecasting_observation["forecast"]["forecast_value"],
        metric_id=financial_parent.metric_id,
        evidence={
            "transformation": "scenario_projection",
            "scenario_uplift_percent": "10",
            "numeric_verification": verification,
            "model": forecasting_observation["model"],
            "model_assumptions": forecasting_observation["forecast"][
                "assumptions"
            ],
        },
        restrictions=[
            "Scenario projection is not an observed business fact.",
        ],
    )

    assessed = assess_for_planning(forecast_child)

    route = route_envelope(assessed, TARGET_AGENT)

    if route["decision"] != "ALLOW_TRANSFER":
        raise PermissionError(
            f"Forecasting claim was not approved for Planning: "
            f"{route['decision']}"
        )

    return assessed


def run_planning_agent(parent: ResultEnvelope) -> dict:
    """Ask Planning to produce one bounded scenario recommendation."""
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
        "planning_rule": {
            "instruction": (
                "Recommend an inventory budget ceiling equal to exactly "
                "30 percent of the supplied projected gross revenue."
            ),
            "budget_percent": "30",
        },
    }

    instructions = (
        "Act only as the supplied Planning Agent role. "
        "Use only the approved parent envelope and explicit planning rule. "
        "Do not reinterpret the forecast as observed revenue. "
        "Do not invent additional business facts. "
        "Do not imply that the recommendation is authorization to spend. "
        "Return the recommended value as a decimal string with two decimal "
        "places and state the assumptions used."
    )

    with OpenAI(max_retries=0) as client:
        response = client.responses.create(
            model=model,
            store=False,
            max_output_tokens=1000,
            instructions=instructions,
            input=json.dumps(input_payload),
            text=PLANNING_FORMAT,
        )

    if response.status != "completed" or not response.output_text:
        raise ValueError(
            "No completed Planning response was returned."
        )

    result = json.loads(response.output_text)

    if (
        not isinstance(result, dict)
        or set(result)
        != {"claim", "recommended_value", "assumptions"}
        or not isinstance(result["claim"], str)
        or not isinstance(result["recommended_value"], str)
        or not isinstance(result["assumptions"], list)
        or not all(
            isinstance(item, str)
            for item in result["assumptions"]
        )
    ):
        raise ValueError(
            "Planning response does not match the contract."
        )

    return {
        "model": response.model,
        "planning": result,
    }


def verify_plan(
    parent: ResultEnvelope,
    recommended_value: str,
) -> dict:
    """Independently verify the Planning transformation."""
    parent_value = Decimal(str(parent.value))
    expected_value = (
        parent_value * BUDGET_RATIO
    ).quantize(Decimal("0.01"))

    observed_value = Decimal(recommended_value).quantize(
        Decimal("0.01")
    )

    verified = observed_value == expected_value

    return {
        "parent_value": f"{parent_value:.2f}",
        "budget_percent": "30",
        "expected_value": f"{expected_value:.2f}",
        "observed_value": f"{observed_value:.2f}",
        "verified": verified,
    }


def run_experiment() -> dict:
    """Run the first governed Forecasting -> Planning transformation."""
    parent = build_forecasting_envelope()

    observation = run_planning_agent(parent)

    verification = verify_plan(
        parent,
        observation["planning"]["recommended_value"],
    )

    if not verification["verified"]:
        raise ValueError(
            "Planning Agent produced a numerically invalid transformation."
        )

    child = create_child_envelope(
        parent=parent,
        target_agent=TARGET_AGENT,
        claim_id=PLANNING_CLAIM_ID,
        claim=observation["planning"]["claim"],
        value=observation["planning"]["recommended_value"],
        metric_id=None,
        evidence={
            "transformation": "inventory_budget_ceiling",
            "budget_percent": "30",
            "numeric_verification": verification,
            "model": observation["model"],
            "model_assumptions": observation["planning"]["assumptions"],
        },
        restrictions=[
            "Planning recommendation is scenario-dependent.",
            "Recommendation is not authorization to spend.",
        ],
    )

    return {
        "experiment": "forecasting_to_planning",
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
        Path(__file__).resolve().parents[1]
        / "evals"
        / f"agent_planning_{model}.json"
    )

    if artifact_path.exists():
        raise FileExistsError(
            f"Planning artifact already exists: {artifact_path}"
        )

    result = run_experiment()

    with artifact_path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")

    print(json.dumps(result, indent=2))
