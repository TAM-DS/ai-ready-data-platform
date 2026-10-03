"""Application-owned fan-out/fan-in, bounded retries, and truthful partial results."""

import asyncio
from dataclasses import asdict
import time
from typing import Protocol

from collaboration.contracts import Budget, Candidate, Task, RetryableAgentError, digest
from collaboration.evidence import ROLES
from collaboration.governor import assess, reconcile
from platform_agents.runtime import load_registry
from policy.authorize import authorization_decision


class Backend(Protocol):
    mode: str
    async def run(self, task: Task, budget: Budget) -> list[Candidate]: ...


async def run(tasks: tuple[Task, ...], backend: Backend, budget: Budget = Budget()) -> dict:
    """The backend cannot supply its own source role, route, or trusted inputs."""
    if not tasks or len(tasks) > 3 or len({t.agent_id for t in tasks}) != len(tasks):
        raise ValueError("Provide one to three distinct governed specialists")
    registry = load_registry()
    for task in tasks:
        if task.agent_id not in ROLES or (task.role, task.capability) != ROLES[task.agent_id]:
            raise ValueError("Task identity/role/capability is not registered")
        if task.agent_id not in registry or "forecasting" not in registry[task.agent_id]["downstream"]:
            raise ValueError("Task has no declared forecasting route")
        if authorization_decision(task.role, task.capability) != "allow":
            raise PermissionError("Task capability denied before dispatch")
        if (not task.facts or len({f.fact_id for f in task.facts}) != len(task.facts)
                or len(str(task.to_dict()).encode()) > 16000):
            raise ValueError("Task facts are missing, duplicated, or too large")
    trace_id = "collaboration-" + digest([t.to_dict() for t in tasks])[:16]
    origin = time.monotonic()
    events, attempts = [], []
    runs_started = 0
    in_flight = 0
    peak_in_flight = 0
    semaphore = asyncio.Semaphore(budget.max_concurrency)

    def event(kind, task, attempt=None, **details):
        events.append({"sequence": len(events) + 1, "event": kind,
                       "agent_id": task.agent_id, "attempt": attempt,
                       "elapsed_ms": round((time.monotonic() - origin) * 1000, 3), **details})

    async def execute(task):
        nonlocal runs_started, in_flight, peak_in_flight
        event("TASK_QUEUED", task)
        for number in range(1, budget.max_attempts + 1):
            async with semaphore:
                if runs_started >= budget.max_runs:
                    event("TASK_BUDGET_EXHAUSTED", task, number)
                    return {"agent_id": task.agent_id, "status": "BUDGET_EXHAUSTED", "candidates": []}
                runs_started += 1
                in_flight += 1
                peak_in_flight = max(peak_in_flight, in_flight)
                event("ATTEMPT_STARTED", task, number, input_digest=task.input_digest)
                retry = False
                try:
                    reply = await asyncio.wait_for(backend.run(task, budget), budget.attempt_timeout)
                    if (not isinstance(reply, list) or not reply or len(reply) > budget.max_candidates
                            or not all(isinstance(c, Candidate) for c in reply)):
                        raise ValueError("Backend reply violates the candidate contract")
                    # Revalidate even injected backends; dataclass construction is not adjudication.
                    reply = [Candidate.from_dict(c.to_dict()) for c in reply]
                    attempts.append({"agent_id": task.agent_id, "attempt": number,
                                     "status": "COMPLETED", "input_digest": task.input_digest})
                    event("ATTEMPT_COMPLETED", task, number)
                    return {"agent_id": task.agent_id, "status": "COMPLETED",
                            "attempt": number, "candidates": [c.to_dict() for c in reply]}
                except (TimeoutError, RetryableAgentError) as exc:
                    status = "TIMEOUT" if isinstance(exc, TimeoutError) else "TRANSIENT_FAILURE"
                    attempts.append({"agent_id": task.agent_id, "attempt": number,
                                     "status": status, "input_digest": task.input_digest})
                    event("ATTEMPT_FAILED", task, number, reason=status)
                    retry = True
                except asyncio.CancelledError:
                    event("ATTEMPT_CANCELLED", task, number)
                    raise
                except Exception as exc:
                    attempts.append({"agent_id": task.agent_id, "attempt": number,
                                     "status": "FAILED", "error_type": type(exc).__name__,
                                     "input_digest": task.input_digest})
                    event("ATTEMPT_FAILED", task, number, reason=type(exc).__name__)
                    return {"agent_id": task.agent_id, "status": "FAILED", "candidates": []}
                finally:
                    in_flight -= 1
            if retry and number < budget.max_attempts:
                event("RETRY_SCHEDULED", task, number + 1)
        event("TASK_RETRIES_EXHAUSTED", task)
        return {"agent_id": task.agent_id, "status": "RETRIES_EXHAUSTED", "candidates": []}

    workers = [asyncio.create_task(execute(t)) for t in tasks]
    try:
        outcomes = await asyncio.gather(*workers)
    except BaseException:
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise
    assessments = []
    for task, outcome in zip(tasks, outcomes):
        for index, raw in enumerate(outcome["candidates"]):
            claim_id = f"{trace_id}:{task.agent_id}:{index + 1}"
            item = assess(task, Candidate.from_dict(raw), claim_id, trace_id)
            assessments.append(item)
            event("CLAIM_BLOCKED" if item["reasons"] else "CLAIM_ELIGIBLE", task,
                  claim_id=claim_id, reasons=item["reasons"])
    accepted, conflicts = reconcile(assessments)
    failed = [o["agent_id"] for o in outcomes if o["status"] != "COMPLETED"]
    blocked = [a["claim_id"] for a in assessments if a["reasons"]]
    covered = {e["source_agent"] for e in accepted}
    missing = [t.agent_id for t in tasks if t.agent_id not in covered]
    review_required = bool(failed or blocked or conflicts or missing)
    canonical = sorted({e["claim"] for e in accepted})
    artifact = {
        "schema_version": 1, "trace_id": trace_id, "mode": backend.mode,
        "budget": asdict(budget), "tasks": [t.to_dict() for t in tasks],
        "attempts": attempts, "outcomes": outcomes, "assessments": assessments,
        "conflicts": conflicts, "accepted_envelopes": accepted, "events": events,
        "summary": {"state": "REVIEW_REQUIRED" if review_required else "READY_FOR_REVIEW",
                    "supported_findings": canonical, "blocked_claim_ids": blocked,
                    "failed_agents": failed, "missing_agent_coverage": missing,
                    "conflict_count": len(conflicts), "spend_authorized": False},
        "measurements": {"duration_ms": round((time.monotonic() - origin) * 1000, 3),
                         "specialist_runs_started": runs_started, "peak_in_flight": peak_in_flight,
                         "timing_interpretation": ("Simulated backend delays; not live-model performance."
                                                   if backend.mode == "fixture" else
                                                   "Actual SDK with injected model transport; no live API calls."
                                                   if backend.mode == "sdk-fixture" else
                                                   "Measured this run; no latency or cost SLA.")},
    }
    artifact["artifact_sha256"] = digest(artifact)
    return artifact
