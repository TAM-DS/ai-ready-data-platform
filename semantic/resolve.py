"""Resolve explicit governed metric labels to canonical metric IDs."""

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
