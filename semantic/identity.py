"""Resolve external identifiers using explicit governed identity mappings."""

from pathlib import Path

import yaml


def resolve_identity(entity_type, external_id):
    """Return the canonical ID for an exact external identifier match.

    Unknown entity types or external identifiers raise KeyError. Conflicting
    mappings within the requested entity type raise ValueError.
    """
    path = Path(__file__).resolve().with_name("identities.yaml")
    with path.open(encoding="utf-8") as source:
        mappings = yaml.safe_load(source)["identities"][entity_type]

    identities = {}
    for mapping in mappings:
        identifier = mapping["external_id"]
        canonical_id = mapping["canonical_id"]
        if identifier in identities and identities[identifier] != canonical_id:
            raise ValueError(
                f"Conflicting identity mappings for {entity_type!r}: {identifier!r}"
            )
        identities[identifier] = canonical_id

    return identities[external_id]
