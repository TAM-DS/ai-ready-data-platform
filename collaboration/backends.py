"""A labeled fixture backend and a live OpenAI Agents SDK adapter."""

import asyncio
from collections import defaultdict
from dataclasses import replace
import json

from collaboration.contracts import Budget, Candidate, Task


def supported_candidates(task: Task) -> list[Candidate]:
    """Replay fixture proposals, not an LLM or an observed live-model response."""
    return [Candidate(
        f.fact_id, f.value, f.metric_id, f.grain, f.time_basis, f.kind,
        task.capability, False, f.restrictions, f.canonical_claim,
    ) for f in task.facts]


class FixtureBackend:
    mode = "fixture"

    def __init__(self, scenario="invalid", delay=0.02):
        if scenario not in {"clean", "invalid", "timeout", "conflict"}:
            raise ValueError("Unknown fixture scenario")
        self.scenario = scenario
        self.delay = delay
        self.calls = defaultdict(int)

    async def run(self, task: Task, budget: Budget) -> list[Candidate]:
        self.calls[task.agent_id] += 1
        if (self.scenario == "timeout" and task.agent_id == "store_operations"
                and self.calls[task.agent_id] == 1):
            await asyncio.sleep(budget.attempt_timeout * 2)
        await asyncio.sleep(self.delay)
        candidates = supported_candidates(task)
        if self.scenario == "invalid" and task.agent_id == "regional_sales_manager":
            candidates[0] = replace(
                candidates[0], value="300.00",
                model_claim="The joined line items establish gross revenue of 300.00.",
            )
        return candidates


class SdkBackend:
    """SDK reasoning and a scoped read-only fact tool; no warehouse/model authority.

    Inject an SDK Model for local transport tests. Live construction uses the
    caller's environment API key and selected model; no credentials are exported.
    """

    mode = "live"

    def __init__(self, model_name: str | None = None, *, model=None):
        from agents import OpenAIResponsesModel
        from openai import AsyncOpenAI

        if model is None:
            if not model_name:
                raise ValueError("Specify OPENAI_MODEL or --model for live execution")
            self.client = AsyncOpenAI(max_retries=0)
            self.model = OpenAIResponsesModel(model_name, self.client)
        else:
            self.client = None
            self.model = model
            self.mode = "sdk-fixture"

    async def run(self, task: Task, budget: Budget) -> list[Candidate]:
        from agents import Agent, ModelSettings, RunConfig, Runner, function_tool
        from agents.retry import ModelRetrySettings
        from openai import APIConnectionError, APITimeoutError, RateLimitError
        from pydantic import BaseModel, ConfigDict, Field
        from collaboration.contracts import RetryableAgentError

        class ClaimOutput(BaseModel):
            model_config = ConfigDict(extra="forbid", strict=True)
            fact_id: str = Field(max_length=1000)
            value: str = Field(max_length=1000)
            metric_id: str | None
            grain: str = Field(max_length=1000)
            time_basis: str = Field(max_length=1000)
            kind: str = Field(max_length=1000)
            requested_capability: str = Field(max_length=1000)
            spend_authorized: bool
            restrictions: list[str] = Field(max_length=20)
            model_claim: str = Field(max_length=1000)

        class Reply(BaseModel):
            model_config = ConfigDict(extra="forbid", strict=True)
            claims: list[ClaimOutput] = Field(min_length=1, max_length=budget.max_candidates)

        scoped = {f.fact_id: f for f in task.facts}

        @function_tool(failure_error_function=None)
        async def read_fact(fact_id: str) -> str:
            """Read one application-approved, non-identifying fact for this task."""
            if fact_id not in scoped:
                raise PermissionError("Fact is outside this specialist's scope")
            return json.dumps(scoped[fact_id].to_dict(), sort_keys=True)

        specialist = Agent(
            name=task.agent_id,
            instructions=(
                "You are the supplied business specialist. Read the approved facts using read_fact. "
                "Return only supported candidate claims. Copy each fact's metric_id, grain, time_basis, "
                "kind, value, and required restrictions exactly. Preserve current-versus-historical "
                "and fact-versus-scenario distinctions. Use only the supplied capability. "
                "spend_authorized must remain false. Explain any business limitation in model_claim. "
                "Do not invent data, authorize spending, request another role's facts, or remove restrictions."
            ),
            model=self.model, tools=[read_fact], output_type=Reply,
            model_settings=ModelSettings(
                max_tokens=budget.max_output_tokens, store=False,
                retry=ModelRetrySettings(max_retries=0),
            ),
        )
        try:
            result = await Runner.run(
                specialist, json.dumps({"question": task.question, "role": task.role,
                                        "capability": task.capability,
                                        "available_fact_ids": list(scoped)}),
                max_turns=budget.max_turns,
                run_config=RunConfig(tracing_disabled=True),
            )
        except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
            raise RetryableAgentError(type(exc).__name__) from exc
        return [Candidate.from_dict(c.model_dump()) for c in result.final_output.claims]

    async def close(self):
        if self.client is not None:
            await self.client.close()
