"""Persist exact run evidence and independently reconstruct its decisions."""

import json
import math
from pathlib import Path

from collaboration.contracts import Budget, Candidate, Fact, Task, digest
from collaboration.evidence import ROLES
from collaboration.governor import assess, reconcile
from platform_agents.runtime import load_registry
from policy.authorize import authorization_decision


def write_artifact(path: Path, artifact: dict) -> None:
    """Never overwrite an earlier run's evidence."""
    verify_artifact(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, allow_nan=False)
        f.write("\n")


def verify_artifact(artifact: dict) -> dict:
    """Rebuild decisions against the captured facts and current control code.

    The digest detects changes; it is not an authenticated signature. Captured
    source declarations do not independently prove warehouse or actor identity.
    """
    if artifact["schema_version"] != 1 or artifact["mode"] not in {"fixture", "live", "sdk-fixture"}:
        raise ValueError("Unknown artifact schema/mode")
    unsigned = {k: v for k, v in artifact.items() if k != "artifact_sha256"}
    if digest(unsigned) != artifact["artifact_sha256"]:
        raise ValueError("Artifact checksum mismatch")
    budget = Budget(**artifact["budget"])
    tasks = tuple(Task(**{**t, "facts": tuple(Fact(**{
        **f, "restrictions": tuple(f["restrictions"]),
    }) for f in t["facts"])}) for t in artifact["tasks"])
    if not tasks or len(tasks) > 3 or len({t.agent_id for t in tasks}) != len(tasks):
        raise ValueError("Invalid task topology")
    registry = load_registry()
    task_map = {t.agent_id: t for t in tasks}
    for task in tasks:
        if (task.agent_id not in ROLES or (task.role, task.capability) != ROLES[task.agent_id]
                or authorization_decision(task.role, task.capability) != "allow"
                or "forecasting" not in registry[task.agent_id]["downstream"]
                or not task.facts or len({f.fact_id for f in task.facts}) != len(task.facts)
                or len(str(task.to_dict()).encode()) > 16000):
            raise ValueError("Task identity/capability/route mismatch")
    expected_trace = "collaboration-" + digest([t.to_dict() for t in tasks])[:16]
    if artifact["trace_id"] != expected_trace:
        raise ValueError("Trace input binding mismatch")
    outcomes = artifact["outcomes"]
    if [o["agent_id"] for o in outcomes] != [t.agent_id for t in tasks]:
        raise ValueError("Task outcomes are missing, duplicated, or reordered")
    assessments = []
    for task, outcome in zip(tasks, outcomes):
        if outcome["status"] not in {"COMPLETED", "FAILED", "BUDGET_EXHAUSTED", "RETRIES_EXHAUSTED"}:
            raise ValueError("Unknown task outcome")
        if outcome["status"] != "COMPLETED" and outcome["candidates"]:
            raise ValueError("Failed task cannot create candidates")
        if outcome["status"] == "COMPLETED" and not 1 <= len(outcome["candidates"]) <= budget.max_candidates:
            raise ValueError("Completed task must have bounded candidates")
        for index, raw in enumerate(outcome["candidates"]):
            assessments.append(assess(task, Candidate.from_dict(raw),
                                      f"{expected_trace}:{task.agent_id}:{index + 1}", expected_trace))
    accepted, conflicts = reconcile(assessments)
    # JSON normalization accounts for tuple/list representations after persistence.
    normalized = lambda value: json.loads(json.dumps(value))
    if normalized(assessments) != normalized(artifact["assessments"]):
        raise ValueError("Candidate assessment replay mismatch")
    if normalized(accepted) != normalized(artifact["accepted_envelopes"]):
        raise ValueError("Accepted lineage replay mismatch")
    if normalized(conflicts) != normalized(artifact["conflicts"]):
        raise ValueError("Conflict replay mismatch")
    failed = [o["agent_id"] for o in outcomes if o["status"] != "COMPLETED"]
    blocked = [a["claim_id"] for a in assessments if a["reasons"]]
    covered = {e["source_agent"] for e in accepted}
    missing = [t.agent_id for t in tasks if t.agent_id not in covered]
    summary = {"state": "REVIEW_REQUIRED" if failed or blocked or conflicts or missing else "READY_FOR_REVIEW",
               "supported_findings": sorted({e["claim"] for e in accepted}),
               "blocked_claim_ids": blocked, "failed_agents": failed,
               "missing_agent_coverage": missing, "conflict_count": len(conflicts), "spend_authorized": False}
    if summary != artifact["summary"]:
        raise ValueError("Executive review replay mismatch")
    if len(artifact["attempts"]) != artifact["measurements"]["specialist_runs_started"]:
        raise ValueError("Attempt accounting mismatch")
    if len(artifact["attempts"]) > budget.max_runs:
        raise ValueError("Run budget exceeded")
    attempt_keys = set()
    for a in artifact["attempts"]:
        key = (a["agent_id"], a["attempt"])
        if (key in attempt_keys or a["agent_id"] not in task_map
                or type(a["attempt"]) is not int or not 1 <= a["attempt"] <= budget.max_attempts
                or a["status"] not in {"COMPLETED", "FAILED", "TIMEOUT", "TRANSIENT_FAILURE"}
                or a["input_digest"] != task_map[a["agent_id"]].input_digest):
            raise ValueError("Attempt input binding mismatch")
        attempt_keys.add(key)
    if not 1 <= artifact["measurements"]["peak_in_flight"] <= budget.max_concurrency:
        raise ValueError("Concurrency budget exceeded")
    active, started, ended, queued = set(), {}, {}, set()
    claim_events = []
    peak = 0
    elapsed = 0.0
    for index, event in enumerate(artifact["events"], start=1):
        agent = event["agent_id"]
        if event["sequence"] != index or agent not in task_map:
            raise ValueError("Trace sequence/identity mismatch")
        now = event["elapsed_ms"]
        if not math.isfinite(now) or now < elapsed:
            raise ValueError("Trace time is invalid")
        elapsed = now
        key = (agent, event["attempt"])
        kind = event["event"]
        if kind == "TASK_QUEUED":
            if agent in queued:
                raise ValueError("Task queued twice")
            queued.add(agent)
        elif kind == "ATTEMPT_STARTED":
            if (agent not in queued or key in started
                    or any(a == agent for a, _ in active)
                    or event["input_digest"] != task_map[agent].input_digest):
                raise ValueError("Trace attempt binding mismatch")
            started[key] = event
            active.add(key)
            peak = max(peak, len(active))
        elif kind in {"ATTEMPT_COMPLETED", "ATTEMPT_FAILED"}:
            if key not in active:
                raise ValueError("Attempt ended without a start")
            active.remove(key)
            ended[key] = event
        elif kind in {"CLAIM_BLOCKED", "CLAIM_ELIGIBLE"}:
            if active:
                raise ValueError("Claim assessed before specialist execution finished")
            claim_events.append({k: event[k] for k in ("event", "agent_id", "claim_id", "reasons")})
        elif kind not in {"TASK_BUDGET_EXHAUSTED", "TASK_RETRIES_EXHAUSTED", "RETRY_SCHEDULED"}:
            raise ValueError("Unknown trace event")
    if (active or set(started) != attempt_keys or set(ended) != attempt_keys
            or queued != set(task_map) or peak != artifact["measurements"]["peak_in_flight"]):
        raise ValueError("Incomplete attempt trace")
    expected_claim_events = [{"event": "CLAIM_BLOCKED" if a["reasons"] else "CLAIM_ELIGIBLE",
                              "agent_id": a["agent_id"], "claim_id": a["claim_id"],
                              "reasons": a["reasons"]} for a in assessments]
    if claim_events != expected_claim_events:
        raise ValueError("Claim assessment trace mismatch")
    duration = artifact["measurements"]["duration_ms"]
    if not math.isfinite(duration) or duration < elapsed:
        raise ValueError("Run duration/trace mismatch")
    for a in artifact["attempts"]:
        key = (a["agent_id"], a["attempt"])
        if (a["status"] == "COMPLETED") != (ended[key]["event"] == "ATTEMPT_COMPLETED"):
            raise ValueError("Attempt outcome/trace mismatch")
        if a["status"] != "COMPLETED" and ended[key]["reason"] != (
                a["error_type"] if a["status"] == "FAILED" else a["status"]):
            raise ValueError("Failure reason/trace mismatch")
    for o in outcomes:
        task_attempts = sorted([a for a in artifact["attempts"] if a["agent_id"] == o["agent_id"]],
                               key=lambda a: a["attempt"])
        if [a["attempt"] for a in task_attempts] != list(range(1, len(task_attempts) + 1)):
            raise ValueError("Attempt sequence has gaps")
        if any(a["status"] not in {"TIMEOUT", "TRANSIENT_FAILURE"} for a in task_attempts[:-1]):
            raise ValueError("Non-retryable attempt was retried")
        if o["status"] == "COMPLETED" and (
                not task_attempts or task_attempts[-1]["status"] != "COMPLETED"
                or o["attempt"] != task_attempts[-1]["attempt"]):
            raise ValueError("Completed outcome lacks its exact successful attempt")
        if o["status"] == "FAILED" and (not task_attempts or task_attempts[-1]["status"] != "FAILED"):
            raise ValueError("Failed outcome lacks its exact failed attempt")
        if o["status"] == "RETRIES_EXHAUSTED" and (
                len(task_attempts) != budget.max_attempts
                or task_attempts[-1]["status"] not in {"TIMEOUT", "TRANSIENT_FAILURE"}):
            raise ValueError("Retry exhaustion does not match the attempt budget")
        if o["status"] == "BUDGET_EXHAUSTED" and (
                len(artifact["attempts"]) != budget.max_runs
                or task_attempts and task_attempts[-1]["status"] not in {"TIMEOUT", "TRANSIENT_FAILURE"}):
            raise ValueError("Run budget exhaustion does not match execution")
    return {"verified": True, "trace_id": expected_trace, "state": summary["state"],
            "accepted_claims": len(accepted), "blocked_claims": len(blocked),
            "conflicts": len(conflicts)}
