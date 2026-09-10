"""Evaluate governed role/capability pairs without enforcing decisions."""

from pathlib import Path

import yaml


def authorization_decision(role, capability):
    """Return allow or deny; raise KeyError for unknowns, ValueError for conflicts."""
    path = Path(__file__).resolve().with_name("access.yaml")
    with path.open(encoding="utf-8") as source:
        governed_role = yaml.safe_load(source)["roles"][role]

    allowed = capability in governed_role["allowed"]
    denied = capability in governed_role["denied"]
    if allowed and denied:
        raise ValueError(f"Capability {capability!r} is both allowed and denied for role {role!r}.")
    if allowed:
        return "allow"
    if denied:
        return "deny"
    raise KeyError(capability)
