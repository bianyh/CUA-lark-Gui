from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from cua_lark.models import (
    ActionStep,
    AssertionSpec,
    Observation,
    PolicyDecision,
    ProgressAssessment,
    ReflectionResult,
    StepRecord,
    TaskSpec,
    ValidationResult,
)


class VisionPolicy(ABC):
    @abstractmethod
    def plan_next_action(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        remaining_steps: int,
        planning_hints: Sequence[ActionStep] | None = None,
        latest_reflection: ReflectionResult | None = None,
    ) -> PolicyDecision:
        raise NotImplementedError

    @abstractmethod
    def validate_assertion(
        self,
        task: TaskSpec,
        observation: Observation,
        assertion: AssertionSpec,
        history: Sequence[StepRecord],
    ) -> ValidationResult:
        raise NotImplementedError

    @abstractmethod
    def assess_progress(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        latest_action: ActionStep | None = None,
    ) -> ProgressAssessment:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError
