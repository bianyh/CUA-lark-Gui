from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from .agents import GroundingAgent, RecoveryAgent, ReportAgent, TestPlannerAgent, VerifierAgent
from .config import Settings
from .executor import ActionExecutor
from .llm import VLMClient
from .models import TaskContext, TestCase, TraceEvent, VerificationResult
from .perception import PerceptionAgent

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
    ):
        self.settings = settings
        self.vlm = VLMClient(settings) if vlm is _DEFAULT_VLM else vlm
        self.perception = perception or PerceptionAgent(self.vlm)
        self.executor = executor or ActionExecutor()
        self.planner = planner or TestPlannerAgent(self.vlm)
        self.grounding = grounding or GroundingAgent(self.vlm)
        self.verifier = verifier or VerifierAgent(self.vlm)
        self.recovery = recovery or RecoveryAgent(self.vlm)
        self.reporter = reporter or ReportAgent()

    def run(self, case: TestCase) -> TaskContext:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{case.id}"
        run_dir = self.settings.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        context = TaskContext(case=case, run_id=run_id, run_dir=str(run_dir), status="running")

        try:
            steps = self.planner.plan(case)
            for step_index, step in enumerate(steps):
                context.current_step_index = step_index
                completed = False
                max_retries = min(step.max_retries, self.settings.max_recovery_attempts)
                for retry_index in range(max_retries + 1):
                    started = time.monotonic()
                    observation = self.perception.observe(run_dir, label=f"{step.step_id}_before")
                    action = self.grounding.propose_action(step, observation)

                    if action.confidence < self.settings.min_action_confidence:
                        recovery_action = self.recovery.recover(step, observation, None)
                        execution = self.executor.execute(
                            recovery_action, observation, run_dir=run_dir
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
                        execution = self.executor.execute(action, observation, run_dir=run_dir)
                        verification = VerificationResult(
                            passed=False,
                            confidence=0.0,
                            evidence="High-risk action requires human confirmation.",
                            failure_type="requires_confirmation",
                        )
                        context.status = "blocked"
                    else:
                        execution = self.executor.execute(action, observation, run_dir=run_dir)
                        after_observation = self.perception.observe(
                            run_dir, label=f"{step.step_id}_after"
                        )
                        verification = self.verifier.verify(step, after_observation)
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
                        return context

                    if execution.executed and verification.passed:
                        completed = True
                        break

                    if retry_index < max_retries:
                        recovery_action = self.recovery.recover(step, observation, verification)
                        self.executor.execute(recovery_action, observation, run_dir=run_dir)

                if not completed:
                    context.status = "failed"
                    context.failure_reason = (
                        f"Step {step.step_id} did not satisfy: {step.success_criteria}"
                    )
                    self.reporter.write(context)
                    return context

            context.status = "passed"
            self.reporter.write(context)
            return context
        except Exception as exc:
            context.status = "failed"
            context.failure_reason = str(exc)
            self.reporter.write(context)
            return context
