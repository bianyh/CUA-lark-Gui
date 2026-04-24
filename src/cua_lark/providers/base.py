from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from cua_lark.models import AssertionSpec, Observation, PolicyDecision, StepRecord, TaskSpec, ValidationResult


class VisionPolicy(ABC):
    @abstractmethod
    def plan_next_action(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        remaining_steps: int,
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

