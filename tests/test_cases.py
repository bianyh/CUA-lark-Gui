from __future__ import annotations

from datetime import UTC, datetime
import unittest
from pathlib import Path
import shutil
from cua_lark.cases.loader import discover_case_files, load_task_spec
from cua_lark.config import Settings
from cua_lark.models import AssertionSpec, Observation, TaskSpec, UIReadiness, ValidationResult
from cua_lark.perception.ocr import paddleocr_diagnostics
from cua_lark.perception.screenshot import Screenshotter
from cua_lark.perception.state import StateAnalyzer
from cua_lark.providers.mock import MockVisionPolicy
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


if __name__ == "__main__":
    unittest.main()
