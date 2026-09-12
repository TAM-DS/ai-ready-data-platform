"""Run one governed Financial Analyst -> Forecasting Agent transformation.

The Financial Analyst parent claim is produced from the governed order-grain
execution path. The Forecasting Agent receives only an approved envelope and
an explicit scenario assumption.

The model may formulate the downstream claim, but Python independently verifies
the numeric transformation before creating the child envelope.
"""

from decimal import Decimal
import json
import os
from pathlib import Path
import sys

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.envelope import ResultEnvelope
from agents.runtime import load_registry, route_envelope
from agents.transform import create_child_envelope
from execution.execute import execute_metric_for_order
from semantic.grain import introduces_fanout


METRIC_ID = "gross_revenue"
ORDER_ID = 5002
RELATIONSHIP_ID = "sales_orders_to_order_items"

SOURCE_AGENT = "financial_analyst"
TARGET_AGENT = "forecasting"

TRACE_ID = "trace-forecast-001"
PARENT_CLAIM_ID = "claim-financial-001"
CHILD_CLAIM_ID = "claim-forecast-001"

SCENARIO_UPLIFT = Decimal("0.10")


FORECAST_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "forecast_claim",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
                "forecast_value": {"type": "string"},
                "assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "claim",
                "forecast_value",
                "assumptions",
            ],
            "additionalProperties": False,
        },
    },
}


def build_parent_envelope() -> ResultEnvelope:
    """Create the governed Financial Analyst claim used by Forecasting."""
    governed_result = execute_metric_for_order(
        METRIC_ID,
        ORDER_ID,
    )

    fanout_detected = introduces_fanout(
        METRIC_ID,
        RELATIONSHIP_ID,
    )

    parent = ResultEnvelope(
        trace_id=TRACE_ID,
        claim_id=PARENT_CLAIM_ID,
        source_agent=SOURCE_AGENT,
        claim=(
            f"Gross revenue for order {ORDER_ID} is "
            f"{governed_result:.2f}."
        ),
        value=f"{governed_result:.2f}",
        metric_id=METRIC_ID,
        evidence={
            "execution_path": "execute_metric_for_order",
            "order_id": ORDER_ID,
            "relationship_id": RELATIONSHIP_ID,
            "fanout_detected": fanout_detected,
        },
        trust_status="ELIGIBLE_FOR_BOUNDARY",
        trust_boundary="forecasting_input",
        trust_decision="ALLOW_GOVERNED_RESULT",
        restrictions=[
            "Do not reinterpret gross_revenue as net_revenue.",
            "Use only the supplied scenario assumption.",
        ],
    )

    route = route_envelope(parent, TARGET_AGENT)

    if route["decision"] != "ALLOW_TRANSFER":
        raise PermissionError(
            f"Financial Analyst claim was not approved for Forecasting: "
            f"{route['decision']}"
        )

    return parent


def run_forecasting_agent(parent: ResultEnvelope) -> dict:
    """Ask the Forecasting Agent to transform one approved parent claim."""
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
        "scenario": {
            "instruction": (
                "Create a simple scenario projection by increasing the "
                "supplied gross revenue value by exactly 10 percent."
            ),
            "uplift_percent": "10",
        },
    }

    instructions = (
        "Act only as the supplied Forecasting Agent role. "
        "Use only the approved parent envelope and explicit scenario assumption. "
        "Do not reinterpret the metric, invent additional data, remove upstream "
        "restrictions, or claim that the scenario is an observed business fact. "
        "Return the projected value as a decimal string with two decimal places. "
        "State the assumption used."
    )

    with OpenAI(max_retries=0) as client:
        response = client.responses.create(
            model=model,
            store=False,
            max_output_tokens=1000,
            instructions=instructions,
            input=json.dumps(input_payload),
            text=FORECAST_FORMAT,
        )

    if response.status != "completed" or not response.output_text:
        raise ValueError(
            "No completed forecasting response was returned."
        )

    forecast = json.loads(response.output_text)

    if (
        not isinstance(forecast, dict)
        or set(forecast)
        != {"claim", "forecast_value", "assumptions"}
        or not isinstance(forecast["claim"], str)
        or not isinstance(forecast["forecast_value"], str)
        or not isinstance(forecast["assumptions"], list)
        or not all(
            isinstance(item, str)
            for item in forecast["assumptions"]
        )
    ):
        raise ValueError(
            "Forecasting response does not match the contract."
        )

    return {
        "model": response.model,
        "forecast": forecast,
    }


def verify_forecast(
    parent: ResultEnvelope,
    forecast_value: str,
) -> dict:
    """Independently verify the model's numeric transformation."""
    parent_value = Decimal(str(parent.value))
    expected_value = (
        parent_value * (Decimal("1.00") + SCENARIO_UPLIFT)
    ).quantize(Decimal("0.01"))

    observed_value = Decimal(forecast_value).quantize(
        Decimal("0.01")
    )

    verified = observed_value == expected_value

    return {
        "parent_value": f"{parent_value:.2f}",
        "uplift_percent": "10",
        "expected_value": f"{expected_value:.2f}",
        "observed_value": f"{observed_value:.2f}",
        "verified": verified,
    }


def run_experiment() -> dict:
    """Run the first governed live agent-to-agent transformation."""
    parent = build_parent_envelope()

    observation = run_forecasting_agent(parent)

    verification = verify_forecast(
        parent,
        observation["forecast"]["forecast_value"],
    )

    if not verification["verified"]:
        raise ValueError(
            "Forecasting Agent produced a numerically invalid transformation."
        )

    child = create_child_envelope(
        parent=parent,
        target_agent=TARGET_AGENT,
        claim_id=CHILD_CLAIM_ID,
        claim=observation["forecast"]["claim"],
        value=observation["forecast"]["forecast_value"],
        metric_id=parent.metric_id,
        evidence={
            "transformation": "scenario_projection",
            "scenario_uplift_percent": "10",
            "numeric_verification": verification,
            "model": observation["model"],
            "model_assumptions": observation["forecast"]["assumptions"],
        },
        restrictions=[
            "Scenario projection is not an observed business fact.",
        ],
    )

    return {
        "experiment": "financial_analyst_to_forecasting",
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
        / f"agent_forecasting_{model}.json"
    )

    if artifact_path.exists():
        raise FileExistsError(
            f"Forecasting artifact already exists: {artifact_path}"
        )

    result = run_experiment()

    with artifact_path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")

    print(json.dumps(result, indent=2))
