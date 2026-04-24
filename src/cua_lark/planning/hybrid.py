from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from cua_lark.models import Observation, PolicyDecision, StepRecord, TaskSpec
from cua_lark.providers.base import VisionPolicy


@dataclass(slots=True)
class PlanningResult:
    decision: PolicyDecision
    scripted: bool


class HybridPlanner:
    def __init__(self, policy: VisionPolicy | None) -> None:
        self.policy = policy

    def next_action(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        scripted_index: int,
        remaining_steps: int,
    ) -> PlanningResult:
        scripted_actions = task.scripted_actions
        if scripted_index < len(scripted_actions):
            action = scripted_actions[scripted_index]
            return PlanningResult(
                decision=PolicyDecision(
                    done=False,
                    rationale=f"Using scripted action {scripted_index + 1}/{len(scripted_actions)}.",
                    action=action,
                ),
                scripted=True,
            )

        if self.policy is None:
            return PlanningResult(
                decision=PolicyDecision(
                    done=True,
                    rationale="No scripted actions remain and no vision policy is configured.",
                ),
                scripted=False,
            )

        return PlanningResult(
            decision=self.policy.plan_next_action(task, observation, history, remaining_steps),
            scripted=False,
        )

