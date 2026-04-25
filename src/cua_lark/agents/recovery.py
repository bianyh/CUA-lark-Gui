from __future__ import annotations

from cua_lark.llm import VLMClient
from cua_lark.models import ActionProposal, Observation, StepPlan, VerificationResult


class RecoveryAgent:
    def __init__(self, vlm: VLMClient | None):
        self.vlm = vlm

    def recover(
        self,
        step: StepPlan,
        observation: Observation,
        verification: VerificationResult | None,
    ) -> ActionProposal:
        if self.vlm is None:
            return ActionProposal(
                action="wait",
                target="recover by waiting for UI stability",
                wait_seconds=0.5,
                confidence=1.0,
                reason="No VLM configured; wait before retry.",
                expected_state=step.success_criteria,
            )

        prompt = (
            "A Feishu/Lark GUI test step failed or had low confidence. "
            "Propose one safe recovery action only. Prefer wait, hotkey escape, "
            "scroll, screenshot, or clicking a visible close/search/navigation control. "
            "Return JSON matching the action proposal schema.\n\n"
            f"Step goal: {step.goal}\n"
            f"Success criteria: {step.success_criteria}\n"
            f"Page summary: {observation.page_summary}\n"
            f"Alerts: {observation.alerts}\n"
            f"Verification: {verification.model_dump() if verification else None}"
        )
        data = self.vlm.complete_json(prompt, images=[observation.screenshot_path])
        return ActionProposal(**data)
