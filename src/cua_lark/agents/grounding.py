from __future__ import annotations

from cua_lark.llm import VLMClient
from cua_lark.models import ActionProposal, Observation, StepPlan


class GroundingAgent:
    def __init__(self, vlm: VLMClient | None):
        self.vlm = vlm

    def propose_action(self, step: StepPlan, observation: Observation) -> ActionProposal:
        if self.vlm is None:
            return ActionProposal(
                action="wait",
                target=step.goal,
                wait_seconds=0.1,
                confidence=1.0,
                reason="No VLM configured; dry-run wait action.",
                expected_state=step.success_criteria,
            )

        candidates = [candidate.model_dump() for candidate in observation.ui_candidates]
        prompt = (
            "You are grounding a Feishu/Lark GUI test step to exactly one next action. "
            "Use the screenshot as the source of truth. Return JSON with keys: action, "
            "target, coordinates, end_coordinates, text, hotkeys, scroll_amount, "
            "wait_seconds, confidence, reason, expected_state, risk. "
            "Coordinates must be screenshot pixel coordinates. If confidence is low, "
            "return wait or screenshot instead of guessing.\n\n"
            f"Step goal: {step.goal}\n"
            f"Success criteria: {step.success_criteria}\n"
            f"Allowed actions: {[item.value for item in step.allowed_actions]}\n"
            f"Page summary: {observation.page_summary}\n"
            f"Detected alerts: {observation.alerts}\n"
            f"UI candidates: {candidates}"
        )
        data = self.vlm.complete_json(prompt, images=[observation.screenshot_path])
        return ActionProposal(**data)
