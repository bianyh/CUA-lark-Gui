from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path


# =========================
# PyCharm 调试运行配置
# =========================
# 直接在 PyCharm 中 Run/Debug 当前文件即可，不需要填写 Script parameters。
#
# 常用改法：
# - 调试安全闭环：保持 RUN_MODE = "mock"，不依赖飞书客户端、OCR 或大模型 API。
# - 调试真实飞书：改成 RUN_MODE = "desktop"，并确认 .env.local 里配置了 OPENAI_API_KEY。
# - 更换用例：修改 CASE_PATH，例如 "cases/calendar/create_event.yaml"。
RUN_MODE = "desktop"  # 可选："mock" 或 "desktop"
RUN_TARGET = "case"  # 可选："case"、"suite"、"doctor"、"list-cases"
CASE_PATH = "cases/im/send_message.yaml"
CASE_DIR = "cases"

MAX_STEPS = 15
MAX_RETRIES = 2
RUNTIME_LOGS = True
RUNTIME_PREVIEW_CHARS = 120


REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from cua_lark.cases.loader import discover_case_files, load_case_directory, load_task_spec
from cua_lark.config import Settings
from cua_lark.perception.ocr import paddleocr_diagnostics
from cua_lark.runner import build_default_runner


def build_debug_settings() -> Settings:
    """Build settings for no-argument PyCharm debugging."""
    settings = Settings.from_env(REPO_ROOT)
    return replace(
        settings,
        repo_root=REPO_ROOT,
        artifact_root=REPO_ROOT / "artifacts",
        report_root=REPO_ROOT / "reports" / "generated",
        mock_mode=RUN_MODE.lower() == "mock",
        max_steps=MAX_STEPS,
        max_retries=MAX_RETRIES,
        ocr_backend="none",
        runtime_logs=RUNTIME_LOGS,
        runtime_preview_chars=RUNTIME_PREVIEW_CHARS,
    )


def run_case(settings: Settings) -> int:
    case_path = REPO_ROOT / CASE_PATH
    task = load_task_spec(case_path)
    runner = build_default_runner(settings)
    report = runner.run_task(task)
    print(
        f"用例执行结束：task={report.task_id} status={report.status} "
        f"report={report.output_dir / 'report.md'}"
    )
    return 0 if report.status == "success" else 1


def run_suite(settings: Settings) -> int:
    case_dir = REPO_ROOT / CASE_DIR
    cases = load_case_directory(case_dir)
    if not cases:
        print(f"未在 {case_dir} 中发现测试用例")
        return 1

    runner = build_default_runner(settings)
    runner.runtime_console.suite_start(len(cases), str(case_dir))
    failed = 0
    for task in cases:
        report = runner.run_task(task)
        print(f"套件进度：task={report.task_id} status={report.status}")
        failed += 0 if report.status == "success" else 1
    runner.runtime_console.suite_end(len(cases), failed)
    return 0 if failed == 0 else 1


def list_cases() -> int:
    case_dir = REPO_ROOT / CASE_DIR
    print(f"已发现以下测试用例，目录：{case_dir}")
    for path in discover_case_files(case_dir):
        task = load_task_spec(path)
        print(f"- {task.id} | 产品={task.product} | 路径={path}")
    return 0


def doctor(settings: Settings) -> int:
    ocr_diagnostics = paddleocr_diagnostics()
    diagnostics = {
        "repo_root": str(settings.repo_root),
        "python_mode": "mock" if settings.mock_mode else "desktop",
        "openai_base_url": settings.openai_base_url,
        "openai_model": settings.openai_model,
        "openai_api_key_set": bool(settings.openai_api_key),
        "artifacts_dir": str(settings.artifact_root),
        "reports_dir": str(settings.report_root),
        "ocr_backend": settings.ocr_backend,
        "paddleocr_lang": settings.paddleocr_lang,
        "paddleocr_package_found": ocr_diagnostics["package_found"],
        "paddleocr_package_version": ocr_diagnostics["package_version"],
        "paddleocr_importable": ocr_diagnostics["importable"],
        "paddleocr_error": ocr_diagnostics["error"],
    }
    for key, value in diagnostics.items():
        print(f"{key}: {value}")
    return 0


def main() -> int:
    os.chdir(REPO_ROOT)
    settings = build_debug_settings()
    target = RUN_TARGET.lower()

    if target == "case":
        return run_case(settings)
    if target == "suite":
        return run_suite(settings)
    if target == "doctor":
        return doctor(settings)
    if target == "list-cases":
        return list_cases()

    print(f"不支持的 RUN_TARGET：{RUN_TARGET}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
