"""Immutable application-owned inputs; model replies remain candidates."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math


NO_SPEND = "No funds may be committed from this claim."


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


@dataclass(frozen=True)
class Fact:
    fact_id: str
    value: str
    metric_id: str | None
    grain: str
    time_basis: str
    scope: str
    kind: str
    source: str
    canonical_claim: str
    restrictions: tuple[str, ...] = (NO_SPEND,)

    def __post_init__(self):
        for name in ("fact_id", "value", "grain", "time_basis", "scope", "kind", "source", "canonical_claim"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"Invalid fact field: {name}")
        if self.metric_id is not None and not isinstance(self.metric_id, str):
            raise ValueError("Invalid fact metric")
        if (not isinstance(self.restrictions, tuple) or NO_SPEND not in self.restrictions
                or not all(isinstance(s, str) for s in self.restrictions)):
            raise ValueError("Facts must retain immutable no-spend restrictions")

    @property
    def semantic_key(self) -> tuple:
        # Provenance is intentionally separate from semantic identity.
        return (self.metric_id, self.grain, self.time_basis, self.scope, self.kind)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Task:
    agent_id: str
    role: str
    capability: str
    question: str
    facts: tuple[Fact, ...]

    def __post_init__(self):
        if not isinstance(self.facts, tuple) or not all(isinstance(f, Fact) for f in self.facts):
            raise ValueError("Task facts must be immutable Fact instances")
        if not isinstance(self.question, str) or not self.question:
            raise ValueError("Task question must be nonempty text")

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def input_digest(self) -> str:
        return digest(self.to_dict())


@dataclass(frozen=True)
class Candidate:
    fact_id: str
    value: str
    metric_id: str | None
    grain: str
    time_basis: str
    kind: str
    requested_capability: str
    spend_authorized: bool
    restrictions: tuple[str, ...]
    model_claim: str

    @classmethod
    def from_dict(cls, data: dict) -> "Candidate":
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Candidate fields do not match the contract")
        for field in ("fact_id", "value", "grain", "time_basis", "kind",
                      "requested_capability", "model_claim"):
            if not isinstance(data[field], str) or not data[field] or len(data[field]) > 1000:
                raise ValueError(f"Invalid candidate field: {field}")
        if data["metric_id"] is not None and (
                not isinstance(data["metric_id"], str) or not 1 <= len(data["metric_id"]) <= 1000):
            raise ValueError("Invalid metric identity")
        if type(data["spend_authorized"]) is not bool:
            raise ValueError("Spend authority must be a Boolean")
        restrictions = data["restrictions"]
        if (not isinstance(restrictions, (list, tuple)) or len(restrictions) > 20
                or not all(isinstance(s, str) and len(s) <= 1000 for s in restrictions)):
            raise ValueError("Invalid restrictions")
        return cls(**{**data, "restrictions": tuple(restrictions)})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Budget:
    max_concurrency: int = 3
    max_attempts: int = 2
    max_runs: int = 6
    attempt_timeout: float = 5.0
    max_turns: int = 3
    max_output_tokens: int = 1000
    max_candidates: int = 4

    def __post_init__(self):
        for field in ("max_concurrency", "max_attempts", "max_runs", "max_turns",
                      "max_output_tokens", "max_candidates"):
            if type(getattr(self, field)) is not int or getattr(self, field) < 1:
                raise ValueError(f"{field} must be a positive integer")
        if (isinstance(self.attempt_timeout, bool)
                or not math.isfinite(self.attempt_timeout) or self.attempt_timeout <= 0):
            raise ValueError("Timeout must be finite and positive")


class RetryableAgentError(Exception):
    """Only transport failures and timeouts may consume a bounded retry."""
