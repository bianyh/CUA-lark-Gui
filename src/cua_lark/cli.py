from __future__ import annotations

import argparse
import json
from pathlib import Path

from cua_lark.cases.loader import discover_case_files, load_case_directory, load_task_spec
from cua_lark.config import Settings
from cua_lark.perception.ocr import paddleocr_diagnostics
from cua_lark.runtime import RuntimeConsole
from cua_lark.runner import build_default_runner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CUA-Lark-Gui command line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Inspect local runtime readiness")
    doctor.add_argument("--json", action="store_true", dest="as_json")

    list_cases = subparsers.add_parser("list-cases", help="List bundled test cases")
    list_cases.add_argument("--case-dir", default="cases")

    run_case = subparsers.add_parser("run-case", help="Run a single case")
    run_case.add_argument("--case", required=True)
    run_case.add_argument("--mock", action="store_true")

    run_suite = subparsers.add_parser("run-suite", help="Run all cases in a directory")
    run_suite.add_argument("--case-dir", default="cases")
    run_suite.add_argument("--mock", action="store_true")

    web = subparsers.add_parser("web", help="Start the Flask web control console")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=5000)
    web.add_argument("--debug", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env(Path.cwd())

    if args.command == "doctor":
        return _doctor(settings, as_json=args.as_json)
    if args.command == "list-cases":
        return _list_cases(Path(args.case_dir))
    if args.command == "run-case":
        return _run_case(settings.with_mock_mode(args.mock or settings.mock_mode), Path(args.case))
    if args.command == "run-suite":
        return _run_suite(settings.with_mock_mode(args.mock or settings.mock_mode), Path(args.case_dir))
    if args.command == "web":
        return _web(settings, host=args.host, port=args.port, debug=args.debug)
    return 1


def _doctor(settings: Settings, as_json: bool) -> int:
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
    if as_json:
        print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
    else:
        runtime_console = RuntimeConsole(enabled=True, preview_chars=settings.runtime_preview_chars)
        runtime_console.doctor_summary(diagnostics)
        print("")
        for key, value in diagnostics.items():
            print(f"{key}: {value}")
    return 0


def _list_cases(case_dir: Path) -> int:
    print(f"已发现以下测试用例，目录：{case_dir}")
    for path in discover_case_files(case_dir):
        task = load_task_spec(path)
        print(f"- {task.id} | 产品={task.product} | 路径={path}")
    return 0


def _run_case(settings: Settings, case_path: Path) -> int:
    task = load_task_spec(case_path)
    runner = build_default_runner(settings)
    report = runner.run_task(task)
    print(
        f"用例执行结束：task={report.task_id} status={report.status} "
        f"report={report.output_dir / 'report.md'}"
    )
    return 0 if report.status == "success" else 1


def _run_suite(settings: Settings, case_dir: Path) -> int:
    runner = build_default_runner(settings)
    cases = load_case_directory(case_dir)
    if not cases:
        print(f"未在 {case_dir} 中发现测试用例")
        return 1
    runner.runtime_console.suite_start(len(cases), str(case_dir))
    failed = 0
    for task in cases:
        report = runner.run_task(task)
        print(f"套件进度：task={report.task_id} status={report.status}")
        failed += 0 if report.status == "success" else 1
    runner.runtime_console.suite_end(len(cases), failed)
    return 0 if failed == 0 else 1


def _web(settings: Settings, host: str, port: int, debug: bool) -> int:
    from cua_lark.web.app import create_app

    app = create_app(settings)
    app.run(host=host, port=port, debug=debug, threaded=True)
    return 0
