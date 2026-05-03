from __future__ import annotations

import json
from pathlib import Path
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
from cua_lark.utils.images import encode_image_as_data_url, resized_dimensions


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
        planning_hints: Sequence[ActionStep] | None = None,
        latest_reflection: ReflectionResult | None = None,
    ) -> PolicyDecision:
        prompt = self._build_planning_prompt(
            task,
            observation,
            history,
            remaining_steps,
            planning_hints=planning_hints,
            latest_reflection=latest_reflection,
        )
        raw = self._call_model(prompt, [observation.screenshot_path], detail="auto")
        data = self._extract_json(raw)
        action = ActionStep.from_dict(data["action"]) if isinstance(data.get("action"), dict) else None
        if action is not None:
            self._annotate_action_coordinates(action, observation)
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
                score=self._coerce_confidence(data.get("confidence", 0.0)),
            )
        ]
        return ValidationResult(
            passed=self._coerce_bool(data.get("passed", False)),
            summary=str(data.get("summary", "")),
            strategy=f"openai_{assertion.type}",
            confidence=self._coerce_confidence(data.get("confidence", 0.0)),
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
            success=self._coerce_bool(data.get("success", False)),
            completion_score=self._coerce_ratio(data.get("completion_score", 0.0)),
            progress_label=str(data.get("progress_label", "未知")),
            summary=str(data.get("summary", "")),
            evidence=evidence,
            unmet_goals=unmet_goals,
            confidence=self._coerce_confidence(data.get("confidence", 0.0)),
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
            should_replan=self._coerce_bool(data.get("should_replan", False)),
            root_cause=str(data.get("root_cause", "")),
            failure_stage=str(data.get("failure_stage", "")),
            suggested_strategy=str(data.get("suggested_strategy", "")),
            suggested_action=suggested_action,
            confidence=self._coerce_confidence(data.get("confidence", 0.0)),
        )

    def _call_model(self, prompt: str, screenshot_paths: Sequence[str], detail: str) -> str:
        max_side = self._settings.api_multi_image_max_side if len(screenshot_paths) > 1 else self._settings.api_image_max_side
        image_urls = [
            encode_image_as_data_url(
                Path(path),
                max_side=max_side,
                jpeg_quality=self._settings.api_image_jpeg_quality,
            )
            for path in screenshot_paths
        ]

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
        try:
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
            self.last_error = None
            return completion.choices[0].message.content or "{}"
        except Exception as exc:
            self.last_transport = "chat.completions_failed"
            self.last_error = str(exc)
            if "413" in str(exc) or "Request Entity Too Large" in str(exc):
                raise RuntimeError(
                    "多模态请求体过大，截图上传超过接口限制。已尝试压缩图片，但当前请求仍然过大。"
                ) from exc
            raise

    def _extract_json(self, raw: str) -> dict:
        text = str(raw).strip()
        try:
            return self._coerce_json_object(json.loads(text))
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        candidates: list[dict] = []
        for match in re.finditer(r"[\{\[]", text):
            try:
                value, _ = decoder.raw_decode(text[match.start() :])
            except json.JSONDecodeError:
                continue
            candidate = self._coerce_json_object(value, strict=False)
            if candidate is not None:
                candidates.append(candidate)

        if not candidates:
            raise RuntimeError(f"Model did not return JSON. Raw output: {text[:500]}")

        return self._select_json_candidate(candidates)

    def _coerce_json_object(self, value, strict: bool = True) -> dict | None:
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    return item
        if strict:
            raise RuntimeError(f"Model JSON root must be an object. Raw JSON root type: {type(value).__name__}")
        return None

    def _select_json_candidate(self, candidates: Sequence[dict]) -> dict:
        preferred_keys = {
            "done",
            "action",
            "passed",
            "summary",
            "success",
            "completion_score",
            "should_replan",
            "root_cause",
        }
        for candidate in candidates:
            if any(key in candidate for key in preferred_keys):
                return candidate
        return candidates[0]

    def _coerce_confidence(self, value) -> float:
        if isinstance(value, (int, float)):
            return self._normalize_ratio(float(value))
        text = str(value).strip()
        if not text:
            return 0.0

        confidence_map = {
            "极低": 0.1,
            "很低": 0.15,
            "较低": 0.25,
            "低": 0.3,
            "偏低": 0.35,
            "中低": 0.4,
            "中等": 0.55,
            "一般": 0.55,
            "中": 0.55,
            "中高": 0.7,
            "较高": 0.75,
            "高": 0.85,
            "很高": 0.92,
            "极高": 0.97,
        }
        if text in confidence_map:
            return confidence_map[text]

        percent_match = re.search(r"(-?\d+(?:\.\d+)?)\s*%", text)
        if percent_match:
            return self._normalize_ratio(float(percent_match.group(1)) / 100.0)

        number_match = re.search(r"-?\d+(?:\.\d+)?", text)
        if number_match:
            return self._normalize_ratio(float(number_match.group(0)))

        return 0.0

    def _coerce_ratio(self, value) -> float:
        return self._coerce_confidence(value)

    def _coerce_bool(self, value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        return text in {"true", "1", "yes", "y", "pass", "passed", "成功", "是", "需要", "已完成"}

    def _normalize_ratio(self, value: float) -> float:
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    def _annotate_action_coordinates(self, action: ActionStep, observation: Observation) -> None:
        if action.coordinates is None:
            return
        original_size = tuple(int(item) for item in observation.screen_size)
        max_side = self._settings.api_image_max_side
        api_size = resized_dimensions(original_size, max_side)
        action.metadata.setdefault("coordinate_mode", self._settings.coordinate_mode)
        action.metadata.setdefault("source_image_size", list(api_size))
        action.metadata.setdefault("screenshot_size", list(original_size))
        action.metadata.setdefault("api_image_max_side", max_side)
        action.metadata.setdefault("coordinate_source", "model")

    def _build_planning_prompt(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        remaining_steps: int,
        planning_hints: Sequence[ActionStep] | None = None,
        latest_reflection: ReflectionResult | None = None,
    ) -> str:
        recent_actions = [
            " | ".join(
                part
                for part in [
                    f"{record.index}.{record.attempt} {record.action.action_type}: {record.action.description}",
                    f"success={record.success}",
                    f"validation={record.validation.summary}" if record.validation else "",
                    f"reflection={record.reflection.suggested_strategy}" if record.reflection else "",
                ]
                if part
            )
            for record in history[-5:]
        ]
        hint_lines = [
            f"{index}. {hint.action_type}: {hint.description}"
            f"{f' | text={hint.text}' if hint.text else ''}"
            f"{f' | hotkey={'+'.join(hint.hotkey)}' if hint.hotkey else ''}"
            f"{f' | validation_hint={hint.validation_hint}' if hint.validation_hint else ''}"
            for index, hint in enumerate(planning_hints or [], start=1)
        ]
        reflection_text = "无"
        if latest_reflection is not None:
            reflection_text = (
                f"should_replan={latest_reflection.should_replan}; "
                f"stage={latest_reflection.failure_stage}; "
                f"root_cause={latest_reflection.root_cause}; "
                f"strategy={latest_reflection.suggested_strategy}"
            )
        return f"""
You are controlling the Feishu desktop client as a testing agent.
Return strict JSON with keys: done, rationale, replan_reason, action.
Allowed action types: click, double_click, right_click, drag, scroll, type_text, hotkey, wait, assert, noop.
If no action is needed, set done=true and action=null.
The rationale field must be concise Simplified Chinese.
Decide only the next action from the current screenshot and history. Do not execute a fixed prewritten plan.
Scripted hints are optional examples, not mandatory steps. Skip any hint that is already satisfied, stale, or unsafe for the current UI.
When the latest reflection says replanning is needed, revise the strategy and avoid repeating the failed action unless the current observation strongly justifies it.
For visible UI controls, prefer click/double_click with coordinates from the current screenshot when that is more reliable than a hotkey.
Coordinates must be pixel coordinates relative to the provided screenshot/window image, not absolute desktop coordinates.
The screenshot/window image size is {observation.screen_size[0]}x{observation.screen_size[1]} before upload.
If image compression changes the transmitted size, return coordinates for the image you see; the executor will rescale them.
If unsure, return normalized_coordinates as [x_ratio, y_ratio] between 0 and 1 in action.metadata.
The screenshot may contain multiple Feishu windows, such as the main app window plus a modal or child editor window.
Use the visible active modal/child window when the task is currently asking for details inside that window.
window_candidates in the observation text includes each detected window title, role, active flag, absolute region, and relative_region inside the screenshot.
For hotkeys, return hotkey as an array such as ["ctrl","k"], never as one combined string.
For Chinese or mixed-language input, use type_text with the exact text to paste.
If the target chat is already open and the message box is visible, the next useful action is type_text with "Hello World"; do not keep clicking the same message box.
If "Hello World" is already typed in the message box, the next useful action is hotkey ["enter"] or clicking the send button.
Avoid repeating the same click coordinate when recent actions show no progress.

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

Latest reflection:
{reflection_text}

Optional scripted hints:
{hint_lines}
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
