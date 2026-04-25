from __future__ import annotations

import json
import re
from typing import Sequence

from cua_lark.config import Settings
from cua_lark.models import (
    ActionStep,
    AssertionSpec,
    Observation,
    PolicyDecision,
    ProgressAssessment,
    ReplanReason,
    ReflectionResult,
    StepRecord,
    TaskSpec,
    ValidationEvidence,
    ValidationResult,
)
from cua_lark.providers.base import VisionPolicy
from cua_lark.utils.images import encode_image_as_data_url


class OpenAICompatibleVisionPolicy(VisionPolicy):
    backend_name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai is not installed. Run `python -m pip install -e .`.") from exc

        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        self._client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        self._settings = settings
        self.last_transport: str | None = None
        self.last_error: str | None = None

    def plan_next_action(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        remaining_steps: int,
    ) -> PolicyDecision:
        prompt = self._build_planning_prompt(task, observation, history, remaining_steps)
        raw = self._call_model(prompt, [observation.screenshot_path], detail="auto")
        data = self._extract_json(raw)
        action = ActionStep.from_dict(data["action"]) if isinstance(data.get("action"), dict) else None
        replan_reason = data.get("replan_reason")
        parsed_reason = ReplanReason(replan_reason) if replan_reason in ReplanReason._value2member_map_ else None
        return PolicyDecision(
            done=bool(data.get("done", False)),
            rationale=str(data.get("rationale", "")),
            action=action,
            replan_reason=parsed_reason,
        )

    def validate_assertion(
        self,
        task: TaskSpec,
        observation: Observation,
        assertion: AssertionSpec,
        history: Sequence[StepRecord],
    ) -> ValidationResult:
        prompt = self._build_validation_prompt(task, observation, assertion, history)
        raw = self._call_model(prompt, [observation.screenshot_path], detail="high")
        data = self._extract_json(raw)
        evidence = [
            ValidationEvidence(
                type="vlm_semantic",
                content=str(data.get("summary", "")),
                score=float(data.get("confidence", 0.0)),
            )
        ]
        return ValidationResult(
            passed=bool(data.get("passed", False)),
            summary=str(data.get("summary", "")),
            strategy=f"openai_{assertion.type}",
            confidence=float(data.get("confidence", 0.0)),
            evidence=evidence,
            details={"raw": data},
        )

    def assess_progress(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        latest_action: ActionStep | None = None,
    ) -> ProgressAssessment:
        prompt = self._build_progress_prompt(task, observation, history, latest_action)
        raw = self._call_model(prompt, [observation.screenshot_path], detail="high")
        data = self._extract_json(raw)
        evidence = [str(item) for item in data.get("evidence", []) if str(item).strip()]
        unmet_goals = [str(item) for item in data.get("unmet_goals", []) if str(item).strip()]
        return ProgressAssessment(
            success=bool(data.get("success", False)),
            completion_score=float(data.get("completion_score", 0.0)),
            progress_label=str(data.get("progress_label", "未知")),
            summary=str(data.get("summary", "")),
            evidence=evidence,
            unmet_goals=unmet_goals,
            confidence=float(data.get("confidence", 0.0)),
        )

    def reflect_after_step(
        self,
        task: TaskSpec,
        before: Observation,
        after: Observation,
        action: ActionStep,
        validation: ValidationResult,
        progress: ProgressAssessment,
        history: Sequence[StepRecord],
    ) -> ReflectionResult:
        prompt = self._build_reflection_prompt(task, before, after, action, validation, progress, history)
        raw = self._call_model(prompt, [before.screenshot_path, after.screenshot_path], detail="high")
        data = self._extract_json(raw)
        suggested_action = (
            ActionStep.from_dict(data["suggested_action"])
            if isinstance(data.get("suggested_action"), dict)
            else None
        )
        return ReflectionResult(
            should_replan=bool(data.get("should_replan", False)),
            root_cause=str(data.get("root_cause", "")),
            failure_stage=str(data.get("failure_stage", "")),
            suggested_strategy=str(data.get("suggested_strategy", "")),
            suggested_action=suggested_action,
            confidence=float(data.get("confidence", 0.0)),
        )

    def _call_model(self, prompt: str, screenshot_paths: Sequence[str], detail: str) -> str:
        image_urls = [encode_image_as_data_url(Path(path)) for path in screenshot_paths]

        try:
            content = [{"type": "input_text", "text": prompt}]
            content.extend({"type": "input_image", "image_url": image_url} for image_url in image_urls)
            response = self._client.responses.create(
                model=self._settings.openai_model,
                input=[
                    {
                        "role": "user",
                        "content": content,
                    }
                ],
            )
            output_text = getattr(response, "output_text", None)
            if output_text:
                self.last_transport = "responses"
                self.last_error = None
                return str(output_text)
        except Exception as exc:
            self.last_transport = "responses_failed"
            self.last_error = str(exc)

        content = [{"type": "text", "text": prompt}]
        content.extend({"type": "image_url", "image_url": {"url": image_url, "detail": detail}} for image_url in image_urls)
        completion = self._client.chat.completions.create(
            model=self._settings.openai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a GUI planning and validation assistant. Return JSON only."},
                {
                    "role": "user",
                    "content": content,
                },
            ],
        )
        self.last_transport = "chat.completions"
        return completion.choices[0].message.content or "{}"

    def _extract_json(self, raw: str) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if not match:
                raise RuntimeError(f"Model did not return JSON. Raw output: {raw[:500]}")
            return json.loads(match.group(0))

    def _build_planning_prompt(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        remaining_steps: int,
    ) -> str:
        recent_actions = [
            f"{record.index}.{record.attempt} {record.action.action_type}: {record.action.description} -> {record.success}"
            for record in history[-5:]
        ]
        return f"""
You are controlling the Feishu desktop client as a testing agent.
Return strict JSON with keys: done, rationale, replan_reason, action.
Allowed action types: click, double_click, right_click, drag, scroll, type_text, hotkey, wait, assert, noop.
If no action is needed, set done=true and action=null.
The rationale field must be concise Simplified Chinese.

Task:
{task.instruction}

Product:
{task.product}

Preconditions:
{task.preconditions}

Assertions:
{[assertion.description or assertion.expected_text for assertion in task.assertions]}

Observation text:
{observation.flattened_text[:2000]}

Window title:
{observation.window_title}

Remaining steps:
{remaining_steps}

Recent actions:
{recent_actions}
""".strip()

    def _build_validation_prompt(
        self,
        task: TaskSpec,
        observation: Observation,
        assertion: AssertionSpec,
        history: Sequence[StepRecord],
    ) -> str:
        recent_actions = [
            f"{record.action.action_type}: {record.action.description} -> {record.success}"
            for record in history[-5:]
        ]
        return f"""
You are validating whether a GUI testing assertion passed.
Return strict JSON with keys: passed, confidence, summary.
The summary field must be concise Simplified Chinese.

Task:
{task.instruction}

Assertion type:
{assertion.type}

Assertion target:
{assertion.expected_text}

Assertion description:
{assertion.description}

Observation text:
{observation.flattened_text[:2000]}

Recent actions:
{recent_actions}
""".strip()

    def _build_progress_prompt(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        latest_action: ActionStep | None,
    ) -> str:
        recent_actions = [
            f"{record.action.action_type}: {record.action.description} -> {record.success}"
            for record in history[-5:]
        ]
        return f"""
You are assessing task completion for a desktop GUI test.
Return strict JSON with keys: success, completion_score, progress_label, summary, evidence, unmet_goals, confidence.
The summary, progress_label, evidence, and unmet_goals fields must be concise Simplified Chinese.
completion_score must be a number between 0 and 1.

Task:
{task.instruction}

Product:
{task.product}

Assertions:
{[assertion.description or assertion.expected_text for assertion in task.assertions]}

Latest action:
{latest_action.description if latest_action else "无"}

Current UI state summary:
{observation.state_assessment.summary if observation.state_assessment else "无"}

Observation text:
{observation.flattened_text[:2200]}

Recent actions:
{recent_actions}
""".strip()

    def _build_reflection_prompt(
        self,
        task: TaskSpec,
        before: Observation,
        after: Observation,
        action: ActionStep,
        validation: ValidationResult,
        progress: ProgressAssessment,
        history: Sequence[StepRecord],
    ) -> str:
        recent_actions = [
            f"{record.action.action_type}: {record.action.description} -> {record.success}"
            for record in history[-5:]
        ]
        return f"""
You are the reflection module for a desktop GUI testing agent.
Return strict JSON with keys: should_replan, root_cause, failure_stage, suggested_strategy, suggested_action, confidence.
The root_cause, failure_stage, and suggested_strategy fields must be concise Simplified Chinese.
If no recovery action is needed, set suggested_action to null.
If suggested_action is provided, it must be a JSON object matching the ActionStep schema with action_type, description, and optional fields.
Prefer safe recovery actions such as wait, hotkey, or noop unless the screenshot strongly supports another action.

Task:
{task.instruction}

Action just executed:
{action.action_type} | {action.description}

Validation result:
{validation.summary}

Progress result:
{progress.summary}

Before-state summary:
{before.state_assessment.summary if before.state_assessment else "无"}

After-state summary:
{after.state_assessment.summary if after.state_assessment else "无"}

Before observation text:
{before.flattened_text[:1600]}

After observation text:
{after.flattened_text[:1600]}

Recent actions:
{recent_actions}
""".strip()


from pathlib import Path
