"""Pure-Python training analytics — no LLM calls.

Computes per-exercise and global metrics from accumulated weekly training
records to determine whether a normal progression, deload, or mesocycle
review is warranted.
"""
from __future__ import annotations

import logging
from typing import Any

from config import STAGNATION_THRESHOLD_WEEKS, MOVEMENT_PATTERNS, VOLUME_GUIDELINES

logger = logging.getLogger(__name__)


def _extract_exercise_history(weeks: list[dict]) -> dict[str, list[dict]]:
    """Group per-set feedback by exercise name across all weeks.

    Returns {exercise_name: [{week, max_weight, max_reps, avg_rir}, ...]}
    """
    history: dict[str, list[dict]] = {}
    for record in weeks:
        feedback = record.get("feedback") or {}
        for day, exercises in feedback.items():
            for ex in exercises:
                name = ex.get("name")
                if not name:
                    continue
                sets = ex.get("sets_data", [])
                if not sets:
                    continue

                weights, reps, rirs = [], [], []
                for s in sets:
                    try:
                        w = float(s.get("weight", 0) or 0)
                        r = float(s.get("reps", 0) or 0)
                        weights.append(w)
                        reps.append(r)
                    except (ValueError, TypeError):
                        pass
                    try:
                        rir = float(s.get("actual_rir", 0) or 0)
                        if rir > 0:
                            rirs.append(rir)
                    except (ValueError, TypeError):
                        pass

                if not weights:
                    continue

                history.setdefault(name, []).append({
                    "week": record.get("week", 0),
                    "max_weight": max(weights),
                    "max_reps": max(reps),
                    "avg_rir": sum(rirs) / len(rirs) if rirs else 0.0,
                })
    return history


def _compute_stagnation(entries: list[dict]) -> int:
    """Count consecutive weeks (from the end) with no weight or rep increase."""
    if len(entries) < 2:
        return 0
    stagnation = 0
    for i in range(len(entries) - 1, 0, -1):
        curr = entries[i]
        prev = entries[i - 1]
        if curr["max_weight"] > prev["max_weight"] or curr["max_reps"] > prev["max_reps"]:
            break
        stagnation += 1
    return stagnation


def _compute_rir_trend(entries: list[dict]) -> str:
    """Determine RIR direction: 'rising' (easier), 'falling' (harder = fatigue signal), or 'stable'."""
    rirs = [e["avg_rir"] for e in entries if e["avg_rir"] > 0]
    if len(rirs) < 2:
        return "stable"
    first_half = sum(rirs[: len(rirs) // 2]) / (len(rirs) // 2)
    second_half = sum(rirs[len(rirs) // 2 :]) / (len(rirs) - len(rirs) // 2)
    diff = second_half - first_half
    if diff > 0.5:
        return "rising"
    if diff < -0.5:
        return "falling"
    return "stable"


def compute_exercise_metrics(weeks: list[dict]) -> dict[str, dict[str, Any]]:
    """Compute per-exercise metrics from weekly training records.

    Parameters
    ----------
    weeks:
        List of enriched weekly records, each with 'feedback' containing
        per-exercise sets_data.

    Returns
    -------
    dict
        {exercise_name: {stagnation_weeks, rir_trend, load_progression, flag}}
    """
    history = _extract_exercise_history(weeks)
    metrics: dict[str, dict[str, Any]] = {}

    for name, entries in history.items():
        entries.sort(key=lambda e: e["week"])
        stagnation = _compute_stagnation(entries)
        rir_trend = _compute_rir_trend(entries)
        load_start = entries[0]["max_weight"]
        load_end = entries[-1]["max_weight"]

        flag = "stalled" if stagnation >= STAGNATION_THRESHOLD_WEEKS else "progressing"

        metrics[name] = {
            "stagnation_weeks": stagnation,
            "rir_trend": rir_trend,
            "load_progression": load_end - load_start,
            "flag": flag,
        }

    return metrics


def compute_global_metrics(
    exercise_metrics: dict[str, dict[str, Any]],
    weeks: list[dict],
) -> dict[str, Any]:
    """Compute global training metrics across all exercises.

    Parameters
    ----------
    exercise_metrics:
        Output of compute_exercise_metrics().
    weeks:
        The weekly records (used for per-week average RIR calculation).

    Returns
    -------
    dict
        {avg_rir_trend, fatigue_score, stalled_exercise_ratio}
    """
    # Per-week average RIR across all exercises
    weekly_rirs: list[float] = []
    for record in weeks:
        feedback = record.get("feedback") or {}
        all_rirs: list[float] = []
        for day_exercises in feedback.values():
            for ex in day_exercises:
                for s in ex.get("sets_data", []):
                    try:
                        rir = float(s.get("actual_rir", 0) or 0)
                        if rir > 0:
                            all_rirs.append(rir)
                    except (ValueError, TypeError):
                        pass
        if all_rirs:
            weekly_rirs.append(sum(all_rirs) / len(all_rirs))

    # Average RIR trend (falling RIR = fatigue signal)
    rir_diff = 0.0
    if len(weekly_rirs) >= 2:
        first = sum(weekly_rirs[: len(weekly_rirs) // 2]) / (len(weekly_rirs) // 2)
        second = sum(weekly_rirs[len(weekly_rirs) // 2 :]) / (len(weekly_rirs) - len(weekly_rirs) // 2)
        rir_diff = second - first
        if rir_diff > 0.5:
            avg_rir_trend = "rising"
        elif rir_diff < -0.5:
            avg_rir_trend = "falling"
        else:
            avg_rir_trend = "stable"
    else:
        avg_rir_trend = "stable"

    # Stalled exercise ratio
    total = len(exercise_metrics)
    stalled = sum(1 for m in exercise_metrics.values() if m["flag"] == "stalled")
    stalled_ratio = stalled / total if total > 0 else 0.0

    # RIR fall component (0..1): how much average RIR fell, capped at 2.0 RIR drop
    rir_fall = 0.0
    if len(weekly_rirs) >= 2:
        rir_fall = min(max(-rir_diff, 0.0) / 2.0, 1.0)

    # Rep decline component: approximate with stalled_ratio
    rep_decline = stalled_ratio

    # Fatigue score composite
    fatigue = (0.4 * rir_fall) + (0.3 * rep_decline) + (0.3 * stalled_ratio)
    fatigue = min(fatigue, 1.0)

    return {
        "avg_rir_trend": avg_rir_trend,
        "fatigue_score": round(fatigue, 3),
        "stalled_exercise_ratio": round(stalled_ratio, 3),
    }


def decide_review_type(
    global_metrics: dict[str, Any],
    week_in_mesocycle: int,
    mesocycle_length: int,
) -> dict[str, Any]:
    """Decide whether this week is normal, deload, or mesocycle review.

    Parameters
    ----------
    global_metrics:
        Output of compute_global_metrics().
    week_in_mesocycle:
        Current position in the mesocycle (1-indexed).
    mesocycle_length:
        Total weeks in the mesocycle.

    Returns
    -------
    dict
        {review_type: str, triggers: list[str]}
    """
    from config import FATIGUE_SCORE_DELOAD_TRIGGER, STALL_RATIO_REVIEW_TRIGGER

    triggers: list[str] = []
    fatigue = global_metrics["fatigue_score"]
    stall_ratio = global_metrics["stalled_exercise_ratio"]

    # Deload takes priority — acute fatigue needs recovery first
    if fatigue > FATIGUE_SCORE_DELOAD_TRIGGER:
        triggers.append(f"Fatigue score {fatigue:.2f} exceeds threshold {FATIGUE_SCORE_DELOAD_TRIGGER}")
        return {"review_type": "deload", "triggers": triggers}

    # Mesocycle review triggers
    if week_in_mesocycle >= mesocycle_length:
        triggers.append(f"End of mesocycle (week {week_in_mesocycle}/{mesocycle_length})")

    if stall_ratio > STALL_RATIO_REVIEW_TRIGGER:
        triggers.append(f"Stalled exercise ratio {stall_ratio:.2f} exceeds threshold {STALL_RATIO_REVIEW_TRIGGER}")

    if triggers:
        return {"review_type": "mesocycle_review", "triggers": triggers}

    return {"review_type": "normal", "triggers": []}


def analyze_training_history(
    weeks: list[dict],
    week_in_mesocycle: int,
    mesocycle_length: int,
) -> dict[str, Any]:
    """Top-level entry point: compute all metrics and decide review type.

    Parameters
    ----------
    weeks:
        Current mesocycle's weekly records with feedback.
    week_in_mesocycle:
        Current position in the mesocycle (1-indexed).
    mesocycle_length:
        Configured mesocycle length.

    Returns
    -------
    dict
        {review_type, triggers, exercise_flags, global_metrics}
    """
    exercise_metrics = compute_exercise_metrics(weeks)
    global_metrics = compute_global_metrics(exercise_metrics, weeks)
    global_metrics["mesocycle_position"] = round(
        week_in_mesocycle / mesocycle_length, 2
    ) if mesocycle_length > 0 else 0.0

    decision = decide_review_type(global_metrics, week_in_mesocycle, mesocycle_length)

    return {
        "review_type": decision["review_type"],
        "triggers": decision["triggers"],
        "exercise_flags": exercise_metrics,
        "global_metrics": global_metrics,
    }


# ── Display metrics (surfaced in the UI, not used for review decisions) ──────


def _is_logged(weight: Any) -> bool:
    """A set counts as logged when it carries a non-empty weight value."""
    return weight is not None and str(weight).strip() != ""


def _count_prescribed_sets(program: dict) -> int:
    """Sum the prescribed set count across every exercise in a week's program."""
    total = 0
    for exercises in (program or {}).values():
        for ex in exercises:
            try:
                total += int(ex.get("sets") or 0)
            except (ValueError, TypeError):
                pass
    return total


def _count_logged_sets(feedback: dict) -> int:
    """Count sets that the user actually logged (non-empty weight) in a week."""
    total = 0
    for exercises in (feedback or {}).values():
        for ex in exercises:
            for s in ex.get("sets_data", []):
                if _is_logged(s.get("weight")):
                    total += 1
    return total


def compute_weekly_volume(all_programs: list[dict]) -> list[dict[str, Any]]:
    """Per-week set-volume summary for display.

    Parameters
    ----------
    all_programs:
        The session's weekly records, each with 'program' and (for completed
        weeks) 'feedback'.

    Returns
    -------
    list[dict]
        One entry per week, sorted ascending:
        {week, mesocycle, type, prescribed_sets, logged_sets}.
    """
    out: list[dict[str, Any]] = []
    for rec in all_programs:
        out.append({
            "week": rec.get("week", 0),
            "mesocycle": rec.get("mesocycle", 1),
            "type": rec.get("type", "normal"),
            "prescribed_sets": _count_prescribed_sets(rec.get("program") or {}),
            "logged_sets": _count_logged_sets(rec.get("feedback") or {}),
        })
    out.sort(key=lambda r: r["week"])
    return out


def _best_logged_set(sets_data: list[dict]) -> dict | None:
    """Return the heaviest logged set (by weight) from a list of sets."""
    best = None
    best_weight = -1.0
    for s in sets_data:
        if not _is_logged(s.get("weight")):
            continue
        try:
            w = float(s.get("weight"))
        except (ValueError, TypeError):
            continue
        if w > best_weight:
            best_weight = w
            best = s
    return best


def compute_last_time(all_programs: list[dict]) -> dict[str, dict]:
    """Look up the most recent prior performance for each week's exercises.

    For every exercise scheduled in week N, find the most recent earlier week
    in which that exercise was logged and summarise its heaviest set. This
    powers the inline "last time you did this" hint.

    Returns
    -------
    dict
        {"<week>|<exercise_name>": {week, weight, reps, actual_rir}}.
        Keys only exist where a prior logged session is available.
    """
    ordered = sorted(all_programs, key=lambda r: r.get("week", 0))
    seen: dict[str, dict] = {}        # exercise name -> latest logged top set
    lookup: dict[str, dict] = {}
    for rec in ordered:
        week = rec.get("week", 0)
        # Record what each scheduled exercise looked like last time, from 'seen'.
        for exercises in (rec.get("program") or {}).values():
            for ex in exercises:
                name = ex.get("name")
                if name and name in seen:
                    lookup[f"{week}|{name}"] = seen[name]
        # Then fold this week's logged results into 'seen' for later weeks.
        for exercises in (rec.get("feedback") or {}).values():
            for ex in exercises:
                name = ex.get("name")
                if not name:
                    continue
                best = _best_logged_set(ex.get("sets_data", []))
                if best:
                    seen[name] = {
                        "week": week,
                        "weight": best.get("weight"),
                        "reps": best.get("reps"),
                        "actual_rir": best.get("actual_rir"),
                    }
    return lookup


_PATTERN_KEYWORDS = {
    "Upper_horizontal_push": ["bench", "push up", "push-up", "pushup", "chest press", "dip", "fly", "pec"],
    "Upper_horizontal_pull": ["row", "rear delt", "face pull"],
    "Upper_vertical_push": ["overhead", "ohp", "shoulder press", "military", "lateral raise", "arnold"],
    "Upper_vertical_pull": ["pull up", "pull-up", "pullup", "chin up", "chin-up", "chinup", "pulldown", "lat "],
    "Lower_anterior_chain": ["squat", "leg press", "lunge", "leg extension", "split squat", "step up"],
    "Lower_posterior_chain": ["deadlift", "rdl", "romanian", "hip thrust", "leg curl", "ham", "glute", "good morning"],
}


def _exercise_patterns(ex: dict) -> list[str]:
    """Patterns an exercise trains: explicit tags if present, else a keyword guess."""
    tags = ex.get("patterns")
    if isinstance(tags, list) and tags:
        return [p for p in tags if p in MOVEMENT_PATTERNS]
    name = (ex.get("name") or "").lower()
    return [k for k, kws in _PATTERN_KEYWORDS.items() if any(w in name for w in kws)]


def compute_muscle_volume(weekly_program: dict, level: str = "intermediate") -> list[dict[str, Any]]:
    """Prescribed weekly sets per movement pattern vs the level's target range.

    Returns one entry per pattern (all six, in MOVEMENT_PATTERNS order):
    {key, description, sets, min, max, status} with status in {under, in_range, over}.
    Each listed pattern of an exercise gets full set credit.
    """
    ranges = VOLUME_GUIDELINES.get(level) or VOLUME_GUIDELINES["intermediate"]
    sets_by_pattern = {k: 0 for k in MOVEMENT_PATTERNS}
    for exercises in (weekly_program or {}).values():
        for ex in exercises:
            try:
                n = int(ex.get("sets") or 0)
            except (ValueError, TypeError):
                n = 0
            for pattern in _exercise_patterns(ex):
                sets_by_pattern[pattern] += n

    out: list[dict[str, Any]] = []
    for key in MOVEMENT_PATTERNS:
        rng = ranges[key]
        sets = sets_by_pattern[key]
        if sets < rng["min"]:
            status = "under"
        elif sets > rng["max"]:
            status = "over"
        else:
            status = "in_range"
        out.append({
            "key": key, "description": rng["description"],
            "sets": sets, "min": rng["min"], "max": rng["max"], "status": status,
        })
    return out


def _epley_e1rm(weight: float, reps: float) -> float:
    """Estimated 1RM (Epley): weight x (1 + reps/30)."""
    return round(weight * (1 + reps / 30), 1)


def compute_exercise_series(all_programs: list[dict]) -> dict[str, dict]:
    """Per-exercise week-by-week heaviest logged set + e1RM, plus overall load delta.

    Returns {name: {"rows": [{week, weight, reps, e1rm}, ...], "delta": float}}.
    Only weeks with a logged set for that exercise appear.
    """
    ordered = sorted(all_programs, key=lambda r: r.get("week", 0))
    series: dict[str, list[dict]] = {}
    for rec in ordered:
        week = rec.get("week", 0)
        for exercises in (rec.get("feedback") or {}).values():
            for ex in exercises:
                name = ex.get("name")
                if not name:
                    continue
                best = _best_logged_set(ex.get("sets_data", []))
                if not best:
                    continue
                try:
                    w = float(best.get("weight"))
                    r = float(best.get("reps") or 0)
                except (ValueError, TypeError):
                    continue
                series.setdefault(name, []).append(
                    {"week": week, "weight": w, "reps": r, "e1rm": _epley_e1rm(w, r)}
                )
    return {
        name: {"rows": rows, "delta": round(rows[-1]["weight"] - rows[0]["weight"], 1)}
        for name, rows in series.items() if rows
    }
