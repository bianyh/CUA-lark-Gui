from __future__ import annotations

import unittest
from pathlib import Path
import shutil
import tempfile

from cua_lark.cases.loader import discover_case_files, load_task_spec
from cua_lark.config import Settings
from cua_lark.models import AssertionSpec, TaskSpec
from cua_lark.perception.ocr import paddleocr_diagnostics
from cua_lark.perception.screenshot import Screenshotter
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


class MockRunnerTest(unittest.TestCase):
    def test_mock_screenshotter_respects_region_size(self) -> None:
        with tempfile.TemporaryDirectory(dir="tests") as tmpdir:
            path = Path(tmpdir) / "region_mock.png"
            screenshotter = Screenshotter(mock_mode=True)
            _, size, capture_mode = screenshotter.capture(
                path,
                overlay_lines=["test"],
                region=(100, 200, 640, 480),
            )
            self.assertEqual(size, (640, 480))
            self.assertEqual(capture_mode, "mock")

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
        finally:
            if root.exists():
                shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
