from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cua_lark.config import Settings
from cua_lark.executors.base import DesktopExecutor
from cua_lark.executors.mock import MockDesktopExecutor
from cua_lark.executors.windows import WindowsDesktopExecutor
from cua_lark.models import Observation, ReplanReason, RunReport, StepRecord, TaskSpec, ValidationResult
from cua_lark.perception.ocr import NullOCRProvider, OCRProvider, PaddleOCRProvider, paddleocr_diagnostics
from cua_lark.perception.screenshot import Screenshotter
from cua_lark.planning.hybrid import HybridPlanner
from cua_lark.providers.base import VisionPolicy
from cua_lark.providers.mock import MockVisionPolicy
from cua_lark.providers.openai_compatible import OpenAICompatibleVisionPolicy
from cua_lark.reporter import ReportWriter
from cua_lark.runtime import RuntimeConsole
from cua_lark.validators.engine import CompositeValidator


class AgentRunner:
    def __init__(
        self,
        settings: Settings,
        planner: HybridPlanner,
        executor: DesktopExecutor,
        screenshotter: Screenshotter,
        ocr_provider: OCRProvider,
        validator: CompositeValidator,
        reporter: ReportWriter,
        runtime_console: RuntimeConsole,
    ) -> None:
        self.settings = settings
        self.planner = planner
        self.executor = executor
        self.screenshotter = screenshotter
        self.ocr_provider = ocr_provider
        self.validator = validator
        self.reporter = reporter
        self.runtime_console = runtime_console

    def run_task(self, task: TaskSpec) -> RunReport:
        self.settings.ensure_runtime_dirs()
        self.executor.reset()
        started_at = datetime.now(UTC)
        run_id = started_at.strftime("%Y%m%d-%H%M%S")
        artifact_dir = self.settings.artifact_root / task.id / run_id
        timeline_dir = artifact_dir / "timeline"
        report_dir = self.settings.report_root / task.id / run_id
        timeline_dir.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)

        window_keyword = str(task.metadata.get("window_title_keyword", self.settings.window_title_keyword))
        focus_result = self.executor.focus_window(window_keyword)
        self.runtime_console.task_start(
            task=task,
            settings=self.settings,
            policy=self.planner.policy,
            executor=self.executor,
            ocr_provider=self.ocr_provider,
            focus_result=focus_result,
        )

        step_records: list[StepRecord] = []
        scripted_index = 0
        failure_reason: str | None = None
        last_observation: Observation | None = None

        for step_index in range(1, self.settings.max_steps + 1):
            before = self._observe(
                screenshot_path=timeline_dir / f"{step_index:02d}_before.png",
                window_title=window_keyword,
                overlay_prefix=f"Before step {step_index}",
            )
            last_observation = before
            self.runtime_console.observation(step_index=step_index, observation=before)
            planning = self.planner.next_action(
                task=task,
                observation=before,
                history=step_records,
                scripted_index=scripted_index,
                remaining_steps=self.settings.max_steps - step_index,
            )
            decision = planning.decision
            source_label = "脚本动作" if planning.scripted else "模型决策"
            self.runtime_console.planning(
                step_index=step_index,
                decision=decision,
                source_label=source_label,
                action=decision.action,
                policy=self.planner.policy,
            )
            if decision.done or decision.action is None:
                break

            if planning.scripted:
                scripted_index += 1

            step_succeeded = False
            max_attempts = self.settings.max_retries + 1
            for attempt in range(1, max_attempts + 1):
                self.runtime_console.execution_start(
                    step_index=step_index,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    action=decision.action,
                )
                step_started_at = datetime.now(UTC)
                execution_meta: dict[str, object] = {}
                error_message: str | None = None
                try:
                    execution_meta = self.executor.execute(decision.action)
                except Exception as exc:
                    error_message = str(exc)

                after = self._observe(
                    screenshot_path=timeline_dir / f"{step_index:02d}_attempt{attempt}_after.png",
                    window_title=window_keyword,
                    overlay_prefix=f"After step {step_index} attempt {attempt}",
                )
                last_observation = after

                if error_message:
                    validation = ValidationResult(
                        passed=False,
                        summary=f"Execution failed before validation: {error_message}",
                        strategy="execution_error",
                        confidence=0.0,
                    )
                    replan_reason = self._classify_failure(error_message, validation)
                    success = False
                else:
                    validation = self.validator.validate_hint(
                        decision.action.validation_hint,
                        observation=after,
                        history=step_records,
                    )
                    replan_reason = self._classify_failure(None, validation)
                    success = validation.passed
                self.runtime_console.execution_result(
                    step_index=step_index,
                    attempt=attempt,
                    success=success,
                    validation=validation,
                    error_message=error_message,
                )

                step_records.append(
                    StepRecord(
                        index=step_index,
                        attempt=attempt,
                        action=decision.action,
                        success=success,
                        rationale=decision.rationale,
                        started_at=step_started_at,
                        ended_at=datetime.now(UTC),
                        observation_before=before,
                        observation_after=after,
                        validation=validation,
                        error=error_message,
                        replan_reason=None if success else replan_reason,
                        executor_state=self.executor.snapshot_state(),
                        execution_meta=dict(execution_meta),
                    )
                )

                if success:
                    step_succeeded = True
                    break

                should_retry = attempt < max_attempts
                self.runtime_console.retry(
                    step_index=step_index,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    reason=error_message or validation.summary,
                    will_retry=should_retry,
                )

                if planning.scripted and attempt > self.settings.max_retries:
                    failure_reason = error_message or validation.summary
                    break

            if failure_reason:
                break

            if not step_succeeded and not planning.scripted:
                continue

        final_observation = last_observation or self._observe(
            screenshot_path=artifact_dir / "final.png",
            window_title=window_keyword,
            overlay_prefix="Final observation",
        )
        final_validation = self.validator.validate_task(task, final_observation, step_records)
        self.runtime_console.final_validation(final_validation)
        ended_at = datetime.now(UTC)
        duration_seconds = (ended_at - started_at).total_seconds()
        status = "success" if final_validation.passed and failure_reason is None else "failed"

        metrics = {
            "step_attempts": len(step_records),
            "step_success_rate": self._success_rate(step_records),
            "successful_steps": sum(1 for record in step_records if record.success),
            "failed_steps": sum(1 for record in step_records if not record.success),
            "retries": sum(max(0, record.attempt - 1) for record in step_records),
            "max_steps": self.settings.max_steps,
            "max_retries": self.settings.max_retries,
        }

        report = RunReport(
            task_id=task.id,
            product=task.product,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            output_dir=report_dir,
            artifact_dir=artifact_dir,
            step_records=step_records,
            metrics=metrics,
            final_validation=final_validation,
            failure_reason=failure_reason if failure_reason else None if final_validation.passed else final_validation.summary,
            assumptions={
                "mock_mode": self.settings.mock_mode,
                "window_title_keyword": window_keyword,
                "provider_mode": self.settings.provider_mode,
                "planner_backend": getattr(self.planner.policy, "backend_name", self.planner.policy.__class__.__name__),
                "executor_backend": getattr(self.executor, "backend_name", self.executor.__class__.__name__),
                "ocr_backend": getattr(self.ocr_provider, "backend_name", self.ocr_provider.__class__.__name__),
            },
        )
        report_paths = self.reporter.write(report)
        self.runtime_console.task_end(report, report_paths)
        return report

    def _observe(self, screenshot_path: Path, window_title: str, overlay_prefix: str) -> Observation:
        state = self.executor.snapshot_state()
        overlay_lines = [overlay_prefix, f"window={window_title}"]
        visible_texts = state.get("visible_texts", [])
        if isinstance(visible_texts, list):
            overlay_lines.extend(str(item) for item in visible_texts[:10])
        region = self.executor.capture_region()
        if region is not None:
            overlay_lines.append(f"capture_region={region}")
        image_path, screen_size, capture_mode = self.screenshotter.capture(
            screenshot_path,
            overlay_lines=overlay_lines,
            region=region,
        )
        ocr_blocks = self.ocr_provider.extract(image_path)
        state["capture_mode"] = capture_mode
        return Observation(
            screenshot_path=str(image_path),
            timestamp=datetime.now(UTC),
            window_title=window_title,
            screen_size=screen_size,
            ocr_blocks=ocr_blocks,
            notes=overlay_lines,
            ui_hints=state,
        )

    def _classify_failure(
        self,
        error_message: str | None,
        validation: ValidationResult,
    ) -> ReplanReason:
        if error_message:
            lowered = error_message.lower()
            if "timeout" in lowered:
                return ReplanReason.LOAD_TIMEOUT
            if "coordinate" in lowered or "target" in lowered:
                return ReplanReason.TARGET_MISSING
            if "input" in lowered:
                return ReplanReason.INPUT_FAILED
            return ReplanReason.UNKNOWN
        if not validation.passed:
            return ReplanReason.VALIDATION_FAILED
        return ReplanReason.UNKNOWN

    def _success_rate(self, step_records: list[StepRecord]) -> float:
        if not step_records:
            return 0.0
        successes = sum(1 for record in step_records if record.success)
        return round(successes / len(step_records), 4)


def build_default_runner(settings: Settings) -> AgentRunner:
    policy: VisionPolicy
    if settings.mock_mode:
        policy = MockVisionPolicy()
        executor: DesktopExecutor = MockDesktopExecutor()
        ocr_provider: OCRProvider = NullOCRProvider("当前为 Mock 模式，未启用 OCR。")
    else:
        try:
            policy = OpenAICompatibleVisionPolicy(settings)
        except Exception as exc:
            policy = MockVisionPolicy(fallback_reason=f"模型策略初始化失败，已切换到 Mock。原因：{exc}")
        try:
            executor = WindowsDesktopExecutor()
        except Exception as exc:
            executor = MockDesktopExecutor()
            executor.fallback_reason = f"桌面执行器初始化失败，已切换到 Mock。原因：{exc}"
        if settings.ocr_backend == "none":
            ocr_provider = NullOCRProvider("OCR backend disabled by configuration.")
        else:
            diagnostics = paddleocr_diagnostics()
            if diagnostics["importable"]:
                ocr_provider = PaddleOCRProvider(language=settings.paddleocr_lang)
            else:
                reason = diagnostics["error"] or diagnostics.get("stderr_tail") or "unknown import error"
                ocr_provider = NullOCRProvider(
                    f"PaddleOCR unavailable, falling back to no OCR: {reason}"
                )

    planner = HybridPlanner(policy=policy)
    screenshotter = Screenshotter(mock_mode=settings.mock_mode or isinstance(executor, MockDesktopExecutor))
    validator = CompositeValidator(vision_policy=policy)
    reporter = ReportWriter()
    runtime_console = RuntimeConsole(
        enabled=settings.runtime_logs,
        preview_chars=settings.runtime_preview_chars,
    )
    return AgentRunner(
        settings=settings,
        planner=planner,
        executor=executor,
        screenshotter=screenshotter,
        ocr_provider=ocr_provider,
        validator=validator,
        reporter=reporter,
        runtime_console=runtime_console,
    )
