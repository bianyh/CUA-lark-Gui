from __future__ import annotations

from typing import Any

from cua_lark.llm import VLMClient
from cua_lark.models import StepPlan, TestCase


class TestPlannerAgent:
    def __init__(self, vlm: VLMClient | None):
        self.vlm = vlm

    def plan(self, case: TestCase) -> list[StepPlan]:
        if case.steps:
            return case.steps
        if self.vlm is None:
            return [
                StepPlan(
                    step_id="1",
                    goal=case.instruction,
                    success_criteria=case.expected_result,
                    max_retries=2,
                )
            ]

        prompt = (
            "Convert this Feishu/Lark GUI test case into executable GUI steps. "
            "Return JSON: {\"steps\": [{\"step_id\": \"1\", \"goal\": \"...\", "
            "\"success_criteria\": \"...\", \"allowed_actions\": [\"click\", "
            "\"type_text\", \"hotkey\", \"wait\", \"scroll\", \"screenshot\"], "
            "\"max_retries\": 2, \"requires_confirmation\": false}]}.\n\n"
            f"Case id: {case.id}\n"
            f"Product: {case.product}\n"
            f"Instruction: {case.instruction}\n"
            f"Expected result: {case.expected_result}\n"
            f"Test data: {case.test_data}"
        )
        data = self.vlm.complete_json(prompt)
        raw_steps = data.get("steps", [])
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("Planner returned no steps")
        return [self._parse_step(raw, index) for index, raw in enumerate(raw_steps, start=1)]

    @staticmethod
    def _parse_step(raw: Any, index: int) -> StepPlan:
        if not isinstance(raw, dict):
            raise ValueError(f"Planner step {index} is not an object")
        raw.setdefault("step_id", str(index))
        raw.setdefault("max_retries", 2)
        raw.setdefault("requires_confirmation", False)
        return StepPlan(**raw)
