"""Demonstrate compositional risk and a governed trust boundary.

This experiment compares a technically valid lower-grain join path with the
governed order-grain execution path for the same metric and order.

The trust-boundary decision is based on governed fanout evidence, not on the
expected numeric result.
"""

import json
from decimal import Decimal
from pathlib import Path
import sys

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution.execute import execute_metric_for_order
from semantic.grain import introduces_fanout


ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_PATH = ROOT / "warehouse" / "warehouse.duckdb"

METRIC_ID = "gross_revenue"
ORDER_ID = 5002
RELATIONSHIP_ID = "sales_orders_to_order_items"

ARTIFACT_PATH = (
    Path(__file__).resolve().parent / "composition_trust_boundary.json"
)


def execute_unsafe_composition():
    """Execute a valid join that repeats an order-grain metric across item rows."""
    query = """
        SELECT SUM(so.gross_amount)
        FROM sales_orders AS so
        JOIN order_items AS oi
          ON so.order_id = oi.order_id
        WHERE so.order_id = ?
    """

    with duckdb.connect(str(WAREHOUSE_PATH), read_only=True) as connection:
        result = connection.execute(query, [ORDER_ID]).fetchone()

    return result[0]


def trust_boundary_decision(fanout_detected):
    """Decide whether the lower-grain result may cross this trust boundary."""
    if fanout_detected:
        return "BLOCK_UNJUSTIFIED_RESULT"

    return "NO_FANOUT_BLOCK_DETECTED"


def run_experiment():
    """Compare unsafe composition with governed execution and record evidence."""
    fanout_detected = introduces_fanout(
        METRIC_ID,
        RELATIONSHIP_ID,
    )

    unsafe_result = execute_unsafe_composition()
    governed_result = execute_metric_for_order(
        METRIC_ID,
        ORDER_ID,
    )

    trust_decision = trust_boundary_decision(fanout_detected)

    difference = unsafe_result - governed_result

    if governed_result == 0:
        amplification_factor = None
    else:
        amplification_factor = unsafe_result / governed_result

    return {
        "experiment": "composition_trust_boundary",
        "metric_id": METRIC_ID,
        "order_id": ORDER_ID,
        "relationship_id": RELATIONSHIP_ID,
        "observations": {
            "unsafe_composition": {
                "execution_succeeded": True,
                "result": str(unsafe_result),
                "path": "sales_orders JOIN order_items",
            },
            "governed_execution": {
                "execution_succeeded": True,
                "result": str(governed_result),
                "path": "execute_metric_for_order",
            },
            "fanout_detected": fanout_detected,
            "difference": str(difference),
            "amplification_factor": (
                str(amplification_factor)
                if amplification_factor is not None
                else None
            ),
        },
        "trust_boundary": {
            "unsafe_result_decision": trust_decision,
            "unsafe_result_eligible_for_propagation": (
                trust_decision != "BLOCK_UNJUSTIFIED_RESULT"
            ),
            "governed_result_eligible_for_this_boundary": True,
        },
    }


def main():
    if ARTIFACT_PATH.exists():
        raise FileExistsError(
            f"Composition artifact already exists: {ARTIFACT_PATH}"
        )

    observation = run_experiment()

    ARTIFACT_PATH.write_text(
        json.dumps(observation, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(observation, indent=2))


if __name__ == "__main__":
    main()
