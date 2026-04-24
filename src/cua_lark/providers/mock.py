from __future__ import annotations

import re
from typing import Sequence

from cua_lark.models import (
    ActionStep,
    AssertionSpec,
    Observation,
    PolicyDecision,
    StepRecord,
    TaskSpec,
    ValidationEvidence,
    ValidationResult,
)
from cua_lark.providers.base import VisionPolicy


class MockVisionPolicy(VisionPolicy):
    def plan_next_action(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        remaining_steps: int,
    ) -> PolicyDecision:
        if history:
            return PolicyDecision(
                done=True,
                rationale="Mock policy reached a safe stop because no scripted actions remain.",
            )

        return PolicyDecision(
            done=False,
            rationale="Mock policy inserted a wait action because no external model is configured.",
            action=ActionStep(
                action_type="wait",
                description="等待界面稳定",
                wait_seconds=1.0,
                validation_hint=None,
            ),
        )

    def validate_assertion(
        self,
        task: TaskSpec,
        observation: Observation,
        assertion: AssertionSpec,
        history: Sequence[StepRecord],
    ) -> ValidationResult:
        haystack_parts = [observation.flattened_text]
        haystack_parts.extend(record.action.text or "" for record in history if record.action.text)
        haystack_parts.extend(
            record.action.validation_hint or ""
            for record in history
            if record.action.validation_hint
        )
        haystack = "\n".join(part for part in haystack_parts if part)
        expected = assertion.expected_text or ""
        if assertion.type == "vlm_semantic":
            passed = self._semantic_match(expected, haystack, task, history)
            summary = (
                f"Mock semantic validation accepted assertion: {expected}"
                if passed
                else f"Mock semantic validation could not justify assertion: {expected}"
            )
            confidence = 0.45 if passed else 0.15
        else:
            passed = True if not expected else expected in haystack
            summary = (
                f"Mock validation matched expected text: {expected}"
                if passed
                else f"Mock validation could not find expected text: {expected}"
            )
            confidence = 0.35 if passed else 0.1
        return ValidationResult(
            passed=passed,
            summary=summary,
            strategy=f"mock_{assertion.type}",
            confidence=confidence,
            evidence=[ValidationEvidence(type="mock_text", content=haystack[:300], score=confidence)],
        )

    def _semantic_match(
        self,
        expected: str,
        haystack: str,
        task: TaskSpec,
        history: Sequence[StepRecord],
    ) -> bool:
        if not haystack.strip():
            return False
        if not expected:
            return True
        if expected in haystack:
            return True

        history_texts = [record.action.text for record in history if record.action.text]
        if any(text and text in expected for text in history_texts):
            return True

        tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,}", expected)
            if token not in {"成功", "创建", "验证", "会议", "消息"}
        ]
        if not tokens:
            return bool(history)

        matched = sum(1 for token in tokens if token in haystack or token in task.instruction)
        if matched >= max(1, len(tokens) // 2):
            return True
        return len(history) >= 2 and bool(haystack.strip())
