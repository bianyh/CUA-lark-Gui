from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from pathlib import Path
from typing import Any


class ReplanReason(str, Enum):
    POPUP_OBSTRUCTION = "popup_obstruction"
    LOAD_TIMEOUT = "load_timeout"
    TARGET_MISSING = "target_missing"
    INPUT_FAILED = "input_failed"
    VALIDATION_FAILED = "validation_failed"
    UNKNOWN = "unknown"


class UIReadiness(str, Enum):
    READY = "ready"
    LOADING = "loading"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class BoundingBox:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BoundingBox":
        return cls(
            x=int(data["x"]),
            y=int(data["y"]),
            width=int(data["width"]),
            height=int(data["height"]),
        )


@dataclass(slots=True)
class OCRBlock:
    text: str
    confidence: float = 0.0
    bbox: BoundingBox | None = None


@dataclass(slots=True)
class StateAssessment:
    readiness: UIReadiness
    state_label: str
    summary: str
    matched_signals: list[str] = field(default_factory=list)
    confidence: float = 0.0
    stable_rounds: int = 0
    screenshot_similarity: float | None = None
    timed_out: bool = False


@dataclass(slots=True)
class ActionTarget:
    label: str
    bbox: BoundingBox | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionTarget":
        bbox = data.get("bbox")
        return cls(
            label=str(data.get("label", "")),
            bbox=BoundingBox.from_dict(bbox) if isinstance(bbox, dict) else None,
            confidence=float(data.get("confidence", 0.0)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class Observation:
    screenshot_path: str
    timestamp: datetime
    window_title: str
    screen_size: tuple[int, int]
    ocr_blocks: list[OCRBlock] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ui_hints: dict[str, Any] = field(default_factory=dict)
    state_assessment: StateAssessment | None = None

    @property
    def flattened_text(self) -> str:
        parts = [block.text for block in self.ocr_blocks if block.text.strip()]
        parts.extend(note for note in self.notes if note.strip())
        if self.state_assessment is not None:
            parts.append(self.state_assessment.state_label)
            parts.append(self.state_assessment.summary)
            parts.extend(self.state_assessment.matched_signals)
        for value in self.ui_hints.values():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (list, tuple)):
                parts.extend(str(item) for item in value if str(item).strip())
            elif value is not None:
                parts.append(str(value))
        return "\n".join(parts)


@dataclass(slots=True)
class AssertionSpec:
    type: str
    expected_text: str | None = None
    description: str = ""
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssertionSpec":
        reserved = {"type", "expected_text", "description"}
        return cls(
            type=str(data.get("type", "ocr_contains")),
            expected_text=str(data["expected_text"]) if data.get("expected_text") is not None else None,
            description=str(data.get("description", "")),
            options={key: value for key, value in data.items() if key not in reserved},
        )


@dataclass(slots=True)
class ActionStep:
    action_type: str
    description: str
    target: ActionTarget | None = None
    text: str | None = None
    hotkey: list[str] = field(default_factory=list)
    scroll_amount: int = 0
    wait_seconds: float = 1.0
    button: str = "left"
    confidence: float = 0.0
    reasoning: str = ""
    validation_hint: str | None = None
    coordinates: tuple[int, int] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionStep":
        target = data.get("target")
        action_type = cls._parse_action_type(data)
        parsed_coordinates = cls._parse_coordinates(data.get("coordinates"))
        if parsed_coordinates is None:
            parsed_coordinates = cls._parse_coordinates_from_xy(data)
        reserved = {
            "type",
            "action_type",
            "description",
            "target",
            "text",
            "hotkey",
            "scroll_amount",
            "wait_seconds",
            "button",
            "confidence",
            "reasoning",
            "validation_hint",
            "coordinates",
            "x",
            "y",
        }
        return cls(
            action_type=action_type,
            description=str(data.get("description", data.get("reasoning", action_type))),
            target=ActionTarget.from_dict(target) if isinstance(target, dict) else None,
            text=str(data["text"]) if data.get("text") is not None else None,
            hotkey=cls._parse_hotkey(data.get("hotkey", [])),
            scroll_amount=int(data.get("scroll_amount", 0)),
            wait_seconds=float(data.get("wait_seconds", 1.0)),
            button=str(data.get("button", "left")),
            confidence=float(data.get("confidence", 0.0)),
            reasoning=str(data.get("reasoning", "")),
            validation_hint=cls._parse_validation_hint(data, action_type),
            coordinates=parsed_coordinates,
            metadata={key: value for key, value in data.items() if key not in reserved},
        )

    @classmethod
    def _parse_action_type(cls, data: dict[str, Any]) -> str:
        raw_type = data.get("action_type", data.get("type"))
        if raw_type is None:
            if data.get("hotkey") is not None:
                return "hotkey"
            if data.get("text") is not None:
                return "type_text"
            if data.get("coordinates") is not None or ("x" in data and "y" in data):
                return "click"
            return "wait"

        action_type = str(raw_type).strip().lower()
        aliases = {
            "type": "type_text",
            "input": "type_text",
            "text": "type_text",
            "keypress": "hotkey",
            "key_press": "hotkey",
            "shortcut": "hotkey",
            "tap": "click",
            "left_click": "click",
            "doubleclick": "double_click",
            "rightclick": "right_click",
        }
        return aliases.get(action_type, action_type)

    @classmethod
    def _parse_coordinates(cls, value: Any) -> tuple[int, int] | None:
        if isinstance(value, dict) and "x" in value and "y" in value:
            return (int(value["x"]), int(value["y"]))
        if isinstance(value, str):
            numbers = re.findall(r"-?\d+(?:\.\d+)?", value)
            if len(numbers) >= 2:
                return (int(float(numbers[0])), int(float(numbers[1])))
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return (int(value[0]), int(value[1]))
        return None

    @classmethod
    def _parse_coordinates_from_xy(cls, data: dict[str, Any]) -> tuple[int, int] | None:
        if "x" not in data or "y" not in data:
            return None
        return (int(float(data["x"])), int(float(data["y"])))

    @classmethod
    def _parse_validation_hint(cls, data: dict[str, Any], action_type: str) -> str | None:
        if data.get("validation_hint") is not None:
            return str(data["validation_hint"])
        if action_type == "type_text" and data.get("text") is not None:
            return str(data["text"])
        return None

    @classmethod
    def _parse_hotkey(cls, value: Any) -> list[str]:
        if value is None:
            return []
        raw_items = value if isinstance(value, (list, tuple)) else [value]
        keys: list[str] = []
        for item in raw_items:
            text = str(item).strip()
            if not text:
                continue
            parts = re.split(r"\s*(?:\+|,|;)\s*", text)
            keys.extend(cls._normalize_key(part) for part in parts if part.strip())
        return [key for key in keys if key]

    @classmethod
    def _normalize_key(cls, value: str) -> str:
        key = value.strip().lower().replace(" ", "")
        aliases = {
            "control": "ctrl",
            "ctrlleft": "ctrl",
            "ctrlright": "ctrl",
            "return": "enter",
            "escape": "esc",
            "windows": "win",
            "command": "win",
            "cmd": "win",
            "option": "alt",
            "del": "delete",
        }
        return aliases.get(key, key)


@dataclass(slots=True)
class TaskSpec:
    id: str
    product: str
    instruction: str
    preconditions: list[str] = field(default_factory=list)
    assertions: list[AssertionSpec] = field(default_factory=list)
    cleanup: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskSpec":
        return cls(
            id=str(data["id"]),
            product=str(data.get("product", "unknown")),
            instruction=str(data.get("instruction", "")),
            preconditions=[str(item) for item in data.get("preconditions", [])],
            assertions=[AssertionSpec.from_dict(item) for item in data.get("assertions", [])],
            cleanup=[str(item) for item in data.get("cleanup", [])],
            tags=[str(item) for item in data.get("tags", [])],
            metadata=dict(data.get("metadata", {})),
        )

    @property
    def scripted_actions(self) -> list[ActionStep]:
        return [ActionStep.from_dict(item) for item in self.metadata.get("scripted_actions", [])]


@dataclass(slots=True)
class PolicyDecision:
    done: bool
    rationale: str
    action: ActionStep | None = None
    replan_reason: ReplanReason | None = None


@dataclass(slots=True)
class ValidationEvidence:
    type: str
    content: str
    score: float = 0.0
    path: str | None = None


@dataclass(slots=True)
class ValidationResult:
    passed: bool
    summary: str
    strategy: str
    confidence: float = 0.0
    evidence: list[ValidationEvidence] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProgressAssessment:
    success: bool
    completion_score: float
    progress_label: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    unmet_goals: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(slots=True)
class ReflectionResult:
    should_replan: bool
    root_cause: str
    failure_stage: str
    suggested_strategy: str
    suggested_action: ActionStep | None = None
    confidence: float = 0.0


@dataclass(slots=True)
class StepRecord:
    index: int
    attempt: int
    action: ActionStep
    success: bool
    rationale: str
    started_at: datetime
    ended_at: datetime
    observation_before: Observation
    observation_after: Observation
    validation: ValidationResult | None = None
    state_assessment: StateAssessment | None = None
    progress_assessment: ProgressAssessment | None = None
    reflection: ReflectionResult | None = None
    error: str | None = None
    replan_reason: ReplanReason | None = None
    executor_state: dict[str, Any] = field(default_factory=dict)
    execution_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunReport:
    task_id: str
    product: str
    status: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    output_dir: Path
    artifact_dir: Path
    step_records: list[StepRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    final_validation: ValidationResult | None = None
    final_progress: ProgressAssessment | None = None
    failure_reason: str | None = None
    assumptions: dict[str, Any] = field(default_factory=dict)
