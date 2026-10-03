"""Collect scoped, non-identifying facts from the existing synthetic warehouse.

Models never receive SQL, a database connection, names, or email addresses.
The application owns evidence collection and task/role binding.
"""

from dataclasses import replace
from pathlib import Path

import duckdb

from collaboration.contracts import Fact, Task, NO_SPEND
from execution.execute import load_metric
from semantic.grain import introduces_fanout
from semantic.identity import resolve_identity
from semantic.temporal import has_temporal_mismatch


ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = ROOT / "warehouse" / "warehouse.duckdb"
ROLES = {
    "regional_sales_manager": ("regional_manager", "aggregate_regional_sales"),
    "customer_analytics": ("customer_analytics", "aggregate_customer_behavior"),
    "store_operations": ("store_operations", "store_performance_analysis"),
}


def build_tasks(database: Path = WAREHOUSE, *, conflict: bool = False) -> tuple[Task, ...]:
    """Read one consistent snapshot using fixed, parameterized queries."""
    metric = load_metric("gross_revenue")
    if (metric["source"], metric["grain"], metric["aggregation"]) != (
            "sales_orders.gross_amount", "order", "sum"):
        raise ValueError("The fixture query no longer matches the governed metric")
    store_id = resolve_identity("store", "AUS-01")
    with duckdb.connect(str(database), read_only=True) as db:
        db.execute("BEGIN TRANSACTION")
        gross = db.execute("""
            SELECT SUM(gross_amount) FROM sales_orders
            WHERE store_id = ? AND order_date >= ? AND order_date < ?
        """, [store_id, "2026-09-01", "2026-10-01"]).fetchone()[0]
        vip = db.execute("""
            SELECT SUM(o.gross_amount) FROM sales_orders o
            JOIN customers c ON o.customer_id = c.customer_id
            WHERE o.store_id = ? AND o.order_date >= ? AND o.order_date < ?
              AND c.loyalty_tier = ?
        """, [store_id, "2026-09-01", "2026-10-01", "VIP"]).fetchone()[0]
        region = db.execute("""
            SELECT r.region_name FROM stores s
            JOIN business_regions r USING (business_region_id)
            WHERE s.store_id = ?
        """, [store_id]).fetchone()
        db.execute("COMMIT")
    if gross is None or vip is None or region is None:
        raise ValueError("Required synthetic evidence is missing")
    if not introduces_fanout("gross_revenue", "sales_orders_to_order_items"):
        raise ValueError("The documented fanout risk changed")
    if not has_temporal_mismatch("store_business_region", "historical"):
        raise ValueError("The documented temporal contract changed")

    total = Fact(
        "store_gross", f"{gross:.2f}", "gross_revenue", "order", "2026-09",
        f"store:{store_id}", "observed", "sales_orders; order-grain SUM; September 2026",
        f"September 2026 gross revenue for store {store_id} is {gross:.2f} in the synthetic warehouse.",
        (NO_SPEND, "Do not reinterpret gross_revenue as net_revenue.",
         "Order-grain monetary amounts must not be summed after an item-grain join."),
    )
    cohort = Fact(
        "vip_gross", f"{vip:.2f}", "gross_revenue", "order", "2026-09",
        f"store:{store_id};cohort:current_VIP", "observed",
        "sales_orders joined to customers; current VIP classification; aggregate only",
        f"September 2026 gross revenue from the currently classified VIP cohort for store {store_id} is {vip:.2f} in the synthetic warehouse.",
        (NO_SPEND, "No customer names, emails, or individual spend may be disclosed.",
         "Current VIP classification does not establish historical VIP membership."),
    )
    current = Fact(
        "current_region", str(region[0]), None, "store", "current",
        f"store:{store_id};attribute:business_region", "current_attribute",
        "stores.business_region_id joined to business_regions; current assignment",
        f"Store {store_id} currently belongs to {region[0]}; its historical assignment is not established.",
        (NO_SPEND, "A current region assignment does not establish historical region membership."),
    )
    store_total = replace(total, fact_id="store_gross_confirmation")
    if conflict:
        # Explicit contradictory-source fixture, never a claim about the warehouse.
        store_total = replace(
            store_total, value="120.00", source="Injected contradictory-source fixture",
            canonical_claim=f"An injected source observation reports 120.00 for store {store_id} in September 2026.",
        )
    question = (
        "Prepare a bounded executive review of September 2026 store performance. "
        "Keep customer information aggregated, distinguish current region from historical truth, "
        "and preserve that reporting does not authorize spending."
    )
    facts = {
        "regional_sales_manager": (total,),
        "customer_analytics": (cohort,),
        "store_operations": (store_total, current),
    }
    return tuple(Task(agent, role, capability, question, facts[agent])
                 for agent, (role, capability) in ROLES.items())
