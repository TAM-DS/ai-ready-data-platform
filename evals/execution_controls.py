"""Run deterministic governed execution evidence checks."""

from pathlib import Path
import sys

# Support direct execution with python evals/execution_controls.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution.execute import execute_metric_for_order


def main():
    passed = 0
    total = 3

    expected = 100
    observed = execute_metric_for_order("gross_revenue", 5002)

    if observed == expected:
        passed += 1
        print(f"PASS execution: gross_revenue order 5002: {observed!r}")
    else:
        print(
            f"FAIL execution: gross_revenue order 5002: "
            f"expected {expected!r}, observed {observed!r}"
        )

    try:
        execute_metric_for_order("fake_metric", 5002)
    except KeyError:
        passed += 1
        print("PASS execution: fake_metric: KeyError")
    else:
        print("FAIL execution: fake_metric: expected KeyError")

    try:
        execute_metric_for_order("net_revenue", 5002)
    except ValueError:
        passed += 1
        print("PASS execution: net_revenue: ValueError (unsupported execution form)")
    else:
        print("FAIL execution: net_revenue: expected ValueError")

    print(f"Summary: {passed}/{total} checks passed.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
