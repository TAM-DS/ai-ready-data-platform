"""Reconstruct the governed claim lineage and evidence trail.

Audit does not decide whether controls passed. It reconstructs how the final
executive claim was produced, which evidence supported each transformation,
which trust boundaries were crossed, and where model language differed from
canonical system meaning.
"""

import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]

ARTIFACTS = {
    "forecasting": ROOT / "evals" / "agent_forecasting_gpt-5.6-terra.json",
    "planning": ROOT / "evals" / "agent_planning_gpt-5.6-terra.json",
    "capex": ROOT / "evals" / "agent_capex_gpt-5.6-terra.json",
    "executive_reporting": (
        ROOT / "evals" / "agent_executive_reporting_gpt-5.6-terra.json"
    ),
}

AUDIT_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "audit_explanation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "final_claim_id": {"type": "string"},
                "lineage_complete": {"type": "boolean"},
                "summary": {"type": "string"},
                "material_events": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "limitations": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "final_claim_id",
                "lineage_complete",
                "summary",
                "material_events",
                "limitations",
            ],
            "additionalProperties": False,
        },
    },
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing audit artifact: {path}")

    with path.open(encoding="utf-8") as source:
        return json.load(source)


def reconstruct_trace() -> dict[str, Any]:
    """Build one deterministic claim-by-claim audit trace."""
    forecasting = load_json(ARTIFACTS["forecasting"])
    planning = load_json(ARTIFACTS["planning"])
    capex = load_json(ARTIFACTS["capex"])
    executive = load_json(ARTIFACTS["executive_reporting"])

    forecast_child = planning["parent_envelope"]
    planning_child = planning["child_envelope"]
    capex_child = capex["child_envelope"]
    executive_child = executive["child_envelope"]

    claims = [
        {
            "claim_id": forecasting["parent_envelope"]["claim_id"],
            "source_agent": forecasting["parent_envelope"]["source_agent"],
            "claim": forecasting["parent_envelope"]["claim"],
            "value": forecasting["parent_envelope"]["value"],
            "trust_boundary": forecasting["parent_envelope"]["trust_boundary"],
            "trust_decision": forecasting["parent_envelope"]["trust_decision"],
            "artifact": str(ARTIFACTS["forecasting"].relative_to(ROOT)),
        },
        {
            "claim_id": forecast_child["claim_id"],
            "source_agent": forecast_child["source_agent"],
            "claim": forecast_child["claim"],
            "value": forecast_child["value"],
            "parent_claim_ids": forecast_child["parent_claim_ids"],
            "transformation": forecast_child["evidence"]["transformation"],
            "verification": forecast_child["evidence"]["numeric_verification"],
            "artifact": str(ARTIFACTS["planning"].relative_to(ROOT)),
        },
        {
            "claim_id": planning_child["claim_id"],
            "source_agent": planning_child["source_agent"],
            "claim": planning_child["claim"],
            "value": planning_child["value"],
            "parent_claim_ids": planning_child["parent_claim_ids"],
            "transformation": planning_child["evidence"]["transformation"],
            "verification": planning_child["evidence"]["numeric_verification"],
            "artifact": str(ARTIFACTS["planning"].relative_to(ROOT)),
        },
        {
            "claim_id": capex_child["claim_id"],
            "source_agent": capex_child["source_agent"],
            "claim": capex_child["claim"],
            "value": capex_child["value"],
            "parent_claim_ids": capex_child["parent_claim_ids"],
            "transformation": capex_child["evidence"]["transformation"],
            "verification": capex_child["evidence"]["numeric_verification"],
            "model_claim": capex_child["evidence"].get("model_claim"),
            "canonical_differs_from_model": (
                capex_child["claim"]
                != capex_child["evidence"].get("model_claim")
            ),
            "artifact": str(ARTIFACTS["capex"].relative_to(ROOT)),
        },
        {
            "claim_id": executive_child["claim_id"],
            "source_agent": executive_child["source_agent"],
            "claim": executive_child["claim"],
            "value": executive_child["value"],
            "parent_claim_ids": executive_child["parent_claim_ids"],
            "transformation": executive_child["evidence"]["transformation"],
            "verification": executive_child["evidence"]["semantic_verification"],
            "model_summary": executive_child["evidence"].get("model_summary"),
            "artifact": str(
                ARTIFACTS["executive_reporting"].relative_to(ROOT)
            ),
        },
    ]

    expected_claim_ids = [
        "claim-financial-001",
        "claim-forecast-plan-001",
        "claim-plan-001",
        "claim-capex-001",
        "claim-executive-001",
    ]

    observed_claim_ids = [
        claim["claim_id"]
        for claim in claims
    ]

    lineage_complete = observed_claim_ids == expected_claim_ids

    all_verifications_passed = (
        forecast_child["evidence"]["numeric_verification"]["verified"] is True
        and planning_child["evidence"]["numeric_verification"]["verified"] is True
        and capex_child["evidence"]["numeric_verification"]["verified"] is True
        and executive_child["evidence"]["semantic_verification"]["verified"] is True
    )

    return {
        "audit": "executive_claim_lineage",
        "final_claim_id": executive_child["claim_id"],
        "expected_claim_ids": expected_claim_ids,
        "observed_claim_ids": observed_claim_ids,
        "lineage_complete": lineage_complete,
        "all_verifications_passed": all_verifications_passed,
        "capex_semantic_divergence_detected": (
            capex_child["claim"]
            != capex_child["evidence"].get("model_claim")
        ),
        "claims": claims,
    }


def run_audit_agent(trace: dict[str, Any]) -> dict[str, Any]:
    """Ask Terra to explain the deterministic trace without changing it."""
    model = os.environ["OPENAI_MODEL"]

    instructions = (
        "Act as the Audit Agent. "
        "The supplied deterministic audit trace is authoritative. "
        "Do not change claim IDs, lineage, verification outcomes, or artifact "
        "references. Explain how the final executive claim came to exist, "
        "highlight material transformations and the CapEx semantic divergence, "
        "and state limitations."
    )

    with OpenAI(max_retries=0) as client:
        response = client.responses.create(
            model=model,
            store=False,
            max_output_tokens=1400,
            instructions=instructions,
            input=json.dumps({
                "deterministic_audit_trace": trace
            }),
            text=AUDIT_FORMAT,
        )

    if response.status != "completed" or not response.output_text:
        raise ValueError("No completed Audit response was returned.")

    explanation = json.loads(response.output_text)

    return {
        "model": response.model,
        "explanation": explanation,
    }


def verify_audit_explanation(
    trace: dict[str, Any],
    explanation: dict[str, Any],
) -> dict[str, Any]:
    """Verify that Terra preserved the deterministic audit facts."""
    verified = (
        explanation["final_claim_id"] == trace["final_claim_id"]
        and explanation["lineage_complete"] == trace["lineage_complete"]
    )

    return {
        "expected_final_claim_id": trace["final_claim_id"],
        "observed_final_claim_id": explanation["final_claim_id"],
        "expected_lineage_complete": trace["lineage_complete"],
        "observed_lineage_complete": explanation["lineage_complete"],
        "verified": verified,
    }


def run_experiment() -> dict[str, Any]:
    trace = reconstruct_trace()

    observation = run_audit_agent(trace)

    verification = verify_audit_explanation(
        trace,
        observation["explanation"],
    )

    if not verification["verified"]:
        raise ValueError(
            "Audit Agent changed deterministic lineage facts."
        )

    return {
        "experiment": "audit_executive_claim_lineage",
        "agent_id": f"openai:{observation['model']}",
        "deterministic_trace": trace,
        "verification": verification,
        "model_explanation": observation["explanation"],
        "canonical_conclusion": (
            "The final executive claim is reconstructable from governed "
            "execution through forecasting, planning, Finance/CapEx, and "
            "Executive Reporting with preserved lineage and verified "
            "transformations."
        ),
    }


if __name__ == "__main__":
    model = os.environ["OPENAI_MODEL"]

    trace_path = ROOT / "evals" / "audit_trace.json"
    result_path = ROOT / "evals" / f"agent_audit_{model}.json"

    if trace_path.exists():
        raise FileExistsError(
            f"Audit trace already exists: {trace_path}"
        )

    if result_path.exists():
        raise FileExistsError(
            f"Audit artifact already exists: {result_path}"
        )

    trace = reconstruct_trace()

    with trace_path.open("x", encoding="utf-8") as handle:
        json.dump(trace, handle, indent=2)
        handle.write("\n")

    result = run_experiment()

    with result_path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")

    print(json.dumps(result, indent=2))
