from __future__ import annotations

import re
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
        planning_hints: Sequence[ActionStep] | None = None,
        latest_reflection: ReflectionResult | None = None,
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

    def assess_progress(
        self,
        task: TaskSpec,
        observation: Observation,
        history: Sequence[StepRecord],
        latest_action: ActionStep | None = None,
    ) -> ProgressAssessment:
        self.last_transport = "mock"
        haystack = self._build_haystack(observation, history, latest_action)
        matched_goals: list[str] = []
        unmet_goals: list[str] = []
        goals = [assertion for assertion in task.assertions if assertion.expected_text or assertion.description]

        for assertion in goals:
            goal = assertion.expected_text or assertion.description
            if assertion.type == "vlm_semantic":
                matched = self._semantic_progress_match(goal or "", haystack, history, latest_action, observation)
            else:
                matched = bool(goal and goal in haystack)
            if matched:
                matched_goals.append(goal or assertion.type)
            else:
                unmet_goals.append(goal or assertion.type)

        if goals:
            completion_score = len(matched_goals) / len(goals)
            success = len(unmet_goals) == 0
        else:
            completion_score = 1.0 if haystack.strip() else 0.0
            success = completion_score >= 0.8
            if latest_action and latest_action.validation_hint:
                matched_goals.append(latest_action.validation_hint)

        progress_label = self._progress_label(completion_score, success)
        summary = (
            f"当前任务已完成，完成度={completion_score:.2f}"
            if success
            else f"当前任务尚未完成，完成度={completion_score:.2f}"
        )
        if matched_goals:
            summary += f"，已满足目标={' / '.join(matched_goals[:3])}"
        if unmet_goals:
            summary += f"，未满足目标={' / '.join(unmet_goals[:3])}"

        confidence = 0.85 if success else 0.4 if completion_score > 0 else 0.2
        return ProgressAssessment(
            success=success,
            completion_score=round(completion_score, 4),
            progress_label=progress_label,
            summary=summary,
            evidence=matched_goals[:5],
            unmet_goals=unmet_goals[:5],
            confidence=confidence,
        )

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
        self.last_transport = "mock"
        if validation.passed and progress.completion_score >= 0.5:
            return ReflectionResult(
                should_replan=False,
                root_cause="当前步骤已达到预期，无需额外反思。",
                failure_stage="无",
                suggested_strategy="继续按既定流程执行后续步骤。",
                confidence=0.85,
            )

        readiness = after.state_assessment.readiness.value if after.state_assessment else "unknown"
        if after.state_assessment and after.state_assessment.readiness.name in {"LOADING", "TIMEOUT"}:
            return ReflectionResult(
                should_replan=True,
                root_cause="动作执行后界面仍在加载或等待超时，当前截图不足以支持下一步。",
                failure_stage="加载阶段",
                suggested_strategy="先等待界面稳定，再重新执行原动作或继续下一步。",
                suggested_action=ActionStep(
                    action_type="wait",
                    description="等待界面完成加载",
                    wait_seconds=1.0,
                ),
                confidence=0.8,
            )

        if action.action_type == "type_text":
            strategy = "输入可能未真正生效，建议先等待或重新聚焦输入区后再输入。"
            suggested_action = ActionStep(
                action_type="wait",
                description="短暂等待输入框状态稳定",
                wait_seconds=0.8,
            )
            return ReflectionResult(
                should_replan=True,
                root_cause="输入动作后的界面反馈不足，可能未聚焦正确输入区域。",
                failure_stage="输入阶段",
                suggested_strategy=strategy,
                suggested_action=suggested_action,
                confidence=0.72,
            )

        if action.action_type in {"click", "double_click", "hotkey"}:
            return ReflectionResult(
                should_replan=True,
                root_cause="交互动作后未看到预期界面反馈，可能未命中正确入口或反馈尚未出现。",
                failure_stage="交互阶段",
                suggested_strategy="先进行短暂等待并重新观察界面，再决定是否重试原动作。",
                suggested_action=ActionStep(
                    action_type="wait",
                    description="等待交互后的界面反馈",
                    wait_seconds=1.0,
                ),
                confidence=0.68,
            )

        return ReflectionResult(
            should_replan=not validation.passed,
            root_cause=f"当前步骤未达到预期：{validation.summary}",
            failure_stage=f"动作阶段({action.action_type})",
            suggested_strategy="重新观察界面，必要时换用更保守的路径继续执行。",
            suggested_action=ActionStep(
                action_type="wait",
                description="等待并重新观察当前界面",
                wait_seconds=1.0,
            ),
            confidence=0.6 if not validation.passed else 0.45,
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

    def _semantic_progress_match(
        self,
        expected: str,
        haystack: str,
        history: Sequence[StepRecord],
        latest_action: ActionStep | None,
        observation: Observation | None = None,
    ) -> bool:
        if not expected:
            return True
        if expected in haystack:
            return True

        sent_messages = []
        if observation is not None:
            maybe_sent = observation.ui_hints.get("sent_messages")
            if isinstance(maybe_sent, list):
                sent_messages = [str(item) for item in maybe_sent if str(item).strip()]
        if any(message and message in expected for message in sent_messages):
            return True

        tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,}", expected)
            if token not in {"成功", "创建", "验证", "会议", "消息"}
        ]
        if not tokens:
            return len(history) >= 2
        matched = sum(1 for token in tokens if token in haystack)
        return matched >= max(2, len(tokens) // 2 + 1)

    def _build_haystack(
        self,
        observation: Observation,
        history: Sequence[StepRecord],
        latest_action: ActionStep | None = None,
    ) -> str:
        haystack_parts = [observation.flattened_text]
        haystack_parts.extend(record.action.text or "" for record in history if record.action.text)
        haystack_parts.extend(
            record.action.validation_hint or ""
            for record in history
            if record.action.validation_hint
        )
        if latest_action and latest_action.text:
            haystack_parts.append(latest_action.text)
        if latest_action and latest_action.validation_hint:
            haystack_parts.append(latest_action.validation_hint)
        return "\n".join(part for part in haystack_parts if part)

    def _progress_label(self, completion_score: float, success: bool) -> str:
        if success:
            return "已完成"
        if completion_score >= 0.66:
            return "进展明显"
        if completion_score > 0:
            return "部分完成"
        return "尚未完成"
