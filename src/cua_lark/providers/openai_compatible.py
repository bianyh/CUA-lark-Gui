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
    ReplanReason,
    StepRecord,
    TaskSpec,
    ValidationEvidence,
    ValidationResult,
)
from cua_lark.providers.base import VisionPolicy
from cua_lark.utils.images import encode_image_as_data_url


class OpenAICompatibleVisionPolicy(VisionPolicy):
    def __init__(self, settings: Settings) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai is not installed. Run `python -m pip install -e .`.") from exc

        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        self._client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        self._settings = settings

    def plan_next_action(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        remaining_steps: int,
    ) -> PolicyDecision:
        prompt = self._build_planning_prompt(task, observation, history, remaining_steps)
        raw = self._call_model(prompt, observation.screenshot_path, detail="auto")
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
        raw = self._call_model(prompt, observation.screenshot_path, detail="high")
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

    def _call_model(self, prompt: str, screenshot_path: str, detail: str) -> str:
        image_url = encode_image_as_data_url(Path(screenshot_path))

        try:
            response = self._client.responses.create(
                model=self._settings.openai_model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": image_url},
                        ],
                    }
                ],
            )
            output_text = getattr(response, "output_text", None)
            if output_text:
                return str(output_text)
        except Exception:
            pass

        completion = self._client.chat.completions.create(
            model=self._settings.openai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a GUI planning and validation assistant. Return JSON only."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url, "detail": detail}},
                    ],
                },
            ],
        )
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


from pathlib import Path

