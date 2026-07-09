"""Editor tool schemas — the day/exercise edit surface.

Factored out of chatbot.py so the live-editor chatbot and any future
generation-time edit path share one definition of the program-mutation tools
(name, description, JSON Schema). Pure data; no behavior.
"""

# Full JSON Schemas for the three program-editing tools. Passed to the Agent SDK's
# @tool decorator in chatbot.py.
TOOL_SCHEMAS = [
    {
        "name": "edit_exercise",
        "description": "Edit one or more fields of an existing exercise in the training program.",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "The exact day key as it appears in the program (e.g. 'Monday: Upper A')"},
                "exercise_index": {"type": "integer", "description": "0-based index of the exercise within that day"},
                "name": {"type": "string", "description": "New exercise name (optional, omit to keep current)"},
                "sets": {"type": "integer", "description": "New number of sets (optional)"},
                "reps": {"type": "string", "description": "New rep range, e.g. '8-12' or '5-8' (optional)"},
                "target_rir": {"type": "string", "description": "New RIR target (Reps In Reserve), e.g. '1-2' (optional)"},
                "cues": {"type": "string", "description": "New coaching cues (optional)"},
                "rest": {"type": "string", "description": "New rest period, e.g. '90-120 seconds' (optional)"},
                "technique": {"type": "string", "description": "Intensity technique for the LAST working set, e.g. 'Drop set', 'Myo-reps', 'Lengthened partials'. Only on isolation/machine exercises. Pass an empty string to remove it. (optional)"},
            },
            "required": ["day", "exercise_index"],
        },
    },
    {
        "name": "add_exercise",
        "description": "Add a new exercise to a training day.",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "The exact day key to add the exercise to"},
                "name": {"type": "string", "description": "Exercise name"},
                "sets": {"type": "integer", "description": "Number of sets"},
                "reps": {"type": "string", "description": "Rep range, e.g. '8-12'"},
                "target_rir": {"type": "string", "description": "RIR target (Reps In Reserve), e.g. '1-2'"},
                "cues": {"type": "string", "description": "Coaching cues"},
                "rest": {"type": "string", "description": "Rest period, e.g. '90 seconds'"},
                "technique": {"type": "string", "description": "Intensity technique for the LAST working set, e.g. 'Drop set', 'Myo-reps' (optional; isolation/machine exercises only)"},
            },
            "required": ["day", "name", "sets", "reps", "target_rir"],
        },
    },
    {
        "name": "remove_exercise",
        "description": "Remove an exercise from a training day.",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "The exact day key"},
                "exercise_index": {"type": "integer", "description": "0-based index of the exercise to remove"},
            },
            "required": ["day", "exercise_index"],
        },
    },
]
