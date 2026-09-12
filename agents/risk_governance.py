"""Explain a deterministic governance inspection without adjudicating it.

The deterministic governance report is authoritative for control outcomes.
The Risk & Governance Agent may summarize and interpret those findings, but
it may not redefine which controls passed or failed.
"""

import json
import os
from pathlib import Path
import sys

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "evals" / "governance_report.json"

REPORT_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "governance_explanation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "overall_assessment": {
                    "type": "string",
                    "enum": ["PASS", "FAIL"],
                },
                "controls_evaluated": {"type": "integer"},
                "controls_failed": {"type": "integer"},
                "summary": {"type": "string"},
                "material_findings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "limitations": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "overall_assessment",
                "controls_evaluated",
                "controls_failed",
                "summary",
                "material_findings",
                "limitations",
            ],
            "additionalProperties": False,
        },
    },
}


def load_report():
    """Load the deterministic governance report."""
    if not REPORT_PATH.exists():
        raise FileNotFoundError(
            f"Missing governance report: {REPORT_PATH}"
        )

    with REPORT_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def run_risk_governance_agent(report):
    """Ask the model to explain, but not adjudicate, deterministic findings."""
    model = os.environ["OPENAI_MODEL"]

    instructions = (
        "Act as the Risk and Governance Agent. "
        "The supplied deterministic governance report is authoritative. "
        "Do not change, reinterpret, or override control pass/fail outcomes. "
        "Explain what the evidence establishes, identify material governance "
        "findings, and state reasonable limitations. "
        "PASS means zero deterministic controls failed; otherwise FAIL."
    )

    with OpenAI(max_retries=0) as client:
        response = client.responses.create(
            model=model,
            store=False,
            max_output_tokens=1200,
            instructions=instructions,
            input=json.dumps({
                "deterministic_governance_report": report
            }),
            text=REPORT_FORMAT,
        )

    if response.status != "completed" or not response.output_text:
        raise ValueError(
            "No completed Risk & Governance response was returned."
        )

    result = json.loads(response.output_text)

    if (
        not isinstance(result, dict)
        or set(result) != {
            "overall_assessment",
            "controls_evaluated",
            "controls_failed",
            "summary",
            "material_findings",
            "limitations",
        }
    ):
        raise ValueError(
            "Risk & Governance response does not match the contract."
        )

    return {
        "model": response.model,
        "explanation": result,
    }


def verify_explanation(report, explanation):
    """Verify the model preserved deterministic governance outcomes."""
    expected_assessment = (
        "PASS"
        if report["controls_failed"] == 0
        else "FAIL"
    )

    verified = (
        explanation["overall_assessment"] == expected_assessment
        and explanation["controls_evaluated"]
        == report["controls_evaluated"]
        and explanation["controls_failed"]
        == report["controls_failed"]
    )

    return {
        "expected_assessment": expected_assessment,
        "observed_assessment": explanation["overall_assessment"],
        "expected_controls_evaluated": report["controls_evaluated"],
        "observed_controls_evaluated": (
            explanation["controls_evaluated"]
        ),
        "expected_controls_failed": report["controls_failed"],
        "observed_controls_failed": explanation["controls_failed"],
        "verified": verified,
    }


def run_experiment():
    """Run the Risk & Governance explanation over deterministic evidence."""
    report = load_report()

    observation = run_risk_governance_agent(report)

    verification = verify_explanation(
        report,
        observation["explanation"],
    )

    if not verification["verified"]:
        raise ValueError(
            "Risk & Governance Agent changed deterministic control outcomes."
        )

    return {
        "experiment": "risk_governance_review",
        "agent_id": f"openai:{observation['model']}",
        "deterministic_result": {
            "controls_evaluated": report["controls_evaluated"],
            "controls_passed": report["controls_passed"],
            "controls_failed": report["controls_failed"],
            "all_controls_passed": report["all_controls_passed"],
        },
        "verification": verification,
        "model_explanation": observation["explanation"],
        "canonical_conclusion": (
            "The governed multi-agent chain passed all deterministic "
            "governance controls evaluated in this experiment."
            if report["all_controls_passed"]
            else
            "The governed multi-agent chain did not pass all deterministic "
            "governance controls evaluated in this experiment."
        ),
    }


if __name__ == "__main__":
    model = os.environ["OPENAI_MODEL"]

    artifact_path = (
        ROOT
        / "evals"
        / f"agent_risk_governance_{model}.json"
    )

    if artifact_path.exists():
        raise FileExistsError(
            f"Risk & Governance artifact already exists: {artifact_path}"
        )

    result = run_experiment()

    with artifact_path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")

    print(json.dumps(result, indent=2))
