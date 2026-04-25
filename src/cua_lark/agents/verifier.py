from __future__ import annotations

from cua_lark.llm import VLMClient
from cua_lark.models import Observation, StepPlan, VerificationResult


class VerifierAgent:
    def __init__(self, vlm: VLMClient | None):
        self.vlm = vlm

    def verify(self, step: StepPlan, observation: Observation) -> VerificationResult:
        if self.vlm is None:
            return VerificationResult(
                passed=True,
                confidence=1.0,
                evidence="No VLM configured; dry-run verification passes.",
            )

        prompt = (
            "Verify whether the Feishu/Lark GUI state satisfies the test step. "
            "Return JSON with keys: passed, confidence, evidence, failure_type, "
            "recommended_next_action.\n\n"
            f"Step goal: {step.goal}\n"
            f"Success criteria: {step.success_criteria}\n"
            f"Page summary: {observation.page_summary}\n"
            f"Alerts: {observation.alerts}"
        )
        data = self.vlm.complete_json(prompt, images=[observation.screenshot_path])
        return VerificationResult(**data)
