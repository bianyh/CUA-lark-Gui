from __future__ import annotations

from datetime import datetime
from typing import Any

from cua_lark.config import Settings
from cua_lark.models import ActionStep, Observation, PolicyDecision, RunReport, TaskSpec, ValidationResult


class RuntimeConsole:
    def __init__(self, enabled: bool = True, preview_chars: int = 80) -> None:
        self.enabled = enabled
        self.preview_chars = max(20, preview_chars)

    def task_start(
        self,
        task: TaskSpec,
        settings: Settings,
        policy: Any,
        executor: Any,
        ocr_provider: Any,
        focus_result: bool,
    ) -> None:
        self._emit("任务", f"开始执行用例 `{task.id}`，产品=`{task.product}`")
        self._emit("指令", self._trim(task.instruction))
        self._emit(
            "环境",
            "运行模式="
            f"{'Mock' if settings.mock_mode else 'Desktop'} | "
            f"规划器={self._describe_component(policy)} | "
            f"执行器={self._describe_component(executor)} | "
            f"OCR={self._describe_component(ocr_provider)}",
        )
        self._emit(
            "窗口",
            f"目标窗口关键字=`{settings.window_title_keyword}`，"
            f"{'已尝试聚焦窗口' if focus_result else '未能确认窗口聚焦，继续执行'}",
        )
        if task.preconditions:
            self._emit("前置", "；".join(self._trim(item) for item in task.preconditions[:3]))

    def observation(self, step_index: int, observation: Observation) -> None:
        preview = self._observation_preview(observation)
        self._emit(
            f"观察 {step_index}",
            f"截图已采集，OCR块数={len(observation.ocr_blocks)}，窗口=`{observation.window_title}`，"
            f"内容预览={preview}",
        )

    def planning(
        self,
        step_index: int,
        decision: PolicyDecision,
        source_label: str,
        action: ActionStep | None,
        policy: Any,
    ) -> None:
        if decision.done or action is None:
            self._emit(
                f"规划 {step_index}",
                f"未生成后续动作，准备结束当前任务。原因：{self._trim(decision.rationale)}",
            )
            return
        route = getattr(policy, "last_transport", None)
        route_text = ""
        if source_label != "脚本动作" and route:
            route_text = f"，模型通道={self._route_name(route)}"
        self._emit(
            f"规划 {step_index}",
            f"来源={source_label}{route_text}，选择动作：{self._format_action(action)}",
        )
        if decision.rationale:
            self._emit(f"思考 {step_index}", self._trim(decision.rationale))

    def execution_start(self, step_index: int, attempt: int, max_attempts: int, action: ActionStep) -> None:
        self._emit(
            f"执行 {step_index}",
            f"开始第 {attempt}/{max_attempts} 次尝试，动作={self._format_action(action)}",
        )

    def execution_result(
        self,
        step_index: int,
        attempt: int,
        success: bool,
        validation: ValidationResult,
        error_message: str | None,
    ) -> None:
        if error_message:
            self._emit(f"执行 {step_index}", f"第 {attempt} 次尝试执行异常：{self._trim(error_message)}")
        status_text = "通过" if success else "未通过"
        self._emit(
            f"校验 {step_index}",
            f"第 {attempt} 次尝试{status_text}，策略=`{validation.strategy}`，摘要={self._trim(validation.summary)}",
        )

    def retry(self, step_index: int, attempt: int, max_attempts: int, reason: str, will_retry: bool) -> None:
        if will_retry:
            self._emit(
                f"重试 {step_index}",
                f"第 {attempt}/{max_attempts} 次尝试失败，准备重试。原因：{self._trim(reason)}",
            )
        else:
            self._emit(
                f"重试 {step_index}",
                f"第 {attempt}/{max_attempts} 次尝试失败，已达到当前步骤上限。原因：{self._trim(reason)}",
            )

    def final_validation(self, validation: ValidationResult) -> None:
        status_text = "通过" if validation.passed else "失败"
        self._emit(
            "总验",
            f"任务级校验{status_text}，策略=`{validation.strategy}`，摘要={self._trim(validation.summary)}",
        )
        checks = validation.details.get("checks")
        if isinstance(checks, list):
            for index, check in enumerate(checks[:5], start=1):
                self._emit("总验", f"断言 {index}: {self._trim(str(check))}")

    def task_end(self, report: RunReport, report_paths: dict[str, Any]) -> None:
        status_text = "成功" if report.status == "success" else "失败"
        self._emit(
            "完成",
            f"用例 `{report.task_id}` 执行{status_text}，耗时 {report.duration_seconds:.2f}s，"
            f"步骤尝试={report.metrics.get('step_attempts', 0)}，重试={report.metrics.get('retries', 0)}",
        )
        if report.failure_reason:
            self._emit("完成", f"失败原因：{self._trim(report.failure_reason)}")
        self._emit(
            "报告",
            f"Markdown={report_paths.get('markdown')} | JSON={report_paths.get('json')}",
        )

    def suite_start(self, case_count: int, case_dir: str) -> None:
        self._emit("套件", f"开始执行测试套件，共 {case_count} 条用例，目录=`{case_dir}`")

    def suite_end(self, total: int, failed: int) -> None:
        passed = total - failed
        self._emit("套件", f"测试套件结束：成功 {passed} 条，失败 {failed} 条，总计 {total} 条")

    def doctor_summary(self, diagnostics: dict[str, Any]) -> None:
        self._emit("诊断", f"运行模式：{'Mock' if diagnostics['python_mode'] == 'mock' else 'Desktop'}")
        self._emit(
            "诊断",
            f"模型：{diagnostics['openai_model']} @ {diagnostics['openai_base_url']}",
        )
        self._emit(
            "诊断",
            f"OCR后端：{diagnostics['ocr_backend']}，语言={diagnostics['paddleocr_lang']}，"
            f"可导入={diagnostics['paddleocr_importable']}",
        )
        if diagnostics.get("paddleocr_error"):
            self._emit("诊断", f"PaddleOCR 问题：{self._trim(str(diagnostics['paddleocr_error']))}")

    def _describe_component(self, component: Any) -> str:
        backend_name = getattr(component, "backend_name", component.__class__.__name__)
        backend_name = self._backend_name(backend_name)
        status_message = getattr(component, "status_message", None)
        fallback_reason = getattr(component, "fallback_reason", None)
        pieces = [str(backend_name)]
        if isinstance(status_message, str) and status_message != "ready":
            pieces.append(self._trim(status_message))
        if isinstance(fallback_reason, str) and fallback_reason:
            pieces.append(self._trim(fallback_reason))
        return " | ".join(pieces)

    def _backend_name(self, backend_name: str) -> str:
        mapping = {
            "mock_policy": "Mock 规划策略",
            "openai_compatible": "OpenAI 兼容视觉策略",
            "mock_executor": "Mock 执行器",
            "windows_executor": "Windows 桌面执行器",
            "paddleocr": "PaddleOCR",
            "none": "无 OCR",
            "executor": "执行器",
            "unknown": "未知组件",
        }
        return mapping.get(backend_name, backend_name)

    def _route_name(self, route: str | None) -> str:
        mapping = {
            "responses": "Responses API",
            "responses_failed": "Responses API 失败",
            "chat.completions": "Chat Completions",
            "mock": "Mock 通道",
        }
        if route is None:
            return "未知"
        return mapping.get(route, route)

    def _observation_preview(self, observation: Observation) -> str:
        ocr_texts = [block.text for block in observation.ocr_blocks if block.text.strip()]
        if ocr_texts:
            preview_source = " / ".join(ocr_texts[:4])
            return self._trim(preview_source)
        visible_texts = observation.ui_hints.get("visible_texts")
        if isinstance(visible_texts, list) and visible_texts:
            return self._trim(" / ".join(str(item) for item in visible_texts[:4]))
        return "无明显文本"

    def _format_action(self, action: ActionStep) -> str:
        parts = [f"{action.action_type}"]
        if action.description:
            parts.append(self._trim(action.description))
        if action.hotkey:
            parts.append(f"快捷键={'+'.join(action.hotkey)}")
        if action.text:
            parts.append(f"文本={self._trim(action.text)}")
        if action.coordinates:
            parts.append(f"坐标={action.coordinates}")
        if action.validation_hint:
            parts.append(f"校验提示={self._trim(action.validation_hint)}")
        if action.wait_seconds and action.action_type == "wait":
            parts.append(f"等待={action.wait_seconds:.1f}s")
        if action.scroll_amount:
            parts.append(f"滚动={action.scroll_amount}")
        return " | ".join(parts)

    def _trim(self, text: str) -> str:
        cleaned = " ".join(str(text).split())
        if len(cleaned) <= self.preview_chars:
            return cleaned
        return cleaned[: self.preview_chars - 3] + "..."

    def _emit(self, stage: str, message: str) -> None:
        if not self.enabled:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [{stage}] {message}", flush=True)
