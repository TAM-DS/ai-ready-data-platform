"""Exercise the real SDK runner/tools/schema with an injected offline model.

These are SDK integration tests, not live-provider or model-quality evidence.
"""

import json
from pathlib import Path
import tempfile
import unittest

from agents import Model
from agents.items import ModelResponse
from agents.models.interface import ModelTracing
from agents.tracing import set_trace_provider
from agents.tracing.provider import DefaultTraceProvider
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

from collaboration.artifacts import verify_artifact
from collaboration.backends import SdkBackend
from collaboration.contracts import Budget
from collaboration.coordinator import run
from collaboration.evidence import build_tasks
from warehouse.build import build


class ScopedModel(Model):
    """Ask the SDK's real tool for facts, then return a typed fixture proposal."""

    def __init__(self, *, outside_scope=False):
        self.outside_scope = outside_scope
        self.requests = []

    async def get_response(self, system_instructions, input, model_settings, tools,
                           output_schema, handoffs, tracing, **kwargs):
        self.requests.append({"tracing": tracing, "settings": model_settings,
                              "tools": [t.name for t in tools]})
        original = next(i for i in input if i.get("role") == "user")
        content = original["content"]
        if isinstance(content, list):
            content = "".join(i["text"] for i in content)
        task = json.loads(content)
        outputs = [i for i in input if i.get("type") == "function_call_output"]
        if not outputs:
            ids = ["unauthorized_fact"] if self.outside_scope else task["available_fact_ids"]
            calls = [ResponseFunctionToolCall(
                type="function_call", id=f"fixture-{task['capability']}-{index}",
                call_id=f"fixture-{task['capability']}-{index}", name="read_fact",
                arguments=json.dumps({"fact_id": fact_id}),
            ) for index, fact_id in enumerate(ids)]
            return ModelResponse(output=calls, usage=Usage(), response_id=None)
        claims = []
        for item in outputs:
            fact = json.loads(item["output"])
            claims.append({**{k: fact[k] for k in (
                "fact_id", "value", "metric_id", "grain", "time_basis", "kind", "restrictions")},
                "requested_capability": task["capability"], "spend_authorized": False,
                "model_claim": fact["canonical_claim"]})
        message = ResponseOutputMessage(
            id=f"fixture-final-{task['capability']}", type="message", role="assistant",
            status="completed", content=[ResponseOutputText(
                type="output_text", text=json.dumps({"claims": claims}), annotations=[],
            )],
        )
        return ModelResponse(output=[message], usage=Usage(), response_id=None)

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError("Streaming is not used by this adapter")
        yield  # Satisfy the SDK's async-generator interface.


class SdkIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # No exporter/client is needed for offline transport tests. The adapter's
        # per-run tracing setting is independently asserted below.
        set_trace_provider(DefaultTraceProvider())
        cls.temp = tempfile.TemporaryDirectory()
        database = Path(cls.temp.name) / "warehouse.duckdb"
        build(database)
        cls.tasks = build_tasks(database)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    async def test_real_sdk_tool_loop_and_typed_output_for_three_specialists(self):
        model = ScopedModel()
        backend = SdkBackend(model=model)
        artifact = await run(self.tasks, backend, Budget(attempt_timeout=3))
        self.assertEqual(artifact["mode"], "sdk-fixture")
        self.assertEqual(artifact["summary"]["state"], "READY_FOR_REVIEW")
        self.assertEqual(len(artifact["accepted_envelopes"]), 4)
        self.assertEqual(len(model.requests), 6)  # Tool request + structured response per specialist.
        for request in model.requests:
            self.assertEqual(request["tools"], ["read_fact"])
            self.assertEqual(request["tracing"], ModelTracing.DISABLED)
            self.assertFalse(request["settings"].store)
            self.assertEqual(request["settings"].retry.max_retries, 0)
            self.assertEqual(request["settings"].max_tokens, 1000)
        self.assertTrue(verify_artifact(artifact)["verified"])
        await backend.close()

    async def test_actual_sdk_tool_rejects_out_of_scope_fact(self):
        model = ScopedModel(outside_scope=True)
        artifact = await run((self.tasks[0],), SdkBackend(model=model), Budget(attempt_timeout=3))
        self.assertEqual(artifact["summary"]["state"], "REVIEW_REQUIRED")
        self.assertEqual(artifact["outcomes"][0]["status"], "FAILED")
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(artifact["accepted_envelopes"], [])
        self.assertTrue(verify_artifact(artifact)["verified"])

    async def test_sdk_turn_limit_stops_the_tool_loop_without_retry(self):
        model = ScopedModel()
        artifact = await run((self.tasks[0],), SdkBackend(model=model),
                             Budget(max_turns=1, attempt_timeout=3))
        self.assertEqual(artifact["attempts"][0]["error_type"], "MaxTurnsExceeded")
        self.assertEqual(len(artifact["attempts"]), 1)
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(artifact["accepted_envelopes"], [])
        self.assertTrue(verify_artifact(artifact)["verified"])
