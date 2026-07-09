"""Pure functions that turn pipeline data into the generation screen's milestone
plan + reasoning lines. No LLM calls, no Flask, no I/O — fully unit-testable.

A generation flow declares an ordered *plan* (milestones the frontend renders)
and streams *reason* lines tagged to a milestone key. The web layer wraps these
into SSE payloads; nothing here knows about SSE.
"""
from __future__ import annotations

import re

from .analytics import compute_muscle_volume

# ── Milestone plans (frontend renders whatever it is handed) ──────────────────
WEEK1_PLAN = [
    {"key": "goals",     "label": "Reviewing your goals & experience"},
    {"key": "split",     "label": "Choosing your weekly split"},
    {"key": "exercises", "label": "Picking your exercises"},
    {"key": "intensity", "label": "Dialing in sets, reps & intensity"},
    {"key": "audit",     "label": "Pressure-testing against the science"},
    {"key": "finalize",  "label": "Finalizing your program"},
]

_PROGRESSION_NORMAL = [
    {"key": "analyze",  "label": "Reviewing last week's performance"},
    {"key": "adjust",   "label": "Adjusting your loads & reps"},
    {"key": "audit",    "label": "Pressure-testing the progression"},
    {"key": "finalize", "label": "Finalizing your program"},
]


def progression_plan(review_type: str) -> list[dict]:
    """Plan emitted at the START of a next-week job (before review_type is known
    for deloads/mesocycles — we show the normal plan; the approval overlay then
    takes over and continuation_plan() re-declares the rebuild plan)."""
    return list(_PROGRESSION_NORMAL)


def continuation_plan(review_type: str) -> list[dict]:
    """Plan emitted after the user approves a deload/mesocycle review."""
    if review_type == "deload":
        return [
            {"key": "rebuild",  "label": "Building your deload week"},
            {"key": "finalize", "label": "Finalizing your program"},
        ]
    return [
        {"key": "split",     "label": "Choosing your new split"},
        {"key": "exercises", "label": "Picking fresh exercises"},
        {"key": "intensity", "label": "Dialing in sets, reps & intensity"},
        {"key": "audit",     "label": "Pressure-testing against the science"},
        {"key": "finalize",  "label": "Finalizing your program"},
    ]


def goals_lines(user_input: str) -> list[str]:
    """Echo the user's own profile back as the first reasoning lines."""
    lines = [ln.strip() for ln in (user_input or "").splitlines() if ln.strip()]
    out = [ln for ln in lines if not ln.lower().startswith("generate a strength")]
    return out[:4] if out else ["Reading your training profile"]


def _exercise_names(weekly: dict) -> list[str]:
    names: list[str] = []
    for exercises in (weekly or {}).values():
        for ex in exercises:
            n = ex.get("name")
            if n and n not in names:
                names.append(n)
    return names


def _rep_span(weekly: dict) -> tuple[int | None, int | None]:
    los, his = [], []
    for exercises in (weekly or {}).values():
        for ex in exercises:
            nums = [int(x) for x in re.findall(r"\d+", str(ex.get("reps") or ""))]
            if nums:
                los.append(min(nums))
                his.append(max(nums))
    return (min(los), max(his)) if los else (None, None)


def design_lines(draft: dict, collapse_to: str | None = None) -> list[dict]:
    """Real, derived design reasoning from a program draft.

    Tags lines to split/exercises/intensity (or all to ``collapse_to`` when set,
    e.g. 'rebuild' for a deload). Returns ``[]`` for an empty/invalid draft.
    """
    weekly = (draft or {}).get("weekly_program") or {}
    level = str((draft or {}).get("level") or "intermediate").lower()
    out: list[dict] = []

    def add(milestone: str, reason: str) -> None:
        out.append({"milestone": collapse_to or milestone, "reason": reason})

    days = [d for d, ex in weekly.items() if ex]
    if days:
        add("split", f"{len(days)} training days per week")
        labels = [d for d in days if not d.lower().startswith("day ")]
        if labels:
            add("split", "Split: " + " · ".join(labels))

    names = _exercise_names(weekly)
    if names:
        add("exercises", f"{len(names)} exercises selected")
        add("exercises", "Including " + ", ".join(names[:4]))

    lo, hi = _rep_span(weekly)
    if lo is not None:
        span = f"{lo}–{hi}" if hi and hi != lo else f"{lo}"
        add("intensity", f"Rep ranges {span} reps")

    for row in compute_muscle_volume(weekly, level):
        if row["sets"] <= 0:
            continue
        if row["status"] == "in_range":
            tag = f"in {row['min']}–{row['max']} range ✓"
        elif row["status"] == "under":
            tag = f"below {row['min']} — light"
        else:
            tag = f"above {row['max']} — high"
        add("intensity", f"{row['description']}: {row['sets']} sets/wk ({tag})")

    return out


_AUDIT_OK = {
    "frequency_and_split": "Training frequency & split — balanced ✓",
    "exercise_selection": "Exercise selection — solid choices ✓",
    "set_volume": "Weekly set volume — within guidelines ✓",
    "rep_ranges": "Rep ranges — suited to the goal ✓",
    "rir": "Effort / RIR targets — on point ✓",
    "progression": "Progression strategy — sound ✓",
}
_AUDIT_FLAG = {
    "frequency_and_split": "Frequency & split — refining",
    "exercise_selection": "Exercise selection — refining",
    "set_volume": "Set volume — adjusting to hit the range",
    "rep_ranges": "Rep ranges — tightening",
    "rir": "Effort / RIR targets — adjusting",
    "progression": "Progression — refining",
}


def audit_line(task_type: str, has_feedback: bool) -> str:
    """One clean verdict line for a Critic dimension."""
    table = _AUDIT_FLAG if has_feedback else _AUDIT_OK
    if task_type in table:
        return table[task_type]
    name = task_type.replace("_", " ").title()
    return f"{name} — refining" if has_feedback else f"{name} ✓"


def analyze_lines(analytics: dict) -> list[dict]:
    """Real autoregulation facts surfaced during the Week-2 analyze phase."""
    gm = (analytics or {}).get("global_metrics", {})
    flags = (analytics or {}).get("exercise_flags", {})
    progressing = [n for n, m in flags.items() if m.get("flag") == "progressing"]
    stalled = [n for n, m in flags.items() if m.get("flag") == "stalled"]
    out: list[dict] = []
    if progressing:
        out.append({"milestone": "analyze", "reason": f"{len(progressing)} lifts progressing well"})
    if stalled:
        out.append({"milestone": "analyze",
                    "reason": f"{len(stalled)} lifts stalled — {', '.join(stalled[:3])}"})
    trend = gm.get("avg_rir_trend")
    if trend == "falling":
        out.append({"milestone": "analyze", "reason": "Effort trending up (RIR falling) — watching fatigue"})
    elif trend == "rising":
        out.append({"milestone": "analyze", "reason": "Plenty in reserve — room to push"})
    return out or [{"milestone": "analyze", "reason": "Reviewing your logged sets"}]


def adjust_lines(analytics: dict) -> list[dict]:
    """Per-exercise progression decisions derived from the autoregulation flags."""
    flags = (analytics or {}).get("exercise_flags", {})
    out: list[dict] = []
    for name, m in list(flags.items())[:6]:
        if m.get("flag") == "stalled":
            out.append({"milestone": "adjust", "reason": f"{name}: stalled — holding load, adding a rep"})
        elif m.get("rir_trend") == "rising":
            out.append({"milestone": "adjust", "reason": f"{name}: felt easy — adding load"})
        else:
            out.append({"milestone": "adjust", "reason": f"{name}: progressing — small bump"})
    return out or [{"milestone": "adjust", "reason": "Tuning loads from last week's performance"}]
