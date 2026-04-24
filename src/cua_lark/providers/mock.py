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
    backend_name = "mock_policy"

    def __init__(self, fallback_reason: str | None = None) -> None:
        self.fallback_reason = fallback_reason
        self.last_transport: str | None = None

    def plan_next_action(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        remaining_steps: int,
    ) -> PolicyDecision:
        self.last_transport = "mock"
        if history:
            return PolicyDecision(
                done=True,
                rationale="Mock 策略检测到预置脚本动作已执行完毕，安全结束当前任务。",
            )

        return PolicyDecision(
            done=False,
            rationale="当前未配置外部模型，Mock 策略插入一个等待动作以模拟规划流程。",
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
        self.last_transport = "mock"
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
                f"Mock 语义校验通过：{expected}"
                if passed
                else f"Mock 语义校验未通过：{expected}"
            )
            confidence = 0.45 if passed else 0.15
        else:
            passed = True if not expected else expected in haystack
            summary = (
                f"Mock 文本校验命中目标：{expected}"
                if passed
                else f"Mock 文本校验未找到目标：{expected}"
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
