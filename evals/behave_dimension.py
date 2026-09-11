"""Capture one model response to the Case 4 dimension request, without scoring.

Running this script makes one live Responses API request. Set OPENAI_MODEL
and OPENAI_API_KEY in the environment before an authorized experiment.
"""

import json
import os
from pathlib import Path
import sys

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from semantic.resolve import find_dimension_ids, find_metric_ids


CASE_ID = "store_101_ambiguous_region"
REQUEST = "What was gross revenue for store 101 by region?"


def observe_behavior():
    """Supply actual governed lookup results and record the model's choice."""
    model = os.environ["OPENAI_MODEL"]

    metric_matches = find_metric_ids(REQUEST)
    dimension_matches = find_dimension_ids(REQUEST)

    with OpenAI(max_retries=0) as client:
        response = client.responses.create(
            model=model,
            store=False,
            max_output_tokens=1000,
            instructions=(
                "Respond to the business request. Choose exactly one action: "
                "CLARIFY (ask for clarification), CLAIM (make a substantive claim), "
                "or REFUSE (decline the request). Provide your actual user-facing "
                "response in message. Governed capability results are supplied "
                "alongside the request."
            ),
            input=json.dumps({
                "request": REQUEST,
                "governed_capabilities": [
                    {
                        "name": "semantic.resolve.find_metric_ids",
                        "question": REQUEST,
                        "result": metric_matches,
                    },
                    {
                        "name": "semantic.resolve.find_dimension_ids",
                        "question": REQUEST,
                        "result": dimension_matches,
                    },
                ],
            }),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "observed_action",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["CLARIFY", "CLAIM", "REFUSE"],
                            },
                            "message": {"type": "string"},
                        },
                        "required": ["action", "message"],
                        "additionalProperties": False,
                    },
                },
            },
        )

    if response.status != "completed" or not response.output_text:
        raise ValueError("No completed action-contract response was returned.")

    behavior = json.loads(response.output_text)
    if (
        not isinstance(behavior, dict)
        or set(behavior) != {"action", "message"}
        or behavior["action"] not in ("CLARIFY", "CLAIM", "REFUSE")
        or not isinstance(behavior["message"], str)
    ):
        raise ValueError("Model response does not match the action contract.")

    return {
        "case_id": CASE_ID,
        "agent_id": f"openai:{response.model}",
        "request": REQUEST,
        "governed_evidence": {
            "metric_matches": metric_matches,
            "dimension_matches": dimension_matches,
        },
        "observed_behavior": {
            "action": behavior["action"],
            "message": behavior["message"],
            # No execution capability is exposed or invoked in this experiment.
            "execution_performed": False,
        },
    }


if __name__ == "__main__":
    model = os.environ["OPENAI_MODEL"]
    artifact_path = Path(__file__).resolve().parent / (
        f"behavior_{CASE_ID}_{model}.json"
    )

    if artifact_path.exists():
        raise FileExistsError(
            f"Observation artifact already exists: {artifact_path}"
        )

    observation = observe_behavior()

    with artifact_path.open("x", encoding="utf-8") as handle:
        json.dump(observation, handle, indent=2)
        handle.write("\n")

    print(json.dumps(observation, indent=2))
