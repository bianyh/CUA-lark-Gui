from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from cua_lark.models import ActionStep, Observation, StateAssessment, StepRecord, TaskSpec, UIReadiness


_LOADING_MARKERS = (
    "加载中",
    "正在加载",
    "请稍候",
    "处理中",
    "同步中",
    "连接中",
    "载入中",
    "loading",
    "please wait",
)

_DIALOG_MARKERS = (
    "确定",
    "取消",
    "稍后",
    "知道了",
    "允许",
    "拒绝",
    "重试",
)

_ERROR_MARKERS = (
    "失败",
    "错误",
    "异常",
    "网络",
    "超时",
    "未响应",
    "重试",
)

_SEARCH_MARKERS = ("搜索", "查找", "search")
_CALENDAR_MARKERS = ("日历", "会议", "参会", "忙闲", "calendar")
_IM_MARKERS = ("消息", "发送", "会话", "群", "@", "聊天", "im")
_DOCS_MARKERS = ("文档", "docs", "标题", "分享", "列表")


@dataclass(slots=True)
class StateAnalyzer:
    similarity_threshold: float = 0.992

    def assess(
        self,
        task: TaskSpec,
        observation: Observation,
        action: ActionStep | None = None,
        history: Sequence[StepRecord] = (),
        stable_rounds: int = 0,
        screenshot_similarity: float | None = None,
        timed_out: bool = False,
    ) -> StateAssessment:
        haystack = observation.flattened_text.lower()
        loading_signals = self._match_markers(haystack, _LOADING_MARKERS)
        dialog_signals = self._match_markers(haystack, _DIALOG_MARKERS)
        error_signals = self._match_markers(haystack, _ERROR_MARKERS)
        search_signals = self._match_markers(haystack, _SEARCH_MARKERS)
        calendar_signals = self._match_markers(haystack, _CALENDAR_MARKERS)
        im_signals = self._match_markers(haystack, _IM_MARKERS)
        docs_signals = self._match_markers(haystack, _DOCS_MARKERS)

        readiness = UIReadiness.READY
        if timed_out:
            readiness = UIReadiness.TIMEOUT
        elif loading_signals:
            readiness = UIReadiness.LOADING
        elif not haystack.strip():
            readiness = UIReadiness.UNKNOWN

        state_label = "未知界面"
        state_signals: list[str] = []
        if dialog_signals:
            state_label = "弹窗或确认框"
            state_signals = dialog_signals
        elif error_signals:
            state_label = "异常提示或错误页"
            state_signals = error_signals
        elif calendar_signals or task.product == "calendar":
            state_label = "日历视图"
            state_signals = calendar_signals or [task.product]
        elif docs_signals or task.product == "docs":
            state_label = "文档视图"
            state_signals = docs_signals or [task.product]
        elif search_signals:
            state_label = "搜索结果视图"
            state_signals = search_signals
        elif im_signals or task.product == "im":
            state_label = "即时消息视图"
            state_signals = im_signals or [task.product]
        elif task.product == "cross_product":
            state_label = "跨产品联动视图"
            state_signals = [task.product]

        matched_signals = state_signals + loading_signals
        if action and action.validation_hint:
            matched_signals.append(f"action_hint:{action.validation_hint}")
        confidence = self._confidence_for(
            readiness=readiness,
            state_signals=state_signals,
            loading_signals=loading_signals,
            screenshot_similarity=screenshot_similarity,
        )

        summary_parts = [f"当前状态={state_label}"]
        if readiness == UIReadiness.READY:
            summary_parts.append("加载判断=已完成")
        elif readiness == UIReadiness.LOADING:
            summary_parts.append("加载判断=加载中")
        elif readiness == UIReadiness.TIMEOUT:
            summary_parts.append("加载判断=等待超时")
        else:
            summary_parts.append("加载判断=信息不足")

        if state_signals:
            summary_parts.append(f"状态依据={'/'.join(state_signals[:3])}")
        if loading_signals:
            summary_parts.append(f"加载依据={'/'.join(loading_signals[:3])}")
        if stable_rounds:
            summary_parts.append(f"稳定轮次={stable_rounds}")
        if screenshot_similarity is not None:
            summary_parts.append(f"截图相似度={screenshot_similarity:.3f}")

        return StateAssessment(
            readiness=readiness,
            state_label=state_label,
            summary="，".join(summary_parts),
            matched_signals=matched_signals,
            confidence=confidence,
            stable_rounds=stable_rounds,
            screenshot_similarity=screenshot_similarity,
            timed_out=timed_out,
        )

    def requires_additional_wait(
        self,
        observation: Observation,
        action: ActionStep | None,
        assessment: StateAssessment,
    ) -> bool:
        capture_mode = str(observation.ui_hints.get("capture_mode", "unknown"))
        if capture_mode == "mock":
            return False
        if assessment.readiness == UIReadiness.LOADING:
            return True
        if action is None:
            return False
        return action.action_type in {"click", "double_click", "right_click", "hotkey", "scroll"}

    def is_stable(
        self,
        assessment: StateAssessment,
        screenshot_similarity: float | None,
    ) -> bool:
        if assessment.readiness == UIReadiness.LOADING:
            return False
        if screenshot_similarity is None:
            return assessment.readiness != UIReadiness.TIMEOUT
        return screenshot_similarity >= self.similarity_threshold

    def _match_markers(self, haystack: str, markers: Sequence[str]) -> list[str]:
        return [marker for marker in markers if marker in haystack]

    def _confidence_for(
        self,
        readiness: UIReadiness,
        state_signals: Sequence[str],
        loading_signals: Sequence[str],
        screenshot_similarity: float | None,
    ) -> float:
        base = 0.4
        if readiness == UIReadiness.LOADING:
            base = 0.85 if loading_signals else 0.55
        elif readiness == UIReadiness.READY:
            base = 0.75 if state_signals else 0.55
        elif readiness == UIReadiness.TIMEOUT:
            base = 0.9
        if screenshot_similarity is not None:
            base = min(0.98, max(base, screenshot_similarity))
        return round(base, 4)
