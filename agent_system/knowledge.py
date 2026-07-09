"""The strength-training knowledge base ("the brain").

Replaces the deferred FAISS/embeddings RAG layer. Reads hand-curated, authorless
markdown notes from ``Data/brain/subjects/`` and returns their bodies as plain
text for injection into agent prompts. Deterministic — no embeddings, no LLM call.
"""
import glob
import logging
import os
import re

from config import BRAIN_DIR

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def _subjects_dir(brain_dir=None):
    return os.path.join(brain_dir or BRAIN_DIR, "subjects")


def _strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block — agents never see metadata."""
    return _FRONTMATTER_RE.sub("", text, count=1).strip()


def get_subject_context(subjects, brain_dir=None) -> str:
    """Return the concatenated bodies of the named subject notes.

    ``subjects`` is a list of subject slugs (file stems in ``subjects/``). Missing
    notes are skipped (logged). Frontmatter is stripped. Returns ``""`` when no
    note resolves — mirrors the old RAG "empty context" contract so callers
    degrade gracefully.
    """
    sdir = _subjects_dir(brain_dir)
    chunks = []
    for slug in subjects:
        path = os.path.join(sdir, f"{slug}.md")
        if not os.path.exists(path):
            logger.warning("brain: subject note not found: %s", path)
            continue
        with open(path, encoding="utf-8") as fh:
            body = _strip_frontmatter(fh.read())
        if body:
            chunks.append(body)
    return "\n\n---\n\n".join(chunks)


# Surnames of coaches/researchers whose work feeds the brain — must never appear
# in note bodies (the brain is authorless; see the spec). Method names (e.g.
# "Juggernaut Method") are deliberately allowed — they are methodology, not authors.
BANNED_NAMES = [
    "Nippard", "Israetel", "Schoenfeld", "Helms", "Nuckols", "Isuf",
    "Tuchscherer", "Hoffmann", "Hoffman", "Krieger", "Barbosa", "Steele",
    # Phase-2 supplementary authors. NB: not "Smith" (→ Smith machine); use "Wesley".
    "Wesley", "Davis",
]

_WIKILINK_RE = re.compile(r"\[\[([a-z0-9-]+)(?:#[^\]]*)?\]\]")


def _all_slugs(brain_dir=None):
    sdir = _subjects_dir(brain_dir)
    return {os.path.splitext(os.path.basename(p))[0]
            for p in glob.glob(os.path.join(sdir, "*.md"))}


def lint_brain(brain_dir=None) -> list[str]:
    """Health-check every subject note. Returns a list of human-readable issues
    (empty == healthy). Enforces: authorless bodies, a `subject:` frontmatter key,
    and wikilinks that resolve to an existing subject note."""
    sdir = _subjects_dir(brain_dir)
    slugs = _all_slugs(brain_dir)
    issues = []
    for path in sorted(glob.glob(os.path.join(sdir, "*.md"))):
        slug = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        m = _FRONTMATTER_RE.match(raw)
        front = raw[: m.end()] if m else ""
        body = _strip_frontmatter(raw)

        if "subject:" not in front:
            issues.append(f"[{slug}] missing `subject:` in frontmatter")
        for name in BANNED_NAMES:
            if re.search(rf"\b{re.escape(name)}\b", body):
                issues.append(f"[{slug}] author name leaked into body: {name!r}")
        for target in _WIKILINK_RE.findall(body):
            if target not in slugs:
                issues.append(f"[{slug}] broken wikilink: [[{target}]]")
    return issues


# ── Example programs ─────────────────────────────────────────────────────────
# Concrete program templates in Data/brain/programs/ that ground the Writer.

def _parse_frontmatter(raw: str) -> dict:
    """Parse simple `key: value` scalars from a note's leading YAML frontmatter."""
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}
    fm = {}
    for line in raw[3:m.end()].splitlines():  # skip the opening ---
        line = line.strip()
        if not line or line == "---" or ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"')
    return fm


_SPLIT_KEYWORDS = {
    "full-body": ["full body", "full-body", "fullbody", "whole body"],
    "upper-lower": ["upper/lower", "upper lower", "upper-lower"],
    "ppl": ["ppl", "push pull legs", "push/pull/legs", "push, pull, legs"],
    "ul-ppl-hybrid": ["hybrid"],
}
_GOAL_KEYWORDS = {
    "hypertrophy": ["hypertroph", "muscle", "size", "bigger", "bodybuild", "physique", "aesthetic"],
    "strength": ["strength", "stronger", "powerlift", "1rm", "one rep max"],
    "powerbuilding": ["powerbuild"],
}


def _score_program(fm: dict, ui: str) -> float:
    """Score one program's frontmatter against the lowercased user request."""
    score = 0.0
    days = fm.get("days_per_week", "")
    if days and (f"{days} day" in ui or f"{days}-day" in ui or f"{days}x" in ui or f"{days} x" in ui):
        score += 3
    if any(k in ui for k in _SPLIT_KEYWORDS.get(fm.get("split", ""), [])):
        score += 2
    if any(k in ui for k in _GOAL_KEYWORDS.get(fm.get("goal", ""), [])):
        score += 2
    lvl = fm.get("level", "")
    if lvl in ("beginner", "intermediate", "advanced") and lvl in ui:
        score += 1
    # gentle defaults so a sensible template floats up when the input gives no signal
    if lvl == "all":
        score += 0.5
    if fm.get("goal") == "hypertrophy":
        score += 0.3
    if days in ("3", "4"):
        score += 0.4
    return score


def get_example_programs(user_input: str, n: int = 1, brain_dir=None) -> str:
    """Return the best-matching example program(s) as plain text — a grounding
    template for the Writer. Deterministic keyword scoring of each program's
    frontmatter (days/split/goal/level) against the lowercased user request; with
    no signal a sensible mid-frequency all-levels hypertrophy template floats up.
    Returns "" when there are no example programs."""
    pdir = os.path.join(brain_dir or BRAIN_DIR, "programs")
    ui = (user_input or "").lower()
    scored = []
    for path in sorted(glob.glob(os.path.join(pdir, "*.md"))):
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        fm = _parse_frontmatter(raw)
        if fm.get("type") != "example-program":
            continue
        scored.append((_score_program(fm, ui), path, raw))
    if not scored:
        return ""
    scored.sort(key=lambda t: (-t[0], t[1]))
    return "\n\n---\n\n".join(_strip_frontmatter(raw) for _, _, raw in scored[: max(1, n)])
