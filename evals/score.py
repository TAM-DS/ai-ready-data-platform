def score_identity_evidence(observed, expected):
    expected_id = expected["canonical_id"]

    if not observed["identity_resolved"]:
        return False, "Identity was not resolved."

    if not observed["target_exists"]:
        return False, "Resolved canonical target does not exist."

    if observed["canonical_id"] != expected_id:
        return False, (
            f"Observed canonical_id {observed['canonical_id']} "
            f"does not match expected canonical_id {expected_id}."
        )

    return True, "Observed identity evidence matches expected canonical identity."
