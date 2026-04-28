from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .agents import GroundingAgent, RecoveryAgent, ReportAgent, TestPlannerAgent, VerifierAgent
from .config import Settings
from .executor import ActionExecutor
from .llm import VLMClient
from .models import ExecutionResult, TaskContext, TestCase, TraceEvent, VerificationResult
from .perception import PerceptionAgent, ScreenCapturer
from .windowing import FeishuWindowManager

_DEFAULT_VLM = object()


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        *,
        vlm: VLMClient | None | object = _DEFAULT_VLM,
        perception: PerceptionAgent | None = None,
        executor: ActionExecutor | None = None,
        planner: TestPlannerAgent | None = None,
        grounding: GroundingAgent | None = None,
        verifier: VerifierAgent | None = None,
        recovery: RecoveryAgent | None = None,
        reporter: ReportAgent | None = None,
        logger: Callable[[str], None] | None = None,
    ):
        self.settings = settings
        self.vlm = VLMClient(settings) if vlm is _DEFAULT_VLM else vlm
        self.perception = perception or PerceptionAgent(
            self.vlm,
            capturer=ScreenCapturer(
                window_manager=FeishuWindowManager(
                    title_pattern=settings.window_title_pattern
                )
            ),
        )
        self.executor = executor or ActionExecutor()
        self.planner = planner or TestPlannerAgent(self.vlm)
        self.grounding = grounding or GroundingAgent(self.vlm)
        self.verifier = verifier or VerifierAgent(self.vlm)
        self.recovery = recovery or RecoveryAgent(self.vlm)
        self.reporter = reporter or ReportAgent()
        self.logger = logger

    def _log(self, message: str) -> None:
        if self.logger is not None:
            self.logger(message)

    def run(self, case: TestCase) -> TaskContext:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{case.id}"
        run_dir = self.settings.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        context = TaskContext(case=case, run_id=run_id, run_dir=str(run_dir), status="running")
        self._log(f"[run] start case={case.id} product={case.product} run_dir={run_dir}")

        try:
            steps = self.planner.plan(case)
            self._log(f"[planner] generated {len(steps)} step(s)")
            for step_index, step in enumerate(steps):
                context.current_step_index = step_index
                completed = False
                max_retries = min(step.max_retries, self.settings.max_recovery_attempts)
                self._log(
                    f"[step {step.step_id}] goal={step.goal} retries={max_retries}"
                )
                for retry_index in range(max_retries + 1):
                    self._log(f"[step {step.step_id}] attempt {retry_index + 1}/{max_retries + 1}")
                    started = time.monotonic()
                    observation = self.perception.observe(run_dir, label=f"{step.step_id}_before")
                    self._log(
                        "[observe] "
                        f"window={observation.window_title or 'unknown'} "
                        f"screenshot={observation.screenshot_path}"
                    )
                    action = self.grounding.propose_action(step, observation)
                    self._log(
                        "[grounding] "
                        f"action={action.action.value} target={action.target or '-'} "
                        f"confidence={action.confidence:.2f}"
                    )

                    if action.confidence < self.settings.min_action_confidence:
                        self._log(
                            "[recovery] action confidence below threshold; requesting recovery"
                        )
                        recovery_action = self.recovery.recover(step, observation, None)
                        execution = self.executor.execute(
                            recovery_action, observation, run_dir=run_dir
                        )
                        self._log(
                            f"[execute] recovery={recovery_action.action.value} "
                            f"ok={execution.executed} message={execution.message}"
                        )
                        verification = VerificationResult(
                            passed=False,
                            confidence=action.confidence,
                            evidence="Action confidence below threshold; recovery attempted.",
                            failure_type="low_confidence",
                            recommended_next_action=recovery_action.reason,
                        )
                        action = recovery_action
                    elif (
                        action.risk == "high"
                        and self.settings.require_confirmation_for_risky
                    ):
                        self._log("[safety] blocked high-risk action before execution")
                        execution = ExecutionResult(
                            executed=False,
                            message="blocked: high-risk action requires human confirmation",
                        )
                        verification = VerificationResult(
                            passed=False,
                            confidence=0.0,
                            evidence="High-risk action requires human confirmation.",
                            failure_type="requires_confirmation",
                        )
                        context.status = "blocked"
                    else:
                        execution = self.executor.execute(action, observation, run_dir=run_dir)
                        self._log(
                            f"[execute] action={action.action.value} "
                            f"ok={execution.executed} message={execution.message}"
                        )
                        after_observation = self.perception.observe(
                            run_dir, label=f"{step.step_id}_after"
                        )
                        self._log(
                            f"[observe] after screenshot={after_observation.screenshot_path}"
                        )
                        verification = self.verifier.verify(step, after_observation)
                        self._log(
                            "[verify] "
                            f"passed={verification.passed} "
                            f"confidence={verification.confidence:.2f} "
                            f"evidence={verification.evidence}"
                        )
                        observation = after_observation

                    trace = TraceEvent(
                        case_id=case.id,
                        step_id=step.step_id,
                        observation=observation,
                        action=action,
                        execution=execution,
                        verification=verification,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        retry_index=retry_index,
                    )
                    context.add_trace(trace)

                    if context.status == "blocked":
                        context.failure_reason = verification.evidence
                        self.reporter.write(context)
                        self._log(f"[run] blocked: {context.failure_reason}")
                        return context

                    if execution.executed and verification.passed:
                        completed = True
                        self._log(f"[step {step.step_id}] passed")
                        break

                    if retry_index < max_retries:
                        self._log(f"[recovery] preparing retry for step {step.step_id}")
                        recovery_action = self.recovery.recover(step, observation, verification)
                        recovery_execution = self.executor.execute(
                            recovery_action, observation, run_dir=run_dir
                        )
                        self._log(
                            f"[recovery] action={recovery_action.action.value} "
                            f"ok={recovery_execution.executed}"
                        )

                if not completed:
                    context.status = "failed"
                    context.failure_reason = (
                        f"Step {step.step_id} did not satisfy: {step.success_criteria}"
                    )
                    self.reporter.write(context)
                    self._log(f"[run] failed: {context.failure_reason}")
                    return context

            context.status = "passed"
            self.reporter.write(context)
            self._log(f"[run] passed report_dir={context.run_dir}")
            return context
        except Exception as exc:
            context.status = "failed"
            context.failure_reason = str(exc)
            self.reporter.write(context)
            self._log(f"[run] failed with exception: {context.failure_reason}")
            return context
