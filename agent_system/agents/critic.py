import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional, Callable, List
from agent_system.knowledge import get_subject_context
from .critique_task import CritiqueTask
from config import VOLUME_GUIDELINES, CRITIC_SINGLE_CALL
from agent_system.utils import compact_json
from agent_system import reasoning

logger = logging.getLogger(__name__)

class Critic:
    def __init__(
            self,
            model,
            role: dict[str, str],
            tasks: Dict[str, str] = None,
            single_call: bool | None = None,
            ):
        self.model = model
        self.role = role
        self.tasks = tasks or {}
        # Week-1 only: collapse the 5-thread aspect fan-out into one multi-aspect
        # call. Experimental — defaults to config.CRITIC_SINGLE_CALL (off).
        self.single_call = CRITIC_SINGLE_CALL if single_call is None else single_call
        self.on_status = None

        self._task_labels = {
            "frequency_and_split": "Evaluating training frequency and split",
            "exercise_selection": "Reviewing exercise selection",
            "set_volume": "Checking weekly set volume",
            "rep_ranges": "Analyzing rep ranges",
            "rir": "Assessing RIR targets",
            "progression": "Evaluating progression strategy",
        }

        # Each critique dimension consults its matching subject note (the brain's
        # subjects map 1:1 onto the critic's aspects). Replaces the old single
        # shared RAG blob. Week-2+ progression injects nothing — handled below.
        self.aspect_subjects = {
            "frequency_and_split": ["frequency-and-splits"],
            "exercise_selection": ["exercise-selection"],
            "set_volume": ["volume"],
            "rep_ranges": ["load-and-rep-ranges"],
            "rir": ["effort"],
        }
        
        # Determine task types based on available tasks
        if tasks and "progression" in tasks and len(tasks) == 1:
            self.task_types = ["progression"]
            self.is_week2plus = True
        else:
            self.task_types = ["frequency_and_split", "exercise_selection", "set_volume", "rep_ranges", "rir"]
            self.is_week2plus = False

        self._init_task_configs()

    def _init_task_configs(self):
        """Build task configuration objects for each critique type."""

        all_task_defs = {
            "frequency_and_split": lambda: CritiqueTask(
                name="frequency_and_split",
                template=self.tasks.get("frequency_and_split", ""),
                dependencies=[],
            ),
            "exercise_selection": lambda: CritiqueTask(
                name="exercise_selection",
                template=self.tasks.get("exercise_selection", ""),
                dependencies=["frequency_and_split"],
            ),
            "set_volume": lambda: CritiqueTask(
                name="set_volume",
                template=self.tasks.get("set_volume", ""),
                dependencies=["frequency_and_split", "exercise_selection"],
                reference_data={"volume_guidelines": VOLUME_GUIDELINES}
            ),
            "rep_ranges": lambda: CritiqueTask(
                name="rep_ranges",
                template=self.tasks.get("rep_ranges", ""),
                dependencies=["frequency_and_split", "exercise_selection", "set_volume"],
            ),
            "rir": lambda: CritiqueTask(
                name="rir",
                template=self.tasks.get("rir", ""),
                dependencies=["frequency_and_split", "exercise_selection", "set_volume", "rep_ranges"],
            ),
            "progression": lambda: CritiqueTask(
                name="progression",
                template=self.tasks.get("progression", ""),
                dependencies=[],
            )
        }

        # Only build configs for task types that have a non-empty template.
        self.task_configs = {}
        for task_type in self.task_types:
            if task_type in all_task_defs and self.tasks.get(task_type):
                self.task_configs[task_type] = all_task_defs[task_type]()

    def _emit(self, message=None, detail=False, milestone=None, reason=None):
        if not self.on_status:
            return
        payload = {"step": "critic"}
        if message is not None:
            payload["message"] = message
        if detail:
            payload["detail"] = True
        if milestone:
            payload["milestone"] = milestone
        if reason:
            payload["reason"] = reason
        self.on_status(payload)

    def _volume_ref_text(self, program: dict) -> str:
        """Volume-guideline text for the set_volume task.

        Scoped to the user's experience level when the draft declares one (so the
        critic sees only the relevant row instead of inferring from three tiers);
        falls back to all tiers when the level is unknown.
        """
        draft = program.get('draft')
        level = draft.get('level') if isinstance(draft, dict) else None
        if level in VOLUME_GUIDELINES:
            lines = [f"\nWeekly set-volume guidelines for a {level} lifter (sets/week):"]
            for muscle, ranges in VOLUME_GUIDELINES[level].items():
                lines.append(f"- {muscle}: {ranges.get('min', '?')}-{ranges.get('max', '?')}")
            return "\n".join(lines) + "\n"
        out = "\nVolume guidelines from reference data:\n"
        for lvl, muscles in VOLUME_GUIDELINES.items():
            out += f"\n{lvl.capitalize()} level:\n"
            for muscle, ranges in muscles.items():
                out += f"- {muscle.capitalize()}: {ranges.get('min', '?')}-{ranges.get('max', '?')} sets per week\n"
        return out

    def run_single_critique(self, task_type: str, program: dict) -> tuple[str, str | None]:
        """Run a single critique task and return (task_type, feedback_or_None).

        Parameters
        ----------
        task_type:
            Key into ``self.task_types`` (e.g. ``"volume"``, ``"exercise_selection"``).
        program:
            pipeline state dict. Must contain 'user-input' and 'draft'.

        Returns
        -------
        tuple[str, str | None]
            The task type and its feedback string, or None if the program passed.
        """
        previous_results = {}
        label = self._task_labels.get(task_type, task_type.replace('_', ' ').title())
        logger.info("Running %s critique", task_type.upper())
        
        task_config = self.task_configs.get(task_type)
        if not task_config:
            task_config = CritiqueTask(
                name=task_type, template=self.tasks.get(task_type, ""),
                dependencies=[],
            )
        
        dependency_context = task_config.get_context_from_dependencies(previous_results)
        
        # Include volume reference data if applicable (scoped to the user's level)
        ref_context = ""
        if task_type == "set_volume" and task_config.reference_data.get("volume_guidelines"):
            ref_context = self._volume_ref_text(program)
        
        # Each dimension consults its own subject note (Week 2+ progression: none).
        context = ""
        subjects = self.aspect_subjects.get(task_type, [])
        if subjects and not self.is_week2plus:
            knowledge = get_subject_context(subjects)
            if knowledge:
                context = f"\nRelevant strength-training knowledge:\n{knowledge}\n"

        if ref_context:
            context = ref_context + "\n" + context
        if dependency_context:
            context = f"\nConsiderations from previous critiques:\n{dependency_context}\n{context}"
        # Serialize program content
        program_content = program.get('draft')
        if isinstance(program_content, dict) and 'weekly_program' in program_content:
            program_content = compact_json(program_content)
        
        task_template = self.tasks.get(task_type)
        if task_template is None:
            task_template = f'''
            Your colleague has written the following training program:
            {{}}
            For an individual who provided the following input:
            {{}}
            Focus specifically on the {task_type.upper()}. Provide feedback if any... otherwise only return "None"
            '''
        
        # Format prompt differently for week 2+ progression
        if self.is_week2plus and task_type == "progression":
            week = program.get('week_number', 2)
            feedback_data = program.get('feedback', '{}')
            task_template = task_template.replace("{week_number}", str(week))
            prompt_content = task_template.format(program_content, program.get('user-input', ''), feedback_data) + context
        else:
            prompt_content = task_template.format(program_content, program.get('user-input', '')) + context
        
        full_prompt = f"{self.role.get('content', '')}\n\n{prompt_content}"
        
        logger.info("Generating %s critique...", task_type)
        try:
            feedback = self.model(full_prompt)
            return feedback or None
        except Exception as e:
            logger.exception("Error in %s critique", task_type.upper())
            return f"Error in {task_type} critique: {e}"

    def _process_task_result(self, task_type: str, feedback) -> tuple[str, str | None]:
        """Validate/clean one task's feedback and emit its audit verdict live.
        Returns (task_type, processed|None)."""
        def _verdict(processed):
            self._emit(milestone="audit",
                       reason=reasoning.audit_line(task_type, processed is not None))
            return task_type, processed

        if not feedback or not isinstance(feedback, str) or len(feedback.strip()) <= 10:
            logger.info("%s - No significant feedback", task_type.upper())
            return _verdict(None)

        processed = feedback.strip().removesuffix("None").strip() if feedback.strip().endswith("None") else feedback
        if len(processed.strip()) <= 10:
            return _verdict(None)
        if 'no changes' in processed.lower() or 'therefore, no changes' in processed.lower():
            logger.info("%s - No changes needed", task_type.upper())
            return _verdict(None)

        return _verdict(processed)

    def critique(self, program: dict) -> dict:
        """Run all critique tasks in parallel and aggregate feedback.

        Executes each task in ``self.task_types`` concurrently via
        ``ThreadPoolExecutor``. Aggregates non-None feedback into a single
        string stored in ``program['feedback']``.

        Parameters
        ----------
        program:
            pipeline state dict.

        Returns
        -------
        dict
            Updated state with 'feedback' set to the combined critique string,
            or None if the program passed all checks.
        """
        logger.info("========== CRITIQUE PROCESS STARTED ==========")

        self._emit(milestone="audit",
                   reason="Checking frequency, volume, rep ranges & effort against the guidelines")

        if self.single_call and not self.is_week2plus:
            return self._critique_single_call(program)

        with ThreadPoolExecutor(max_workers=len(self.task_types)) as executor:
            futures = {
                executor.submit(self.run_single_critique, task_type, program): task_type
                for task_type in self.task_types
            }
            processed_results: dict[str, str | None] = {}
            for future in as_completed(futures):
                task_type = futures[future]
                try:
                    feedback = future.result()
                except Exception:
                    logger.exception("Error in %s critique", task_type.upper())
                    feedback = None
                # Emits the audit verdict live as each dimension finishes.
                _, processed = self._process_task_result(task_type, feedback)
                processed_results[task_type] = processed

        all_feedback = []
        for task_type in self.task_types:
            processed = processed_results.get(task_type)
            if processed is None:
                continue
            all_feedback.append(f"[{task_type.upper()} FEEDBACK]:\n{processed}\n")
            logger.info("%s CRITIQUE:\n%s", task_type.upper(), processed)

        if not all_feedback:
            logger.info("No actionable feedback from any critique task")
            return {'feedback': None}

        combined = "\n".join(all_feedback)
        logger.info("========== CRITIQUE COMPLETE — %d/%d tasks with actionable feedback ==========",
                    len(all_feedback), len(self.task_types))
        return {'feedback': combined}

    def _critique_single_call(self, program: dict) -> dict:
        """Week-1 critique in ONE multi-aspect model call (experimental).

        Keeps the five aspect templates verbatim as labelled sections, asks for a
        per-aspect verdict, and flattens the parsed result into the same combined
        ``[ASPECT FEEDBACK]:`` string the downstream Writer/Editor already read —
        so it is a drop-in for the 5-thread fan-out. Gated by ``self.single_call``.
        """
        logger.info("Single-call critique (all aspects in one pass)")
        program_content = program.get('draft')
        if isinstance(program_content, dict) and 'weekly_program' in program_content:
            program_content = compact_json(program_content)
        user_input = program.get('user-input', '')

        sections = []
        for task_type in self.task_types:
            template = self.tasks.get(task_type) or ""
            try:
                body = template.format(program_content, user_input)
            except (IndexError, KeyError):
                body = template
            if task_type == "set_volume":
                body += self._volume_ref_text(program)
            sections.append(f"===== {task_type.upper()} =====\n{body}")

        aspects = ", ".join(t.upper() for t in self.task_types)
        instructions = (
            "Evaluate the program on EACH area below independently. For every area, "
            f"emit a section headed exactly '### <AREA>' (areas: {aspects}) followed "
            "by concrete feedback, or the single word 'None' if that area needs no "
            "change. Cover every area exactly once.\n\n"
        )
        full_prompt = f"{self.role.get('content', '')}\n\n{instructions}" + "\n\n".join(sections)
        subjects = sorted({s for t in self.task_types for s in self.aspect_subjects.get(t, [])})
        knowledge = get_subject_context(subjects) if subjects else ""
        if knowledge:
            full_prompt += f"\n\nRelevant strength-training knowledge:\n{knowledge}\n"

        response = self.model(full_prompt)
        if not isinstance(response, str):
            response = str(response)

        parsed = self._split_aspect_sections(response)
        all_feedback = []
        for task_type in self.task_types:
            _, processed = self._process_task_result(task_type, parsed.get(task_type))
            if processed is None:
                continue
            all_feedback.append(f"[{task_type.upper()} FEEDBACK]:\n{processed}\n")

        if not all_feedback:
            return {'feedback': None}
        return {'feedback': "\n".join(all_feedback)}

    def _split_aspect_sections(self, text: str) -> dict[str, str]:
        """Parse a single-call response into {task_type: feedback_text}.

        Splits on ``###``-style headers and maps each header to a task type by a
        normalized substring match (tolerates spaces/case/colons in the header).
        """
        import re
        result: dict[str, str] = {}
        parts = re.split(r'(?m)^\s*#{2,}\s*', text)
        for part in parts:
            if not part.strip():
                continue
            head, _, body = part.partition('\n')
            key = head.strip().lower().replace(' ', '_').replace(':', '').replace('=', '').strip('_')
            for task_type in self.task_types:
                if task_type and (task_type in key or key in task_type):
                    result[task_type] = body.strip()
                    break
        return result

    def __call__(self, article: dict[str, str | None]) -> dict[str, str | None]:
        # New critique = any feedback_applied flag from the previous revise is stale.
        article.pop('feedback_applied', None)
        article.update(self.critique(article))
        return article
