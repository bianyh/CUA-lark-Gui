from __future__ import annotations

from datetime import UTC, datetime
import unittest
from pathlib import Path
import shutil
from cua_lark.cases.loader import discover_case_files, load_task_spec
from cua_lark.config import Settings
from cua_lark.models import (
    ActionStep,
    AssertionSpec,
    Observation,
    PolicyDecision,
    ProgressAssessment,
    ReflectionResult,
    StepRecord,
    TaskSpec,
    UIReadiness,
    ValidationResult,
)
from cua_lark.perception.ocr import paddleocr_diagnostics
from cua_lark.perception.screenshot import Screenshotter
from cua_lark.perception.state import StateAnalyzer
from cua_lark.planning.hybrid import HybridPlanner
from cua_lark.providers.mock import MockVisionPolicy
from cua_lark.providers.openai_compatible import OpenAICompatibleVisionPolicy
from cua_lark.runner import build_default_runner


class CaseLoaderTest(unittest.TestCase):
    def test_discover_and_load_case(self) -> None:
        files = discover_case_files(Path("cases"))
        self.assertGreaterEqual(len(files), 5)
        task = load_task_spec(Path("cases/im/send_message.yaml"))
        self.assertEqual(task.id, "im_send_message")
        self.assertEqual(task.product, "im")
        self.assertGreaterEqual(len(task.scripted_actions), 1)

    def test_paddleocr_diagnostics_returns_expected_shape(self) -> None:
        diagnostics = paddleocr_diagnostics()
        self.assertIn("package_found", diagnostics)
        self.assertIn("package_version", diagnostics)
        self.assertIn("importable", diagnostics)
        self.assertIn("error", diagnostics)

    def test_state_analyzer_detects_loading(self) -> None:
        analyzer = StateAnalyzer()
        task = TaskSpec(id="loading_case", product="im", instruction="等待加载完成")
        observation = Observation(
            screenshot_path="fake.png",
            timestamp=datetime.now(UTC),
            window_title="飞书",
            screen_size=(100, 100),
            notes=["当前页面正在加载中，请稍候"],
        )
        assessment = analyzer.assess(task, observation)
        self.assertEqual(assessment.readiness, UIReadiness.LOADING)
        self.assertIn("加载判断=加载中", assessment.summary)

    def test_mock_progress_and_reflection(self) -> None:
        policy = MockVisionPolicy()
        task = TaskSpec(
            id="progress_case",
            product="im",
            instruction="发送 Hello World 并确认成功",
            assertions=[AssertionSpec(type="ocr_contains", expected_text="Hello World", description="消息应出现")],
        )
        before = Observation(
            screenshot_path="before.png",
            timestamp=datetime.now(UTC),
            window_title="飞书",
            screen_size=(100, 100),
            notes=["搜索页面"],
        )
        after = Observation(
            screenshot_path="after.png",
            timestamp=datetime.now(UTC),
            window_title="飞书",
            screen_size=(100, 100),
            notes=["Hello World 已显示"],
        )
        progress = policy.assess_progress(
            task=task,
            observation=after,
            history=[],
            latest_action=None,
        )
        self.assertTrue(progress.success)
        self.assertGreaterEqual(progress.completion_score, 1.0)

        reflection = policy.reflect_after_step(
            task=task,
            before=before,
            after=after,
            action=load_task_spec(Path("cases/im/send_message.yaml")).scripted_actions[0],
            validation=ValidationResult(passed=False, summary="未命中步骤校验提示：搜索", strategy="hint_contains"),
            progress=progress,
            history=[],
        )
        self.assertIn(reflection.failure_stage, {"无", "交互阶段", "输入阶段", "动作阶段(hotkey)"})

    def test_openai_provider_coerces_confidence_text(self) -> None:
        provider = OpenAICompatibleVisionPolicy.__new__(OpenAICompatibleVisionPolicy)
        self.assertAlmostEqual(provider._coerce_confidence("较低"), 0.25)
        self.assertAlmostEqual(provider._coerce_confidence("82%"), 0.82)
        self.assertAlmostEqual(provider._coerce_confidence("0.67"), 0.67)
        self.assertTrue(provider._coerce_bool("成功"))
        self.assertFalse(provider._coerce_bool("false"))

    def test_action_step_accepts_model_action_aliases(self) -> None:
        click = ActionStep.from_dict({"type": "click", "x": 115, "y": 85})
        self.assertEqual(click.action_type, "click")
        self.assertEqual(click.coordinates, (115, 85))

        hotkey = ActionStep.from_dict({"type": "hotkey", "hotkey": "ctrl+k"})
        self.assertEqual(hotkey.action_type, "hotkey")
        self.assertEqual(hotkey.hotkey, ["ctrl", "k"])

        text = ActionStep.from_dict({"type": "input", "text": "测试群"})
        self.assertEqual(text.action_type, "type_text")
        self.assertEqual(text.text, "测试群")

    def test_hybrid_planner_uses_scripted_actions_as_hints_in_adaptive_mode(self) -> None:
        class RecordingPolicy(MockVisionPolicy):
            def __init__(self) -> None:
                super().__init__()
                self.received_hints: list[ActionStep] = []
                self.received_reflection: ReflectionResult | None = None

            def plan_next_action(
                self,
                task: TaskSpec,
                observation: Observation,
                history: list[StepRecord],
                remaining_steps: int,
                planning_hints: list[ActionStep] | None = None,
                latest_reflection: ReflectionResult | None = None,
            ) -> PolicyDecision:
                self.received_hints = list(planning_hints or [])
                self.received_reflection = latest_reflection
                return PolicyDecision(done=True, rationale="测试结束")

        policy = RecordingPolicy()
        planner = HybridPlanner(policy=policy, prefer_scripted=False)
        task = TaskSpec(
            id="adaptive_case",
            product="im",
            instruction="根据当前界面动态决定下一步",
            metadata={
                "scripted_actions": [
                    {
                        "action_type": "hotkey",
                        "description": "打开全局搜索",
                        "hotkey": ["ctrl", "k"],
                        "validation_hint": "搜索",
                    }
                ]
            },
        )
        observation = Observation(
            screenshot_path="adaptive.png",
            timestamp=datetime.now(UTC),
            window_title="飞书",
            screen_size=(100, 100),
            notes=["已经在聊天窗口"],
        )
        reflection = ReflectionResult(
            should_replan=True,
            root_cause="上一动作未命中目标",
            failure_stage="交互阶段",
            suggested_strategy="改用当前界面可见入口继续",
        )

        result = planner.next_action(
            task=task,
            observation=observation,
            history=[],
            scripted_index=0,
            remaining_steps=5,
            latest_reflection=reflection,
        )

        self.assertFalse(result.scripted)
        self.assertEqual(len(policy.received_hints), 1)
        self.assertEqual(policy.received_hints[0].description, "打开全局搜索")
        self.assertIs(policy.received_reflection, reflection)

    def test_hybrid_planner_can_keep_scripted_fallback_mode(self) -> None:
        planner = HybridPlanner(policy=MockVisionPolicy(), prefer_scripted=True)
        task = TaskSpec(
            id="scripted_case",
            product="im",
            instruction="使用脚本回退",
            metadata={
                "scripted_actions": [
                    {
                        "action_type": "wait",
                        "description": "等待界面稳定",
                        "wait_seconds": 1.0,
                    }
                ]
            },
        )
        observation = Observation(
            screenshot_path="scripted.png",
            timestamp=datetime.now(UTC),
            window_title="飞书",
            screen_size=(100, 100),
        )

        result = planner.next_action(
            task=task,
            observation=observation,
            history=[],
            scripted_index=0,
            remaining_steps=5,
        )

        self.assertTrue(result.scripted)
        self.assertEqual(result.decision.action.description, "等待界面稳定")


class MockRunnerTest(unittest.TestCase):
    def test_mock_screenshotter_respects_region_size(self) -> None:
        root = Path("tests") / ".tmp" / "screenshotter"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            path = root / "region_mock.png"
            screenshotter = Screenshotter(mock_mode=True)
            _, size, capture_mode = screenshotter.capture(
                path,
                overlay_lines=["test"],
                region=(100, 200, 640, 480),
            )
            self.assertEqual(size, (640, 480))
            self.assertEqual(capture_mode, "mock")
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_mock_runner_generates_artifacts(self) -> None:
        root = Path("tests") / ".tmp" / "mock_runner"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            settings = Settings(
                repo_root=root,
                artifact_root=root / "artifacts",
                report_root=root / "reports" / "generated",
                openai_api_key=None,
                mock_mode=True,
            )
            task = TaskSpec(
                id="mock_send_message",
                product="im",
                instruction="发送 Hello World 并确认成功。",
                assertions=[
                    AssertionSpec(type="ocr_contains", expected_text="Hello World", description="消息应出现")
                ],
                metadata={
                    "window_title_keyword": "飞书",
                    "scripted_actions": [
                        {
                            "action_type": "type_text",
                            "description": "输入消息",
                            "text": "Hello World",
                            "validation_hint": "Hello World",
                        },
                        {
                            "action_type": "hotkey",
                            "description": "发送消息",
                            "hotkey": ["enter"],
                            "validation_hint": "Hello World",
                        },
                    ]
                },
            )
            runner = build_default_runner(settings)
            report = runner.run_task(task)

            self.assertEqual(report.status, "success")
            self.assertTrue((report.output_dir / "run.json").exists())
            self.assertTrue((report.output_dir / "report.md").exists())
            self.assertTrue((report.artifact_dir / "timeline").exists())
            self.assertGreaterEqual(report.metrics["load_wait_rounds"], 0)
            self.assertIsNotNone(report.step_records[-1].state_assessment)
            self.assertIsNotNone(report.step_records[-1].progress_assessment)
            self.assertIsNotNone(report.final_progress)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_failed_step_generates_reflection(self) -> None:
        root = Path("tests") / ".tmp" / "mock_reflection"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            settings = Settings(
                repo_root=root,
                artifact_root=root / "artifacts",
                report_root=root / "reports" / "generated",
                openai_api_key=None,
                mock_mode=True,
                max_retries=1,
            )
            task = TaskSpec(
                id="mock_reflection_case",
                product="im",
                instruction="触发一个失败动作并观察反思。",
                metadata={
                    "window_title_keyword": "飞书",
                    "scripted_actions": [
                        {
                            "action_type": "hotkey",
                            "description": "执行一个不会满足校验提示的动作",
                            "hotkey": ["ctrl", "k"],
                            "validation_hint": "不会出现的提示词",
                        },
                    ]
                },
            )
            runner = build_default_runner(settings)
            def _raise_failure(_step):
                raise RuntimeError("模拟执行失败")

            runner.executor.execute = _raise_failure  # type: ignore[method-assign]
            report = runner.run_task(task)

            self.assertEqual(report.status, "failed")
            self.assertIsNotNone(report.step_records[0].reflection)
            self.assertTrue(report.step_records[0].reflection.should_replan)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_adaptive_runner_replans_failed_model_action_with_latest_observation(self) -> None:
        class AdaptiveFailurePolicy(MockVisionPolicy):
            def __init__(self) -> None:
                super().__init__()
                self.plan_calls = 0
                self.latest_reflection_seen: ReflectionResult | None = None
                self.second_observation_path = ""

            def plan_next_action(
                self,
                task: TaskSpec,
                observation: Observation,
                history: list[StepRecord],
                remaining_steps: int,
                planning_hints: list[ActionStep] | None = None,
                latest_reflection: ReflectionResult | None = None,
            ) -> PolicyDecision:
                self.plan_calls += 1
                if self.plan_calls == 1:
                    return PolicyDecision(
                        done=False,
                        rationale="先执行一个会失败的模型动作。",
                        action=ActionStep(
                            action_type="wait",
                            description="等待不存在的目标",
                            wait_seconds=0.1,
                            validation_hint="不会出现的提示词",
                        ),
                    )
                self.latest_reflection_seen = latest_reflection
                self.second_observation_path = observation.screenshot_path
                return PolicyDecision(done=True, rationale="重规划已接收最新状态。")

            def assess_progress(
                self,
                task: TaskSpec,
                observation: Observation,
                history: list[StepRecord],
                latest_action: ActionStep | None = None,
            ) -> ProgressAssessment:
                return ProgressAssessment(
                    success=False,
                    completion_score=0.0,
                    progress_label="尚未完成",
                    summary="测试策略要求重规划。",
                    confidence=0.8,
                )

            def reflect_after_step(
                self,
                task: TaskSpec,
                before: Observation,
                after: Observation,
                action: ActionStep,
                validation: ValidationResult,
                progress: ProgressAssessment,
                history: list[StepRecord],
            ) -> ReflectionResult:
                return ReflectionResult(
                    should_replan=True,
                    root_cause="模型动作未达到校验目标。",
                    failure_stage="校验阶段",
                    suggested_strategy="重新观察界面并选择新的下一步。",
                    suggested_action=ActionStep(
                        action_type="wait",
                        description="等待后重新规划",
                        wait_seconds=0.1,
                    ),
                    confidence=0.9,
                )

        root = Path("tests") / ".tmp" / "adaptive_replan"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            settings = Settings(
                repo_root=root,
                artifact_root=root / "artifacts",
                report_root=root / "reports" / "generated",
                openai_api_key=None,
                mock_mode=True,
                max_retries=2,
            )
            task = TaskSpec(
                id="adaptive_replan_case",
                product="im",
                instruction="失败后应根据最新界面重新规划。",
                metadata={"window_title_keyword": "飞书"},
            )
            policy = AdaptiveFailurePolicy()
            runner = build_default_runner(settings)
            runner.planner = HybridPlanner(policy=policy, prefer_scripted=False)

            def _raise_execution_failure(_step):
                raise RuntimeError("模拟模型动作失败")

            runner.executor.execute = _raise_execution_failure  # type: ignore[method-assign]

            report = runner.run_task(task)

            self.assertEqual(policy.plan_calls, 2)
            self.assertIsNotNone(policy.latest_reflection_seen)
            self.assertIn("recovery", policy.second_observation_path)
            self.assertEqual(len(report.step_records), 1)
            self.assertEqual(report.metrics["replans"], 1)
        finally:
            if root.exists():
                shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
