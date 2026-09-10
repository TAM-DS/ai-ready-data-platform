"""Run explicit deterministic control evidence checks, without AI or SQL."""

from pathlib import Path
import sys

# Support direct execution with python evals/controls.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policy.authorize import authorization_decision
from semantic.grain import introduces_fanout
from semantic.identity import resolve_identity
from semantic.resolve import find_dimension_ids, find_metric_ids
from semantic.temporal import has_temporal_mismatch


def main():
    checks = [
        ("metric: gross revenue", find_metric_ids, ("gross revenue",), ["gross_revenue"]),
        ("metric: revenue", find_metric_ids, ("revenue",), []),
        ("grain: sales_orders_to_order_items", introduces_fanout,
         ("gross_revenue", "sales_orders_to_order_items"), True),
        ("dimension: business region", find_dimension_ids,
         ("business region",), ["business_region"]),
        ("dimension: region", find_dimension_ids, ("region",), []),
        ("temporal: customer_state historical", has_temporal_mismatch,
         ("customer_state", "historical"), True),
        ("security: regional_manager customer_emails", authorization_decision,
         ("regional_manager", "customer_emails"), "deny"),
        ("identity: store AUS-01", resolve_identity, ("store", "AUS-01"), 101),
    ]
    passed = 0
    total = len(checks) + 1
    for label, control, arguments, expected in checks:
        observed = control(*arguments)
        matches = observed is expected if isinstance(expected, bool) else observed == expected
        if matches:
            passed += 1
            print(f"PASS {label}: {observed!r}")
        else:
            print(f"FAIL {label}: expected {expected!r}, observed {observed!r}")

    try:
        observed = resolve_identity("store", "AUS001")
    except KeyError:
        passed += 1
        print("PASS identity: store AUS001: KeyError (unresolved)")
    else:
        print(f"FAIL identity: store AUS001: expected KeyError, observed {observed!r}")

    print(f"Summary: {passed}/{total} checks passed.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
