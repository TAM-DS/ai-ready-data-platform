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


def score_clarification_behavior(justified, observed):
    interventions = justified["interventions"]
    clarification_justified = any(
        item["justification"] == "CLARIFY"
        for item in interventions
    )

    if not clarification_justified:
        return False, "Clarification was not independently justified."

    action = observed["observed_behavior"]["action"]

    if action != "CLARIFY":
        return False, (
            f"Clarification was justified, but observed action was {action}."
        )

    return True, "Observed behavior matches independently justified clarification."
