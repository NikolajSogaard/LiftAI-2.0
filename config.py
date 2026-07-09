# config.py
"""Central configuration — import from here instead of hardcoding values."""
import os

# ── LLM defaults (Anthropic Claude, via the Claude Agent SDK / subscription) ──
DEFAULT_MODEL = "claude-opus-4-8"           # writer / generation — most capable tier
DEFAULT_CRITIC_MODEL = "claude-sonnet-4-6"  # critic + analyst — evaluation, cheaper tier
DEFAULT_FALLBACK_MODEL = "claude-sonnet-4-6"  # writer falls back here on a transient Opus error

# Effort controls thinking depth / token spend on adaptive-thinking models
# (Opus 4.8 / Sonnet 4.6). 'high' is the Opus 4.8 sweet spot; sweep on an eval set.
DEFAULT_WRITER_EFFORT = "high"
DEFAULT_CRITIC_EFFORT = "medium"

# ── Pipeline feature flags (experimental — validate live before flipping) ─────
CRITIC_SINGLE_CALL = False    # Week-1 critic: one multi-aspect call vs the 5-thread fan-out
VOLUME_VERIFIER_ENABLED = False  # Week-1: re-generate once if deterministic volume check fails

# ── Timeouts (seconds) ───────────────────────────────────────────────────────
QUEUE_TIMEOUT = 120          # SSE inter-message idle budget in app.py (resets per status msg)
LLM_CALL_TIMEOUT = 600       # hard cap on a single model call on the shared event loop

# ── Knowledge base ("the brain") ──────────────────────────────────────────────
BRAIN_DIR = os.path.join("Data", "brain")

# ── Mesocycle & autoregulation ──────────────────────────────────────────────
DEFAULT_MESOCYCLE_LENGTH = 6         # weeks per training block
STAGNATION_THRESHOLD_WEEKS = 2      # consecutive weeks with no progress → flagged
FATIGUE_SCORE_DELOAD_TRIGGER = 0.7  # fatigue above this → deload
STALL_RATIO_REVIEW_TRIGGER = 0.5    # fraction of exercises stalled → mesocycle review
# (Deload volume cut lives in the Analyst prompt — it's LLM-applied, not a Python knob.)

# ── Input validation ─────────────────────────────────────────────────────────
MAX_USER_INPUT_CHARS = 5000
MAX_CHAT_MESSAGE_CHARS = 2000
MAX_CHAT_HISTORY_TURNS = 50

# ── Per-movement-pattern weekly set-volume guidelines (single source of truth) ─
# Shared by the Critic (set_volume task) and the volume panel (analytics).
# Heuristic weekly hard-set ranges per movement pattern, in mainstream hypertrophy
# territory; deliberately coarse (a tighter table would imply false precision).
# Tiers rise with training age: advanced lifters tolerate and need more volume.
# Provenance: editorial synthesis of common hypertrophy guidance (Schoenfeld et al.
# dose-response work and practitioner consensus). v2 (2026-06-14): the `advanced`
# tier was a duplicate of `intermediate`; it now carries distinct, higher ranges.
MOVEMENT_PATTERNS = [
    "Upper_horizontal_push",
    "Upper_horizontal_pull",
    "Upper_vertical_push",
    "Upper_vertical_pull",
    "Lower_anterior_chain",
    "Lower_posterior_chain",
]

VOLUME_GUIDELINES = {
    "beginner": {
        "Upper_horizontal_push": {"min": 6, "max": 10, "description": "Chest/pressing"},
        "Upper_horizontal_pull": {"min": 6, "max": 10, "description": "Rows/rear back"},
        "Upper_vertical_push": {"min": 6, "max": 10, "description": "Overhead/shoulders"},
        "Upper_vertical_pull": {"min": 6, "max": 10, "description": "Pull-ups/lats"},
        "Lower_anterior_chain": {"min": 6, "max": 10, "description": "Quads"},
        "Lower_posterior_chain": {"min": 6, "max": 10, "description": "Glutes/Hams"},
    },
    "intermediate": {
        "Upper_horizontal_push": {"min": 10, "max": 16, "description": "Chest/pressing"},
        "Upper_horizontal_pull": {"min": 10, "max": 16, "description": "Rows/rear back"},
        "Upper_vertical_push": {"min": 8, "max": 14, "description": "Overhead/shoulders"},
        "Upper_vertical_pull": {"min": 10, "max": 18, "description": "Pull-ups/lats"},
        "Lower_anterior_chain": {"min": 10, "max": 16, "description": "Quads"},
        "Lower_posterior_chain": {"min": 10, "max": 16, "description": "Glutes/Hams"},
    },
    "advanced": {
        "Upper_horizontal_push": {"min": 12, "max": 20, "description": "Chest/pressing"},
        "Upper_horizontal_pull": {"min": 12, "max": 20, "description": "Rows/rear back"},
        "Upper_vertical_push": {"min": 10, "max": 18, "description": "Overhead/shoulders"},
        "Upper_vertical_pull": {"min": 12, "max": 22, "description": "Pull-ups/lats"},
        "Lower_anterior_chain": {"min": 12, "max": 20, "description": "Quads"},
        "Lower_posterior_chain": {"min": 12, "max": 20, "description": "Glutes/Hams"},
    },
}
