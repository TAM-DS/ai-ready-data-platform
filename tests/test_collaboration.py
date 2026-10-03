"""Attack the trust boundary and scheduler, not model wording."""

import asyncio
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collaboration.artifacts import verify_artifact, write_artifact
from collaboration.backends import FixtureBackend, supported_candidates
from collaboration.contracts import Budget, Candidate, RetryableAgentError, digest
from collaboration.coordinator import run
from collaboration.evidence import build_tasks
from collaboration.governor import assess, reconcile
from warehouse.build import build


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db = Path(cls.temp.name) / "warehouse.duckdb"
        build(cls.db)
        cls.tasks = build_tasks(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check_block(self, reason, **changes):
        task = self.tasks[0]
        candidate = replace(supported_candidates(task)[0], **changes)
        result = assess(task, candidate, "claim-1", "trace-1")
        self.assertIn(reason, result["reasons"])
        self.assertIsNone(result["eligible_envelope"])

    def test_fanout_financial_error_is_blocked(self):
        self.check_block("VALUE_NOT_SUPPORTED", value="300.00")

    def test_semantic_metric_substitution_is_blocked(self):
        self.check_block("SEMANTIC_IDENTITY_MISMATCH", metric_id="net_revenue")

    def test_grain_substitution_is_blocked(self):
        self.check_block("SEMANTIC_IDENTITY_MISMATCH", grain="order_item")

    def test_current_fact_cannot_become_historical(self):
        task = self.tasks[2]
        candidate = replace(supported_candidates(task)[1], time_basis="2026-09")
        result = assess(task, candidate, "claim-1", "trace-1")
        self.assertIn("TEMPORAL_MISMATCH", result["reasons"])

    def test_observation_cannot_become_scenario(self):
        self.check_block("FACT_SCENARIO_MISMATCH", kind="scenario")

    def test_customer_precision_is_not_authorized(self):
        task = self.tasks[1]
        c = replace(supported_candidates(task)[0], requested_capability="customer_names")
        result = assess(task, c, "claim-1", "trace-1")
        self.assertIn("CAPABILITY_DENIED", result["reasons"])

    def test_out_of_scope_fact_is_blocked(self):
        self.check_block("EVIDENCE_OUTSIDE_TASK_SCOPE", fact_id="vip_gross")

    def test_no_model_spend_authority(self):
        self.check_block("SPEND_AUTHORITY_DENIED", spend_authorized=True)

    def test_restrictions_cannot_be_removed(self):
        self.check_block("RESTRICTIONS_REMOVED", restrictions=())

    def test_nonfinite_and_invalid_numbers_fail_closed(self):
        for value in ("NaN", "Infinity", "-Infinity", "not-a-number"):
            with self.subTest(value=value):
                self.check_block("VALUE_NOT_SUPPORTED", value=value)

    def test_model_language_is_not_canonical_meaning(self):
        task = self.tasks[0]
        c = replace(supported_candidates(task)[0], model_claim="This authorizes capital spending.")
        result = assess(task, c, "claim-1", "trace-1")
        envelope = result["eligible_envelope"]
        self.assertEqual(envelope["claim"], task.facts[0].canonical_claim)
        self.assertEqual(envelope["evidence"]["model_claim"], c.model_claim)
        self.assertIn("No funds may be committed from this claim.", envelope["restrictions"])

    def test_conflicts_withheld_without_majority_vote(self):
        tasks = build_tasks(self.db, conflict=True)
        assessments = [assess(t, c, f"{t.agent_id}:{i}", "trace")
                       for t in tasks for i, c in enumerate(supported_candidates(t))]
        # A third agreeing copy cannot outvote a conflicting eligible observation.
        assessments.append(copy.deepcopy(assessments[0]))
        accepted, conflicts = reconcile(assessments)
        self.assertEqual(len(conflicts), 1)
        self.assertFalse(any(e["evidence"]["fact"]["scope"] == "store:101"
                             and e["metric_id"] == "gross_revenue" for e in accepted))
        self.assertTrue(any(e["source_agent"] == "customer_analytics" for e in accepted))

    def test_fact_snapshot_excludes_customer_identifiers(self):
        inputs = json.dumps([t.to_dict() for t in self.tasks])
        for text in ("Jane Doe", "Thomas Wilkerson", "jane.doe@gmail.com", "tw@gmail.com"):
            self.assertNotIn(text, inputs)


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "warehouse.duckdb"
        build(self.db)
        self.tasks = build_tasks(self.db)
        self.budget = Budget(attempt_timeout=0.03)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_parallel_overlap_and_sequential_equivalence(self):
        class BarrierBackend(FixtureBackend):
            def __init__(self):
                super().__init__("clean", 0)
                self.arrived = 0
                self.barrier = asyncio.Event()

            async def run(self, task, budget):
                self.arrived += 1
                if self.arrived == 3:
                    self.barrier.set()
                await self.barrier.wait()
                return supported_candidates(task)

        parallel = await run(self.tasks, BarrierBackend(), replace(self.budget, attempt_timeout=1))
        sequential = await run(self.tasks, FixtureBackend("clean", 0),
                               replace(self.budget, max_concurrency=1))
        self.assertEqual(parallel["measurements"]["peak_in_flight"], 3)
        self.assertEqual(sequential["measurements"]["peak_in_flight"], 1)
        self.assertEqual(parallel["summary"], sequential["summary"])
        self.assertTrue(verify_artifact(parallel)["verified"])

    async def test_invalid_specialist_does_not_erase_useful_findings(self):
        result = await run(self.tasks, FixtureBackend("invalid", 0), self.budget)
        self.assertEqual(result["summary"]["state"], "REVIEW_REQUIRED")
        self.assertEqual(len(result["summary"]["blocked_claim_ids"]), 1)
        self.assertTrue(result["summary"]["supported_findings"])
        self.assertFalse(result["summary"]["spend_authorized"])
        verify_artifact(result)

    async def test_timeout_retry_preserves_first_failure(self):
        result = await run(self.tasks, FixtureBackend("timeout", 0), self.budget)
        attempts = [a for a in result["attempts"] if a["agent_id"] == "store_operations"]
        self.assertEqual([a["status"] for a in attempts], ["TIMEOUT", "COMPLETED"])
        self.assertEqual(result["summary"]["state"], "READY_FOR_REVIEW")
        verify_artifact(result)

    async def test_retry_exhaustion_is_partial_not_success(self):
        class Broken(FixtureBackend):
            async def run(self, task, budget):
                if task.agent_id == "store_operations":
                    raise RetryableAgentError("transport")
                return supported_candidates(task)
        result = await run(self.tasks, Broken("clean", 0), self.budget)
        self.assertIn("store_operations", result["summary"]["failed_agents"])
        self.assertEqual(result["summary"]["state"], "REVIEW_REQUIRED")
        self.assertEqual(len(result["attempts"]), 4)
        verify_artifact(result)

    async def test_unexpected_failure_is_recorded_without_retry(self):
        class Broken(FixtureBackend):
            async def run(self, task, budget):
                if task.agent_id == "store_operations":
                    raise RuntimeError("private diagnostic must not leak")
                return supported_candidates(task)
        result = await run(self.tasks, Broken("clean", 0), self.budget)
        self.assertEqual(len(result["attempts"]), 3)
        self.assertNotIn("private diagnostic", json.dumps(result))
        self.assertEqual(result["outcomes"][2]["status"], "FAILED")
        verify_artifact(result)

    async def test_run_budget_stops_dispatch(self):
        backend = FixtureBackend("clean", 0)
        result = await run(self.tasks, backend, replace(self.budget, max_runs=2))
        self.assertEqual(sum(backend.calls.values()), 2)
        self.assertEqual(result["outcomes"][2]["status"], "BUDGET_EXHAUSTED")
        self.assertEqual(result["summary"]["state"], "REVIEW_REQUIRED")
        verify_artifact(result)

    async def test_malformed_reply_fails_without_retry(self):
        class Malformed(FixtureBackend):
            async def run(self, task, budget):
                return ["not a candidate"]
        result = await run(self.tasks, Malformed("clean", 0), self.budget)
        self.assertEqual(len(result["attempts"]), 3)
        self.assertFalse(result["accepted_envelopes"])
        self.assertEqual(result["summary"]["state"], "REVIEW_REQUIRED")

    async def test_cancellation_drains_all_workers(self):
        class Blocking(FixtureBackend):
            def __init__(self):
                self.active = 0
                self.entered = asyncio.Event()

            async def run(self, task, budget):
                self.active += 1
                if self.active == 3:
                    self.entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.active -= 1
        backend = Blocking()
        running = asyncio.create_task(run(self.tasks, backend, replace(self.budget, attempt_timeout=5)))
        await asyncio.wait_for(backend.entered.wait(), 1)
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertEqual(backend.active, 0)

    async def test_forged_role_is_rejected_before_dispatch(self):
        backend = FixtureBackend("clean", 0)
        forged = replace(self.tasks[0], role="customer_analytics")
        with self.assertRaises(ValueError):
            await run((forged,), backend, self.budget)
        self.assertFalse(backend.calls)

    async def test_duplicate_specialist_rejected(self):
        with self.assertRaises(ValueError):
            await run((self.tasks[0], self.tasks[0]), FixtureBackend(), self.budget)

    async def test_mutable_task_evidence_rejected(self):
        with self.assertRaisesRegex(ValueError, "immutable"):
            replace(self.tasks[0], facts=list(self.tasks[0].facts))

    async def test_current_policy_is_checked_at_claim_assessment(self):
        # Dispatch was allowed; policy changes while the specialist reasons.
        with patch("collaboration.governor.authorization_decision", return_value="deny"):
            result = await run(self.tasks, FixtureBackend("clean", 0), self.budget)
        self.assertFalse(result["accepted_envelopes"])
        self.assertTrue(all("CAPABILITY_DENIED" in a["reasons"] for a in result["assessments"]))

    async def test_replay_detects_changed_result_even_after_rehash(self):
        result = await run(self.tasks, FixtureBackend("clean", 0), self.budget)
        result["summary"]["spend_authorized"] = True
        result["artifact_sha256"] = digest({k: v for k, v in result.items() if k != "artifact_sha256"})
        with self.assertRaisesRegex(ValueError, "replay mismatch"):
            verify_artifact(result)

    async def test_checksum_detects_tampering(self):
        result = await run(self.tasks, FixtureBackend("clean", 0), self.budget)
        result["summary"]["state"] = "FORGED"
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_artifact(result)

    async def test_trace_missing_attempt_detected_after_rehash(self):
        result = await run(self.tasks, FixtureBackend("clean", 0), self.budget)
        result["events"] = [e for e in result["events"] if e["event"] != "ATTEMPT_STARTED"]
        for i, e in enumerate(result["events"], 1):
            e["sequence"] = i
        result["artifact_sha256"] = digest({k: v for k, v in result.items() if k != "artifact_sha256"})
        with self.assertRaisesRegex(ValueError, "without a start"):
            verify_artifact(result)

    async def test_artifact_round_trip_and_no_overwrite(self):
        result = await run(self.tasks, FixtureBackend("clean", 0), self.budget)
        path = Path(self.temp.name) / "run.json"
        write_artifact(path, result)
        self.assertTrue(verify_artifact(json.loads(path.read_text()))["verified"])
        with self.assertRaises(FileExistsError):
            write_artifact(path, result)

    async def test_forged_claim_event_detected_after_rehash(self):
        result = await run(self.tasks, FixtureBackend("invalid", 0), self.budget)
        blocked = next(e for e in result["events"] if e["event"] == "CLAIM_BLOCKED")
        blocked["event"] = "CLAIM_ELIGIBLE"
        result["artifact_sha256"] = digest({k: v for k, v in result.items() if k != "artifact_sha256"})
        with self.assertRaisesRegex(ValueError, "assessment trace"):
            verify_artifact(result)

    async def test_conflict_reconciliation_matches_sequential_baseline(self):
        tasks = build_tasks(self.db, conflict=True)
        parallel = await run(tasks, FixtureBackend("conflict", 0), self.budget)
        sequential = await run(tasks, FixtureBackend("conflict", 0), replace(self.budget, max_concurrency=1))
        self.assertEqual(parallel["summary"], sequential["summary"])
        self.assertEqual(parallel["summary"]["conflict_count"], 1)
        verify_artifact(parallel)


class BudgetTests(unittest.TestCase):
    def test_invalid_budgets_are_rejected(self):
        for kwargs in ({"max_concurrency": 0}, {"max_runs": True}, {"max_attempts": -1},
                       {"attempt_timeout": float("nan")}, {"attempt_timeout": float("inf")},
                       {"attempt_timeout": -1}, {"max_turns": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Budget(**kwargs)
