"""Deterministic, no-LLM program quality floor.

Reuses the shared volume table (via :func:`compute_muscle_volume`) so
``VOLUME_GUIDELINES`` does double duty as ground truth. Returns a list of
human-readable problems; an empty list means the program passed.

Used by the Week-1 generator to take one re-generation pass when a draft is
structurally broken or its prescribed per-muscle volume falls outside the level's
ranges — gated behind ``config.VOLUME_VERIFIER_ENABLED`` (off by default).

NOTE: the volume bounds are coarse heuristics; on real split routines some patterns
will sit below the per-pattern minimum legitimately. Treat this as experimental and
tune which deviations should force a re-generation before enabling it in production.
"""
from __future__ import annotations

from .analytics import compute_muscle_volume

_REQUIRED_FIELDS = ("name", "sets", "reps")


def verify_program(formatted: dict, level: str | None = None) -> list[str]:
    """Return a list of problems with a formatted program (empty == passed).

    Parameters
    ----------
    formatted:
        The Editor's output: ``{"weekly_program": {...}, "level": ...}``.
    level:
        Experience level for the volume bounds. Falls back to the program's own
        ``level`` field, then ``intermediate``.
    """
    weekly = (formatted or {}).get("weekly_program") or {}
    if not weekly:
        return ["program has no training days"]

    problems: list[str] = []

    # Structural checks: non-empty days, required fields present.
    non_empty_days = 0
    for day, exercises in weekly.items():
        if not exercises:
            problems.append(f"{day} has no exercises")
            continue
        non_empty_days += 1
        for i, ex in enumerate(exercises):
            missing = [f for f in _REQUIRED_FIELDS if not ex.get(f)]
            if missing:
                problems.append(f"{day} exercise {i} missing {', '.join(missing)}")
    if non_empty_days == 0:
        problems.append("program has no non-empty training days")

    # Per-muscle weekly volume vs the level's guidelines.
    resolved_level = level or (formatted or {}).get("level") or "intermediate"
    for row in compute_muscle_volume(weekly, resolved_level):
        if row["status"] == "under":
            problems.append(f"{row['key']} volume {row['sets']} below min {row['min']}")
        elif row["status"] == "over":
            problems.append(f"{row['key']} volume {row['sets']} above max {row['max']}")

    return problems
