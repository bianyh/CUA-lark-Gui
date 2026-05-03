from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from cua_lark.models import Observation, PolicyDecision, ReflectionResult, StepRecord, TaskSpec
from cua_lark.providers.base import VisionPolicy


@dataclass(slots=True)
class PlanningResult:
    decision: PolicyDecision
    scripted: bool


class HybridPlanner:
    def __init__(self, policy: VisionPolicy | None, prefer_scripted: bool = False) -> None:
        self.policy = policy
        self.prefer_scripted = prefer_scripted

    def next_action(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        scripted_index: int,
        remaining_steps: int,
        latest_reflection: ReflectionResult | None = None,
    ) -> PlanningResult:
        scripted_actions = task.scripted_actions
        if self.prefer_scripted and scripted_index < len(scripted_actions):
            action = scripted_actions[scripted_index]
            return PlanningResult(
                decision=PolicyDecision(
                    done=False,
                    rationale=f"采用预置脚本动作 {scripted_index + 1}/{len(scripted_actions)}。",
                    action=action,
                ),
                scripted=True,
            )

        if self.policy is None:
            if scripted_index < len(scripted_actions):
                action = scripted_actions[scripted_index]
                return PlanningResult(
                    decision=PolicyDecision(
                        done=False,
                        rationale="当前没有可用的视觉策略，回退到预置脚本动作。",
                        action=action,
                    ),
                    scripted=True,
                )
            return PlanningResult(
                decision=PolicyDecision(
                    done=True,
                    rationale="当前没有可用的视觉策略，也没有可执行的回退动作。",
                ),
                scripted=False,
            )

        return PlanningResult(
            decision=self.policy.plan_next_action(
                task,
                observation,
                history,
                remaining_steps,
                planning_hints=scripted_actions,
                latest_reflection=latest_reflection,
            ),
            scripted=False,
        )
