"""Resolve explicit governed metric and dimension labels to canonical IDs."""

from pathlib import Path
import re

import yaml


def find_metric_ids(question):
    """Return metric IDs whose governed labels are explicitly present in a question."""
    path = Path(__file__).resolve().with_name("metrics.yaml")
    with path.open(encoding="utf-8") as source:
        metrics = yaml.safe_load(source)["metrics"]

    matches = []
    for metric_id, metric in metrics.items():
        if re.search(
            r"(?<!\w)" + re.escape(metric["label"]) + r"(?!\w)",
            question,
            re.IGNORECASE,
        ):
            matches.append(metric_id)
    return matches


def find_dimension_ids(question):
    """Return dimension IDs whose governed labels are explicitly present in a question."""
    path = Path(__file__).resolve().with_name("dimensions.yaml")
    with path.open(encoding="utf-8") as source:
        dimensions = yaml.safe_load(source)["dimensions"]

    matches = []
    for dimension_id, dimension in dimensions.items():
        if re.search(
            r"(?<!\w)" + re.escape(dimension["label"]) + r"(?!\w)",
            question,
            re.IGNORECASE,
        ):
            matches.append(dimension_id)
    return matches
