from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import time

from cua_lark.config import Settings
from cua_lark.executors.base import DesktopExecutor
from cua_lark.executors.mock import MockDesktopExecutor
from cua_lark.executors.windows import WindowsDesktopExecutor
from cua_lark.models import (
    Observation,
    ReflectionResult,
    ReplanReason,
    RunReport,
    StepRecord,
    TaskSpec,
    UIReadiness,
    ValidationResult,
)
from cua_lark.perception.ocr import NullOCRProvider, OCRProvider, PaddleOCRProvider, paddleocr_diagnostics
from cua_lark.perception.screenshot import Screenshotter
from cua_lark.perception.state import StateAnalyzer
from cua_lark.planning.hybrid import HybridPlanner
from cua_lark.providers.base import VisionPolicy
from cua_lark.providers.mock import MockVisionPolicy
from cua_lark.providers.openai_compatible import OpenAICompatibleVisionPolicy
from cua_lark.reporter import ReportWriter
from cua_lark.runtime import RuntimeConsole
from cua_lark.utils.images import compare_images
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
        state_analyzer: StateAnalyzer,
    ) -> None:
        self.settings = settings
        self.planner = planner
        self.executor = executor
        self.screenshotter = screenshotter
        self.ocr_provider = ocr_provider
        self.validator = validator
        self.reporter = reporter
        self.runtime_console = runtime_console
        self.state_analyzer = state_analyzer

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
        current_observation = self._observe(
            screenshot_path=timeline_dir / "00_initial.png",
            window_title=window_keyword,
            overlay_prefix="Initial observation",
        )
        current_observation, _ = self._assess_and_wait_until_ready(
            task=task,
            observation=current_observation,
            action=None,
            history=step_records,
            timeline_dir=timeline_dir,
            step_index=0,
            attempt=0,
            window_title=window_keyword,
        )
        last_observation: Observation | None = current_observation
        latest_reflection: ReflectionResult | None = None

        for step_index in range(1, self.settings.max_steps + 1):
            before = current_observation
            last_observation = before
            self.runtime_console.observation(step_index=step_index, observation=before)
            planning = self.planner.next_action(
                task=task,
                observation=before,
                history=step_records,
                scripted_index=scripted_index,
                remaining_steps=self.settings.max_steps - step_index,
                latest_reflection=latest_reflection,
            )
            decision = planning.decision
            source_label = "脚本动作" if planning.scripted else "模型动态规划"
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
            attempt_before = before
            last_failed_reflection: ReflectionResult | None = None
            for attempt in range(1, max_attempts + 1):
                attempt_observation_before = attempt_before
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

                raw_after = self._observe(
                    screenshot_path=timeline_dir / f"{step_index:02d}_attempt{attempt}_after.png",
                    window_title=window_keyword,
                    overlay_prefix=f"After step {step_index} attempt {attempt}",
                )
                after, state_meta = self._assess_and_wait_until_ready(
                    task=task,
                    observation=raw_after,
                    action=decision.action,
                    history=step_records,
                    timeline_dir=timeline_dir,
                    step_index=step_index,
                    attempt=attempt,
                    window_title=window_keyword,
                )
                last_observation = after

                if error_message:
                    validation = ValidationResult(
                        passed=False,
                        summary=f"动作执行异常，未进入正常校验：{error_message}",
                        strategy="execution_error",
                        confidence=0.0,
                    )
                    replan_reason = self._classify_failure(error_message, validation)
                    success = False
                elif after.state_assessment is not None and after.state_assessment.readiness == UIReadiness.TIMEOUT:
                    validation = ValidationResult(
                        passed=False,
                        summary=f"界面等待加载超时：{after.state_assessment.summary}",
                        strategy="load_wait",
                        confidence=0.0,
                    )
                    replan_reason = ReplanReason.LOAD_TIMEOUT
                    success = False
                else:
                    validation = self.validator.validate_hint(
                        decision.action.validation_hint,
                        observation=after,
                        history=step_records,
                    )
                    replan_reason = self._classify_failure(None, validation)
                    success = validation.passed

                progress_assessment = self.planner.policy.assess_progress(
                    task=task,
                    observation=after,
                    history=step_records,
                    latest_action=decision.action,
                )
                self.runtime_console.progress(step_index, progress_assessment)

                stalled = self._is_stalled_action(
                    decision.action,
                    progress_assessment.completion_score,
                    step_records,
                )
                if success and stalled:
                    validation = ValidationResult(
                        passed=False,
                        summary="动作执行后任务进度未提升，判定为停滞并触发重新规划。",
                        strategy="progress_stall",
                        confidence=progress_assessment.confidence,
                    )
                    replan_reason = ReplanReason.VALIDATION_FAILED
                    success = False

                reflection: ReflectionResult | None = None
                if not success:
                    reflection = self.planner.policy.reflect_after_step(
                        task=task,
                        before=attempt_before,
                        after=after,
                        action=decision.action,
                        validation=validation,
                        progress=progress_assessment,
                        history=step_records,
                    )
                    last_failed_reflection = reflection
                    self.runtime_console.reflection(step_index, reflection)
                self.runtime_console.execution_result(
                    step_index=step_index,
                    attempt=attempt,
                    success=success,
                    validation=validation,
                    error_message=error_message,
                )

                if success:
                    step_records.append(
                        StepRecord(
                            index=step_index,
                            attempt=attempt,
                            action=decision.action,
                            success=success,
                            rationale=decision.rationale,
                            started_at=step_started_at,
                            ended_at=datetime.now(UTC),
                            observation_before=attempt_observation_before,
                            observation_after=after,
                            validation=validation,
                            state_assessment=after.state_assessment,
                            progress_assessment=progress_assessment,
                            reflection=reflection,
                            error=error_message,
                            replan_reason=None if success else replan_reason,
                            executor_state=self.executor.snapshot_state(),
                            execution_meta={**dict(execution_meta), **state_meta},
                        )
                    )
                    step_succeeded = True
                    current_observation = after
                    latest_reflection = None
                    break

                attempt_before = after
                should_replan = bool(reflection and reflection.should_replan and not planning.scripted)
                should_retry = attempt < max_attempts and not should_replan

                if should_replan and reflection is not None:
                    self.runtime_console.replan(step_index, reflection)
                else:
                    self.runtime_console.retry(
                        step_index=step_index,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        reason=error_message or validation.summary,
                        will_retry=should_retry,
                    )

                if (
                    reflection
                    and reflection.should_replan
                    and reflection.suggested_action is not None
                    and (should_retry or should_replan)
                ):
                    recovery_observation, recovery_meta = self._apply_recovery_action(
                        step_index=step_index,
                        attempt=attempt,
                        action=reflection.suggested_action,
                        task=task,
                        history=step_records,
                        timeline_dir=timeline_dir,
                        window_title=window_keyword,
                    )
                    attempt_before = recovery_observation
                    last_observation = recovery_observation
                    execution_meta.update(recovery_meta)

                step_records.append(
                    StepRecord(
                        index=step_index,
                        attempt=attempt,
                        action=decision.action,
                        success=success,
                        rationale=decision.rationale,
                        started_at=step_started_at,
                        ended_at=datetime.now(UTC),
                        observation_before=attempt_observation_before,
                        observation_after=after,
                        validation=validation,
                        state_assessment=after.state_assessment,
                        progress_assessment=progress_assessment,
                        reflection=reflection,
                        error=error_message,
                        replan_reason=None if success else replan_reason,
                        executor_state=self.executor.snapshot_state(),
                        execution_meta={**dict(execution_meta), **state_meta},
                    )
                )

                if should_replan:
                    current_observation = attempt_before
                    latest_reflection = reflection
                    break

                if planning.scripted and attempt > self.settings.max_retries:
                    failure_reason = error_message or validation.summary
                    break

            if failure_reason:
                break

            if not step_succeeded:
                current_observation = last_observation or current_observation
                if latest_reflection is None and last_failed_reflection is not None:
                    latest_reflection = last_failed_reflection

            if not step_succeeded and not planning.scripted:
                continue

        final_observation = last_observation or self._observe(
            screenshot_path=artifact_dir / "final.png",
            window_title=window_keyword,
            overlay_prefix="Final observation",
        )
        final_validation = self.validator.validate_task(task, final_observation, step_records)
        final_progress = self.planner.policy.assess_progress(
            task=task,
            observation=final_observation,
            history=step_records,
            latest_action=step_records[-1].action if step_records else None,
        )
        self.runtime_console.final_progress(final_progress)
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
            "load_wait_rounds": sum(
                int(record.execution_meta.get("load_wait_rounds", 0)) for record in step_records
            ),
            "load_timeouts": sum(
                1 for record in step_records if bool(record.execution_meta.get("load_timed_out", False))
            ),
            "replans": sum(
                1 for record in step_records if record.reflection is not None and record.reflection.should_replan
            ),
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
            final_progress=final_progress,
            failure_reason=failure_reason if failure_reason else None if final_validation.passed else final_validation.summary,
            assumptions={
                "mock_mode": self.settings.mock_mode,
                "window_title_keyword": window_keyword,
                "provider_mode": self.settings.provider_mode,
                "planner_mode": "scripted_fallback" if self.planner.prefer_scripted else "adaptive",
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
        try:
            ocr_blocks = self.ocr_provider.extract(image_path)
        except Exception as exc:
            state["ocr_error"] = str(exc)
            ocr_blocks = []
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

    def _assess_and_wait_until_ready(
        self,
        task: TaskSpec,
        observation: Observation,
        action,
        history: list[StepRecord],
        timeline_dir: Path,
        step_index: int,
        attempt: int,
        window_title: str,
    ) -> tuple[Observation, dict[str, object]]:
        assessment = self.state_analyzer.assess(task, observation, action=action, history=history)
        observation.state_assessment = assessment
        self.runtime_console.state_summary(step_index, assessment.summary)
        wait_rounds = 0
        similarity: float | None = None
        stable_ready_rounds = 0 if self.state_analyzer.requires_additional_wait(observation, action, assessment) else 1

        if not self.settings.load_wait_enabled:
            return observation, {"load_wait_rounds": wait_rounds, "load_timed_out": False}

        latest_observation = observation
        latest_assessment = assessment
        last_observation = observation

        while wait_rounds < self.settings.load_max_wait_rounds:
            if latest_assessment.readiness != UIReadiness.LOADING and stable_ready_rounds >= 1:
                break

            wait_rounds += 1
            self.runtime_console.loading_wait(step_index, wait_rounds, latest_assessment.summary)
            time.sleep(self.settings.load_poll_interval_ms / 1000.0)

            polled_observation = self._observe(
                screenshot_path=timeline_dir / f"{step_index:02d}_attempt{attempt}_settle{wait_rounds}.png",
                window_title=window_title,
                overlay_prefix=f"Settle step {step_index} attempt {attempt} round {wait_rounds}",
            )
            similarity = compare_images(
                Path(last_observation.screenshot_path),
                Path(polled_observation.screenshot_path),
            )["similarity"]
            latest_assessment = self.state_analyzer.assess(
                task,
                polled_observation,
                action=action,
                history=history,
                stable_rounds=wait_rounds,
                screenshot_similarity=similarity,
            )
            polled_observation.state_assessment = latest_assessment
            self.runtime_console.state_probe(step_index, wait_rounds, latest_assessment.summary)
            latest_observation = polled_observation
            last_observation = polled_observation

            if self.state_analyzer.is_stable(latest_assessment, similarity):
                stable_ready_rounds += 1
            else:
                stable_ready_rounds = 0

        if latest_assessment.readiness == UIReadiness.LOADING and wait_rounds >= self.settings.load_max_wait_rounds:
            latest_assessment = self.state_analyzer.assess(
                task,
                latest_observation,
                action=action,
                history=history,
                stable_rounds=wait_rounds,
                screenshot_similarity=similarity,
                timed_out=True,
            )
            latest_observation.state_assessment = latest_assessment

        return latest_observation, {
            "load_wait_rounds": wait_rounds,
            "load_timed_out": latest_assessment.readiness == UIReadiness.TIMEOUT,
            "state_summary": latest_assessment.summary,
        }

    def _apply_recovery_action(
        self,
        step_index: int,
        attempt: int,
        action,
        task: TaskSpec,
        history: list[StepRecord],
        timeline_dir: Path,
        window_title: str,
    ) -> tuple[Observation, dict[str, object]]:
        self.runtime_console.recovery_action(step_index, action)
        recovery_meta: dict[str, object] = {
            "recovery_action_type": action.action_type,
            "recovery_action_description": action.description,
        }
        try:
            if action.action_type in {"wait", "noop"} or (
                action.action_type == "hotkey" and action.hotkey
            ):
                recovery_meta.update(self.executor.execute(action))
        except Exception as exc:
            recovery_meta["recovery_error"] = str(exc)

        raw_observation = self._observe(
            screenshot_path=timeline_dir / f"{step_index:02d}_attempt{attempt}_recovery.png",
            window_title=window_title,
            overlay_prefix=f"Recovery step {step_index} attempt {attempt}",
        )
        recovery_observation, state_meta = self._assess_and_wait_until_ready(
            task=task,
            observation=raw_observation,
            action=action,
            history=history,
            timeline_dir=timeline_dir,
            step_index=step_index,
            attempt=attempt,
            window_title=window_title,
        )
        recovery_meta.update(state_meta)
        return recovery_observation, recovery_meta

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

    def _is_stalled_action(
        self,
        action,
        completion_score: float,
        history: list[StepRecord],
    ) -> bool:
        if action.validation_hint:
            return False
        if action.action_type not in {"click", "double_click", "wait"}:
            return False
        if len(history) < 2:
            return False
        previous_scores = [
            record.progress_assessment.completion_score
            for record in history[-3:]
            if record.progress_assessment is not None
        ]
        if not previous_scores:
            return False
        if completion_score > max(previous_scores) + 0.05:
            return False
        if action.action_type == "wait":
            return True
        if action.coordinates is None:
            return False
        recent_clicks = [
            record.action.coordinates
            for record in history[-3:]
            if record.action.action_type in {"click", "double_click"} and record.action.coordinates is not None
        ]
        return len(recent_clicks) >= 2

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

    planner = HybridPlanner(policy=policy, prefer_scripted=isinstance(policy, MockVisionPolicy))
    screenshotter = Screenshotter(mock_mode=settings.mock_mode or isinstance(executor, MockDesktopExecutor))
    validator = CompositeValidator(vision_policy=policy)
    reporter = ReportWriter()
    runtime_console = RuntimeConsole(
        enabled=settings.runtime_logs,
        preview_chars=settings.runtime_preview_chars,
    )
    state_analyzer = StateAnalyzer(similarity_threshold=settings.load_similarity_threshold)
    return AgentRunner(
        settings=settings,
        planner=planner,
        executor=executor,
        screenshotter=screenshotter,
        ocr_provider=ocr_provider,
        validator=validator,
        reporter=reporter,
        runtime_console=runtime_console,
        state_analyzer=state_analyzer,
    )
