"""Application lifecycle states, transitions, and durable search suppression rules."""

from __future__ import annotations


APPLICATION_STATES = (
    "new",
    "saved",
    "ready_to_apply",
    "applying",
    "applied",
    "interviewing",
    "offer",
    "accepted",
    "declined",
    "rejected",
    "withdrawn",
    "closed",
)

TERMINAL_STATES = {"accepted", "declined", "rejected", "withdrawn", "closed"}

# Roles in these states should not be rediscovered. ``saved`` and
# ``ready_to_apply`` remain visible because the candidate has not applied yet.
SEARCH_SUPPRESSION_STATES = {
    "applying",
    "applied",
    "interviewing",
    "offer",
    "accepted",
    "declined",
    "rejected",
    "withdrawn",
    "closed",
}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "new": {"saved", "ready_to_apply", "applied", "closed", "withdrawn"},
    "saved": {"new", "ready_to_apply", "applying", "applied", "closed", "withdrawn"},
    "ready_to_apply": {"saved", "applying", "applied", "closed", "withdrawn"},
    "applying": {"saved", "ready_to_apply", "applied", "closed", "withdrawn"},
    "applied": {"interviewing", "offer", "rejected", "withdrawn"},
    "interviewing": {"offer", "rejected", "withdrawn"},
    "offer": {"accepted", "declined", "withdrawn"},
    "accepted": set(),
    "declined": set(),
    "rejected": set(),
    "withdrawn": set(),
    "closed": set(),
}


def validate_transition(current: str, target: str, *, force: bool = False) -> None:
    """Raise for an unknown or invalid lifecycle transition.

    ``force`` exists only for explicit manual corrections; production agent code
    should follow the normal graph.
    """
    if target not in APPLICATION_STATES:
        raise ValueError(f"Unknown application state: {target}")
    if current not in APPLICATION_STATES:
        raise ValueError(f"Stored application state is unknown: {current}")
    if force or current == target:
        return
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(
            f"Invalid application transition: {current} -> {target}. "
            "Use --force only to correct reviewed historical data."
        )
