from __future__ import annotations

from pathlib import Path
from typing import Sequence

from cua_lark.models import (
    AssertionSpec,
    Observation,
    StepRecord,
    TaskSpec,
    ValidationEvidence,
    ValidationResult,
)
from cua_lark.providers.base import VisionPolicy
from cua_lark.utils.images import compare_images


class CompositeValidator:
    def __init__(self, vision_policy: VisionPolicy | None = None) -> None:
        self.vision_policy = vision_policy

    def validate_hint(
        self,
        expected_text: str | None,
        observation: Observation,
        history: Sequence[StepRecord],
    ) -> ValidationResult:
        if not expected_text:
            return ValidationResult(
                passed=True,
                summary="当前步骤未设置额外校验提示。",
                strategy="hint_skip",
                confidence=1.0,
            )

        haystack = self._build_haystack(observation, history)
        passed = expected_text in haystack
        return ValidationResult(
            passed=passed,
            summary=(
                f"已命中步骤校验提示：{expected_text}"
                if passed
                else f"未命中步骤校验提示：{expected_text}"
            ),
            strategy="hint_contains",
            confidence=0.9 if passed else 0.2,
            evidence=[ValidationEvidence(type="text_hint", content=haystack[:300], score=0.9 if passed else 0.2)],
        )

    def validate_task(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
    ) -> ValidationResult:
        if not task.assertions:
            return ValidationResult(
                passed=True,
                summary="当前任务未定义显式断言，默认视为通过。",
                strategy="no_assertions",
                confidence=1.0,
            )

        checks: list[ValidationResult] = [
            self.validate_assertion(task, observation, assertion, history) for assertion in task.assertions
        ]
        passed = all(check.passed for check in checks)
        confidence = sum(check.confidence for check in checks) / len(checks)
        evidence = [item for check in checks for item in check.evidence]
        return ValidationResult(
            passed=passed,
            summary="所有断言均已通过。" if passed else "存在至少一个断言失败。",
            strategy="composite",
            confidence=confidence,
            evidence=evidence,
            details={"checks": [check.summary for check in checks]},
        )

    def validate_assertion(
        self,
        task: TaskSpec,
        observation: Observation,
        assertion: AssertionSpec,
        history: Sequence[StepRecord],
    ) -> ValidationResult:
        if assertion.type == "ocr_contains":
            haystack = self._build_haystack(observation, history)
            expected = assertion.expected_text or ""
            passed = expected in haystack
            return ValidationResult(
                passed=passed,
                summary=(
                    f"OCR/文本检索命中目标：{expected}"
                    if passed
                    else f"OCR/文本检索未命中目标：{expected}"
                ),
                strategy="ocr_contains",
                confidence=0.85 if passed else 0.15,
                evidence=[ValidationEvidence(type="text_search", content=haystack[:400], score=0.85 if passed else 0.15)],
            )

        if assertion.type == "image_diff":
            baseline_path = assertion.options.get("baseline_path")
            if not baseline_path:
                return ValidationResult(
                    passed=False,
                    summary="image_diff 断言缺少 baseline_path 配置。",
                    strategy="image_diff",
                    confidence=0.0,
                )
            metrics = compare_images(Path(observation.screenshot_path), Path(baseline_path))
            threshold = float(assertion.options.get("max_difference", 0.15))
            passed = metrics["difference"] <= threshold
            return ValidationResult(
                passed=passed,
                summary=f"图像差异={metrics['difference']:.4f}，阈值={threshold:.4f}",
                strategy="image_diff",
                confidence=metrics["similarity"],
                evidence=[ValidationEvidence(type="image_diff", content=str(metrics), score=metrics["similarity"])],
                details=metrics,
            )

        if assertion.type == "vlm_semantic" and self.vision_policy is not None:
            return self.vision_policy.validate_assertion(task, observation, assertion, history)

        haystack = self._build_haystack(observation, history)
        expected = assertion.expected_text or ""
        passed = True if not expected else expected in haystack
        return ValidationResult(
            passed=passed,
            summary=(
                f"回退校验命中目标：{expected}"
                if passed
                else f"回退校验未命中目标：{expected}"
            ),
            strategy=f"fallback_{assertion.type}",
            confidence=0.3 if passed else 0.1,
            evidence=[ValidationEvidence(type="fallback_text", content=haystack[:300], score=0.3 if passed else 0.1)],
        )

    def _build_haystack(self, observation: Observation, history: Sequence[StepRecord]) -> str:
        parts = [observation.flattened_text]
        parts.extend(record.action.text or "" for record in history if record.action.text)
        parts.extend(record.action.validation_hint or "" for record in history if record.action.validation_hint)
        return "\n".join(part for part in parts if part)
