"""Collect independent control observations for seven explicit experiments."""

import json
from pathlib import Path
import sys

import duckdb

# Support direct execution with python evals/evidence.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policy.authorize import authorization_decision
from semantic.grain import introduces_fanout
from semantic.identity import resolve_identity
from semantic.resolve import find_dimension_ids, find_metric_ids
from semantic.temporal import has_temporal_mismatch


def observe_identity(entity_type, external_id):
    """Return identity and target facts for a store external identifier.

    Only unresolved external identifiers are handled as missing identities;
    metadata conflicts and warehouse errors propagate to the caller.
    """
    if entity_type != "store":
        raise ValueError("This evidence experiment supports only entity type 'store'.")

    try:
        canonical_id = resolve_identity(entity_type, external_id)
    except KeyError as error:
        if error.args != (external_id,):
            raise
        return {
            "identity_resolved": False,
            "canonical_id": None,
            "target_exists": False,
        }

    database = Path(__file__).resolve().parents[1] / "warehouse" / "warehouse.duckdb"
    with duckdb.connect(str(database), read_only=True) as connection:
        target_exists = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM stores WHERE store_id = ?)",
            [canonical_id],
        ).fetchone()[0]

    return {
        "identity_resolved": True,
        "canonical_id": canonical_id,
        "target_exists": target_exists,
    }


def collect_evidence():
    """Observe explicit experiment inputs without loading evaluation cases.

    Labels, relationship, temporal requirement, role, and capabilities are
    experiment inputs. All control results are obtained at collection time.
    Only the identity experiment queries the warehouse.
    """
    role = "regional_manager"
    return [
        {
            "case_id": "revenue_by_region_last_quarter",
            "observations": {
                "metric_matches": find_metric_ids("revenue"),
                "dimension_matches": find_dimension_ids("region"),
            },
        },
        {
            "case_id": "gross_revenue_order_5002",
            "observations": {
                "metric_matches": find_metric_ids("gross revenue"),
                "fanout_detected": introduces_fanout(
                    "gross_revenue", "sales_orders_to_order_items"
                ),
            },
        },
        {
            "case_id": "revenue_order_5001_ambiguous_metric",
            "observations": {
                "metric_matches": find_metric_ids("revenue"),
            },
        },
        {
            "case_id": "store_101_ambiguous_region",
            "observations": {
                "metric_matches": find_metric_ids("gross revenue"),
                "dimension_matches": find_dimension_ids("region"),
            },
        },
        {
            "case_id": "order_5003_missing_historical_state",
            "observations": {
                "metric_matches": find_metric_ids("gross revenue"),
                "dimension_matches": find_dimension_ids("state"),
                "temporal_mismatch": has_temporal_mismatch(
                    "customer_state", "historical"
                ),
            },
        },
        {
            "case_id": "vip_customer_details_unauthorized",
            "observations": {
                "role": role,
                "authorization": {
                    capability: authorization_decision(role, capability)
                    for capability in (
                        "customer_names", "customer_emails", "customer_level_spend"
                    )
                },
            },
        },
        {
            "case_id": "legacy_store_identifier_unresolved",
            "observations": observe_identity("store", "AUS-01"),
        },
    ]


if __name__ == "__main__":
    print(json.dumps(collect_evidence(), indent=2))
