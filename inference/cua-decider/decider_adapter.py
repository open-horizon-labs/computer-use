"""Decider provider for Cua Driver's immutable candidate interface.

Only selects an allowlisted ID. Observation, action execution and independent
verification remain in Cua Driver's jev-use loop.
"""

import json
import math
import os
from urllib.request import Request, urlopen

DEFAULT_URL = "http://192.168.1.104:8010"


def validate_answer(answer, criteria):
    selected = answer.get("choice")
    probabilities = answer.get("probabilities")
    confidence = answer.get("confidence")
    if answer.get("method") == "single_position_logits":
        scores = answer.get("scores")
        if (selected not in criteria or confidence is not None or probabilities is not None
            or answer.get("requires_verification") is not True or answer.get("calibrated") is not False
            or answer.get("thinking") is not False or answer.get("output_positions") != 1
            or not isinstance(scores, dict) or set(scores) != set(criteria)
            or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in scores.values())
            or abs(sum(scores.values())-1) > .0001 or scores[selected] != max(scores.values())):
            raise ValueError("Invalid direct scorer response")
        return selected, None, None
    if (selected in criteria and confidence is None and probabilities is None
        and answer.get("method") == "constrained_generation"
        and answer.get("requires_verification") is True):
        return selected, None, None
    if (
        selected not in criteria
        or not isinstance(probabilities, dict)
        or set(probabilities) != set(criteria)
    ):
        raise ValueError(
            "Decider returned an unknown choice or incomplete candidate distribution"
        )
    values = [confidence, *probabilities.values()]
    if any(
        isinstance(x, bool)
        or not isinstance(x, (int, float))
        or not math.isfinite(x)
        or not 0 <= x <= 1
        for x in values
    ):
        raise ValueError("Invalid Decider probabilities")
    # Upstream rounds probabilities to four decimal places (up to 32 options).
    if abs(sum(probabilities.values()) - 1) > len(criteria) * 0.000051:
        raise ValueError("Decider distribution does not sum to one")
    if abs(confidence - probabilities[selected]) > 0.00011 or confidence < max(
        probabilities.values()
    ):
        raise ValueError("Decider choice and confidence disagree")
    return selected, confidence, probabilities


def choose(state, criteria, *, instructions, url=None):
    if not 2 <= len(criteria) <= 32 or not {"reobserve", "abstain"} <= criteria.keys():
        raise ValueError("Expected 2..32 candidates including reobserve and abstain")
    payload = {
        "state": state,
        "questions": {
            "driver_action": {
                "type": "choice",
                "instructions": instructions,
                "criteria": criteria,
            }
        },
    }
    endpoint = (url or os.environ.get("DECIDER_URL", DEFAULT_URL)).rstrip("/")
    request = Request(
        endpoint + "/v1/systemone",
        json.dumps(payload).encode(),
        {"Content-Type": "application/json"},
    )
    # Never retry a decision/action implicitly after uncertain execution.
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    return validate_answer(result["answers"]["driver_action"], criteria)


def choose_decider(candidates, snapshot, visual, history):
    from jev_adapter import visual_decision_state

    criteria = {c.id: c.description for c in candidates}
    if len(criteria) != len(candidates):
        raise ValueError("Duplicate candidate IDs")
    return choose(
        {
            "goal": "Enter the verification token, then submit the form.",
            "observation": {
                "page": snapshot.get("page"),
                "outline": snapshot.get("outline"),
                "visual": visual_decision_state(visual),
            },
            "history": history,
        },
        criteria,
        instructions="Which complete executable action should Cua Driver run next?",
    )
