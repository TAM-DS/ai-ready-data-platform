"""Load and validate evaluation cases without evaluating SQL."""

from collections.abc import Mapping
from pathlib import Path
import sys

import yaml


def require_mapping(value, location):
    if not isinstance(value, Mapping):
        raise ValueError(f"{location} must be a mapping.")


def require_text(value, location):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} must be a non-empty string.")


def validate_cases(document):
    """Return the valid case count, or raise ValueError with field context."""
    require_mapping(document, "Document")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list of case mappings.")

    seen_ids = set()
    for index, case in enumerate(cases):
        location = f"cases[{index}]"
        require_mapping(case, location)
        case_id = case.get("id")
        require_text(case_id, f"{location}.id")
        if case_id in seen_ids:
            raise ValueError(f"{location}.id duplicates {case_id!r}; IDs must be unique.")
        seen_ids.add(case_id)
        require_text(case.get("question"), f"{location}.question")

        expected = case.get("expected")
        require_mapping(expected, f"{location}.expected")
        behavior = expected.get("behavior")
        if not isinstance(behavior, str) or behavior not in ("answer", "clarify", "refuse"):
            raise ValueError(f"{location}.expected.behavior must be answer, clarify, or refuse.")
        root_causes = expected.get("root_causes")
        if not isinstance(root_causes, list) or not root_causes:
            raise ValueError(f"{location}.expected.root_causes must be a non-empty list.")
        seen_root_causes = set()
        for cause_index, cause in enumerate(root_causes):
            cause_location = f"{location}.expected.root_causes[{cause_index}]"
            if not isinstance(cause, str) or cause not in (
                "metric", "grain", "dimension", "temporal", "security", "identity"
            ):
                raise ValueError(
                    f"{cause_location} must be metric, grain, dimension, temporal, security, or identity."
                )
            if cause in seen_root_causes:
                raise ValueError(f"{cause_location} duplicates {cause!r}; root causes must be unique.")
            seen_root_causes.add(cause)
        for field in ("metric", "time_filter"):
            if field in expected:
                require_text(expected[field], f"{location}.expected.{field}")
        if "dimensions" in expected:
            dimensions = expected["dimensions"]
            if not isinstance(dimensions, list):
                raise ValueError(f"{location}.expected.dimensions must be a list of strings.")
            for dimension_index, dimension in enumerate(dimensions):
                require_text(dimension, f"{location}.expected.dimensions[{dimension_index}]")

        evaluation = case.get("evaluation")
        require_mapping(evaluation, f"{location}.evaluation")
        for field in ("execution_required", "security_compliant"):
            if not isinstance(evaluation.get(field), bool):
                raise ValueError(f"{location}.evaluation.{field} must be a boolean (true or false).")

    return len(cases)


def main():
    path = Path(__file__).resolve().with_name("cases.yaml")
    try:
        with path.open(encoding="utf-8") as source:
            document = yaml.safe_load(source)
        count = validate_cases(document)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as error:
        print(f"Validation failed for {path}: {error}", file=sys.stderr)
        return 1

    print(f"Validation successful: {count} valid case(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
