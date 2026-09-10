"""Detect mismatches between declared and required temporal semantics."""

from pathlib import Path

import yaml


def has_temporal_mismatch(attribute_id, required_temporal_semantics):
    """Return whether an attribute's declared temporal semantics differ.

    False means the semantics match, not that a complete query is safe or
    historically answerable. Unknown attribute IDs raise KeyError.
    """
    path = Path(__file__).resolve().with_name("attributes.yaml")
    with path.open(encoding="utf-8") as source:
        attribute = yaml.safe_load(source)["attributes"][attribute_id]
    return attribute["temporal_semantics"] != required_temporal_semantics
