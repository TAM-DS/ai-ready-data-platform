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
        for field in ("metric", "time_filter"):
            require_text(expected.get(field), f"{location}.expected.{field}")
        dimensions = expected.get("dimensions")
        if not isinstance(dimensions, list):
            raise ValueError(f"{location}.expected.dimensions must be a list of strings.")
        for dimension_index, dimension in enumerate(dimensions):
            require_text(dimension, f"{location}.expected.dimensions[{dimension_index}]")

        evaluation = case.get("evaluation")
        require_mapping(evaluation, f"{location}.evaluation")
        for field in ("execution_required", "security_compliant", "refusal_expected"):
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
