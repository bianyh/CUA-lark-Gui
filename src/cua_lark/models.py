from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ActionName(str, Enum):
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    DRAG = "drag"
    SCROLL = "scroll"
    TYPE_TEXT = "type_text"
    HOTKEY = "hotkey"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    ASSERT_STATE = "assert_state"
    FINISH = "finish"


RiskLevel = Literal["low", "medium", "high"]


class Point(BaseModel):
    x: int
    y: int


class Bounds(BaseModel):
    left: int
    top: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    def contains(self, point: Point) -> bool:
        return (
            self.left <= point.x <= self.left + self.width
            and self.top <= point.y <= self.top + self.height
        )


class UICandidate(BaseModel):
    label: str
    role: str | None = None
    bounds: Bounds | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class TestCase(BaseModel):
    id: str
    name: str
    product: str
    instruction: str
    preconditions: list[str] = Field(default_factory=list)
    test_data: dict[str, Any] = Field(default_factory=dict)
    expected_result: str
    risk_level: RiskLevel = "low"
    timeout_seconds: int = Field(default=180, gt=0)
    steps: list["StepPlan"] = Field(default_factory=list)


class StepPlan(BaseModel):
    step_id: str
    goal: str
    success_criteria: str
    allowed_actions: list[ActionName] = Field(default_factory=list)
    max_retries: int = Field(default=2, ge=0, le=5)
    requires_confirmation: bool = False

    @field_validator("allowed_actions", mode="before")
    @classmethod
    def _default_allowed_actions(cls, value: Any) -> Any:
        if value:
            return value
        return [
            ActionName.CLICK,
            ActionName.TYPE_TEXT,
            ActionName.HOTKEY,
            ActionName.WAIT,
            ActionName.SCROLL,
            ActionName.SCREENSHOT,
        ]


class Observation(BaseModel):
    screenshot_path: str
    window_bounds: Bounds
    screen_bounds: Bounds | None = None
    window_title: str | None = None
    scale_factor: float = Field(default=1.0, gt=0)
    page_summary: str = ""
    ui_candidates: list[UICandidate] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActionProposal(BaseModel):
    action: ActionName
    target: str = ""
    coordinates: Point | None = None
    end_coordinates: Point | None = None
    text: str | None = None
    hotkeys: list[str] = Field(default_factory=list)
    scroll_amount: int | None = None
    wait_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""
    expected_state: str = ""
    risk: RiskLevel = "low"

    def needs_coordinates(self) -> bool:
        return self.action in {
            ActionName.CLICK,
            ActionName.DOUBLE_CLICK,
            ActionName.RIGHT_CLICK,
            ActionName.DRAG,
        }

    @model_validator(mode="after")
    def _validate_action_payload(self) -> "ActionProposal":
        if self.action in {
            ActionName.CLICK,
            ActionName.DOUBLE_CLICK,
            ActionName.RIGHT_CLICK,
            ActionName.DRAG,
        } and self.coordinates is None:
            raise ValueError(f"{self.action.value} requires coordinates")
        if self.action == ActionName.DRAG and self.end_coordinates is None:
            raise ValueError("drag requires end_coordinates")
        return self


class VerificationResult(BaseModel):
    passed: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = ""
    failure_type: str | None = None
    recommended_next_action: str | None = None


class ExecutionResult(BaseModel):
    executed: bool
    message: str = ""
    duration_ms: int = 0


class TraceEvent(BaseModel):
    case_id: str
    step_id: str
    observation: Observation
    action: ActionProposal | None = None
    execution: ExecutionResult | None = None
    verification: VerificationResult | None = None
    duration_ms: int = 0
    retry_index: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskContext(BaseModel):
    case: TestCase
    run_id: str
    run_dir: str
    status: Literal["pending", "running", "passed", "failed", "blocked"] = "pending"
    current_step_index: int = 0
    traces: list[TraceEvent] = Field(default_factory=list)
    failure_reason: str | None = None

    def add_trace(self, trace: TraceEvent) -> None:
        self.traces.append(trace)


TestCase.model_rebuild()
