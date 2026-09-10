"""Detect metric-grain fanout in a single governed relationship traversal."""

from pathlib import Path

import yaml


def introduces_fanout(metric_id, relationship_id):
    """Detect left-to-right one-to-many fanout below a metric's declared grain.

    False means this specific risk was not detected, not that a query is safe.
    Unknown IDs or missing required metadata raise KeyError.
    """
    directory = Path(__file__).resolve().parent
    with (directory / "metrics.yaml").open(encoding="utf-8") as source:
        metric = yaml.safe_load(source)["metrics"][metric_id]
    with (directory / "relationships.yaml").open(encoding="utf-8") as source:
        relationship = yaml.safe_load(source)["relationships"][relationship_id]

    metric_grain = metric["grain"]
    left_grain = relationship["grain"]["left"]
    right_grain = relationship["grain"]["right"]
    return (
        relationship["cardinality"] == "one_to_many"
        and metric_grain == left_grain
        and right_grain != metric_grain
    )
