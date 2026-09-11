"""Execute governed metrics against the local warehouse."""

from pathlib import Path

import duckdb
import yaml


ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = ROOT / "semantic" / "metrics.yaml"
WAREHOUSE_PATH = ROOT / "warehouse" / "warehouse.duckdb"


def load_metric(metric_id):
    """Return the governed definition for a canonical metric ID."""
    with METRICS_PATH.open(encoding="utf-8") as source:
        metrics = yaml.safe_load(source)["metrics"]

    if metric_id not in metrics:
        raise KeyError(f"Unknown metric: {metric_id}")

    return metrics[metric_id]


def execute_metric_for_order(metric_id, order_id):
    """Execute a governed source metric at order grain."""
    metric = load_metric(metric_id)

    source = metric.get("source")
    if not source or "." not in source:
        raise ValueError(f"Metric {metric_id} does not define a direct source")

    table, column = source.split(".", 1)

    if metric.get("grain") != "order":
        raise ValueError(f"Metric {metric_id} is not defined at order grain")

    if metric.get("aggregation") != "sum":
        raise ValueError(f"Unsupported aggregation for metric {metric_id}")

    query = f"""
        SELECT SUM({column})
        FROM {table}
        WHERE order_id = ?
    """

    with duckdb.connect(str(WAREHOUSE_PATH), read_only=True) as connection:
        result = connection.execute(query, [order_id]).fetchone()

    return result[0]

