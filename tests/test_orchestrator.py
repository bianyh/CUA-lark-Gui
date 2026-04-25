from pathlib import Path
from uuid import uuid4

from PIL import Image

from cua_lark.agents import GroundingAgent, TestPlannerAgent as PlannerBase, VerifierAgent
from cua_lark.config import Settings
from cua_lark.executor import ActionExecutor
from cua_lark.models import ActionProposal, StepPlan, TestCase as CuaTestCase, VerificationResult
from cua_lark.orchestrator import Orchestrator
from cua_lark.perception import PerceptionAgent, ScreenCapturer


class StaticPlanner(PlannerBase):
    def __init__(self):
        pass

    def plan(self, case):
        return [
            StepPlan(
                step_id="1",
                goal="wait for page",
                success_criteria="page is stable",
                allowed_actions=["wait"],
                max_retries=0,
            )
        ]


class StaticGrounding(GroundingAgent):
    def __init__(self):
        pass

    def propose_action(self, step, observation):
        return ActionProposal(action="wait", wait_seconds=0.01, confidence=1.0)


class StaticVerifier(VerifierAgent):
    def __init__(self):
        pass

    def verify(self, step, observation):
        return VerificationResult(passed=True, confidence=1.0, evidence="ok")


def test_orchestrator_dry_run_passes():
    tmp_path = Path("test_artifacts") / f"orchestrator_{uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (100, 80), "white").save(image_path)

    settings = Settings(openai_api_key=None, runs_dir=tmp_path / "runs")
    perception = PerceptionAgent(None, capturer=ScreenCapturer(dry_run_image=image_path))
    case = CuaTestCase(
        id="case",
        name="case",
        product="IM",
        instruction="do thing",
        expected_result="done",
    )
    orchestrator = Orchestrator(
        settings,
        vlm=None,
        perception=perception,
        executor=ActionExecutor(dry_run=True),
        planner=StaticPlanner(),
        grounding=StaticGrounding(),
        verifier=StaticVerifier(),
    )
    context = orchestrator.run(case)
    assert context.status == "passed"
    assert (Path(context.run_dir) / "report.md").exists()
