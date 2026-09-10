"""Observe governed store identity resolution and warehouse target existence."""

from pathlib import Path
import sys

import duckdb

# Support direct execution with python evals/evidence.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from semantic.identity import resolve_identity


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


if __name__ == "__main__":
    for fact, value in observe_identity("store", "AUS-01").items():
        print(f"{fact} = {value!r}")
