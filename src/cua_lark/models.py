from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class ReplanReason(str, Enum):
    POPUP_OBSTRUCTION = "popup_obstruction"
    LOAD_TIMEOUT = "load_timeout"
    TARGET_MISSING = "target_missing"
    INPUT_FAILED = "input_failed"
    VALIDATION_FAILED = "validation_failed"
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

    @property
    def flattened_text(self) -> str:
        parts = [block.text for block in self.ocr_blocks if block.text.strip()]
        parts.extend(note for note in self.notes if note.strip())
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
        coordinates = data.get("coordinates")
        parsed_coordinates = None
        if isinstance(coordinates, (list, tuple)) and len(coordinates) == 2:
            parsed_coordinates = (int(coordinates[0]), int(coordinates[1]))
        reserved = {
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
        }
        return cls(
            action_type=str(data.get("action_type", "wait")),
            description=str(data.get("description", data.get("action_type", "step"))),
            target=ActionTarget.from_dict(target) if isinstance(target, dict) else None,
            text=str(data["text"]) if data.get("text") is not None else None,
            hotkey=[str(item) for item in data.get("hotkey", [])],
            scroll_amount=int(data.get("scroll_amount", 0)),
            wait_seconds=float(data.get("wait_seconds", 1.0)),
            button=str(data.get("button", "left")),
            confidence=float(data.get("confidence", 0.0)),
            reasoning=str(data.get("reasoning", "")),
            validation_hint=str(data["validation_hint"]) if data.get("validation_hint") is not None else None,
            coordinates=parsed_coordinates,
            metadata={key: value for key, value in data.items() if key not in reserved},
        )


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
    failure_reason: str | None = None
    assumptions: dict[str, Any] = field(default_factory=dict)
