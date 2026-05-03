from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import threading
import uuid
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory, url_for
from werkzeug.exceptions import HTTPException

from cua_lark.cases.loader import discover_case_files, load_task_spec
from cua_lark.config import Settings
from cua_lark.models import RunReport, TaskSpec
from cua_lark.perception.ocr import paddleocr_diagnostics
from cua_lark.runner import build_default_runner
from cua_lark.runtime import RuntimeConsole
from cua_lark.utils.json import to_jsonable


TERMINAL_STATUSES = {"success", "failed", "error", "cancelled"}


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class WebRuntimeConsole(RuntimeConsole):
    def __init__(self, job: "RunJob", preview_chars: int = 120) -> None:
        super().__init__(enabled=True, preview_chars=preview_chars)
        self.job = job

    def _emit(self, stage: str, message: str) -> None:
        if not self.enabled:
            return
        self.job.append_log(stage, message)


class RunJob:
    def __init__(self, job_id: str, task: TaskSpec, case_path: Path, mode: str) -> None:
        self.id = job_id
        self.task_id = task.id
        self.product = task.product
        self.instruction = task.instruction
        self.case_path = str(case_path)
        self.mode = mode
        self.status = "queued"
        self.created_at = datetime.now(UTC)
        self.started_at: datetime | None = None
        self.ended_at: datetime | None = None
        self.error: str | None = None
        self.cancel_requested = False
        self.logs: list[dict[str, str]] = []
        self.metrics: dict[str, Any] = {}
        self.report_json: dict[str, Any] | None = None
        self.report_dir: str | None = None
        self.artifact_dir: str | None = None
        self.thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def append_log(self, stage: str, message: str) -> None:
        with self._lock:
            self.logs.append(
                {
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "stage": str(stage),
                    "message": str(message),
                }
            )
            if len(self.logs) > 600:
                self.logs = self.logs[-600:]

    def mark_running(self) -> None:
        with self._lock:
            self.status = "running"
            self.started_at = datetime.now(UTC)

    def request_cancel(self) -> None:
        with self._lock:
            self.cancel_requested = True
            if self.status in {"queued", "running"}:
                self.status = "cancel_requested"
            self.logs.append(
                {
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "stage": "控制",
                    "message": "已请求停止，运行器会在下一次安全检查点退出。",
                }
            )

    def is_cancel_requested(self) -> bool:
        with self._lock:
            return self.cancel_requested

    def complete(self, report: RunReport) -> None:
        report_json = to_jsonable(report)
        with self._lock:
            self.status = "cancelled" if self.cancel_requested and report.status != "success" else report.status
            self.ended_at = datetime.now(UTC)
            self.metrics = dict(report.metrics)
            self.report_json = report_json
            self.report_dir = str(report.output_dir)
            self.artifact_dir = str(report.artifact_dir)
            self.error = report.failure_reason

    def fail(self, exc: BaseException) -> None:
        with self._lock:
            self.status = "error"
            self.ended_at = datetime.now(UTC)
            self.error = str(exc)
            self.logs.append(
                {
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "stage": "异常",
                    "message": str(exc),
                }
            )

    def to_dict(self, include_logs: bool = True) -> dict[str, Any]:
        with self._lock:
            duration = None
            if self.started_at:
                end = self.ended_at or datetime.now(UTC)
                duration = round((end - self.started_at).total_seconds(), 2)
            return {
                "id": self.id,
                "task_id": self.task_id,
                "product": self.product,
                "instruction": self.instruction,
                "case_path": self.case_path,
                "mode": self.mode,
                "status": self.status,
                "created_at": self.created_at.isoformat(),
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "ended_at": self.ended_at.isoformat() if self.ended_at else None,
                "duration_seconds": duration,
                "cancel_requested": self.cancel_requested,
                "error": self.error,
                "metrics": dict(self.metrics),
                "report_dir": self.report_dir,
                "artifact_dir": self.artifact_dir,
                "logs": list(self.logs) if include_logs else [],
                "report_available": self.report_json is not None,
            }


class RunManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jobs: dict[str, RunJob] = {}
        self._lock = threading.RLock()

    def list_cases(self) -> list[dict[str, Any]]:
        case_root = self.settings.repo_root / "cases"
        cases: list[dict[str, Any]] = []
        for path in discover_case_files(case_root):
            task = load_task_spec(path)
            relative_path = path.relative_to(self.settings.repo_root)
            cases.append(
                {
                    "id": task.id,
                    "product": task.product,
                    "instruction": task.instruction,
                    "preconditions": task.preconditions,
                    "assertions": [to_jsonable(assertion) for assertion in task.assertions],
                    "tags": task.tags,
                    "path": str(relative_path).replace("\\", "/"),
                    "scripted_action_count": len(task.scripted_actions),
                }
            )
        return cases

    def start_run(self, payload: dict[str, Any]) -> RunJob:
        case_path = self._resolve_case_path(payload)
        task = load_task_spec(case_path)
        mode = "mock" if _parse_bool(payload.get("mock_mode"), self.settings.mock_mode) else "desktop"
        job = RunJob(job_id=uuid.uuid4().hex[:12], task=task, case_path=case_path, mode=mode)

        with self._lock:
            active = self._active_job_locked()
            if active is not None:
                raise ApiError(f"已有任务正在运行：{active.id}", status_code=409)
            self._jobs[job.id] = job

        thread = threading.Thread(target=self._run_job, args=(job, case_path, payload), daemon=True)
        job.thread = thread
        thread.start()
        return job

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)
        return [job.to_dict(include_logs=False) for job in jobs]

    def get_job(self, job_id: str) -> RunJob:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ApiError("运行任务不存在。", status_code=404)
        return job

    def cancel_run(self, job_id: str) -> RunJob:
        job = self.get_job(job_id)
        if job.status in TERMINAL_STATUSES:
            return job
        job.request_cancel()
        return job

    def _run_job(self, job: RunJob, case_path: Path, payload: dict[str, Any]) -> None:
        job.mark_running()
        try:
            settings = self._settings_for_payload(payload)
            task = load_task_spec(case_path)
            runner = build_default_runner(settings)
            runner.runtime_console = WebRuntimeConsole(
                job,
                preview_chars=settings.runtime_preview_chars,
            )
            runner.stop_requested = job.is_cancel_requested
            report = runner.run_task(task)
            job.complete(report)
        except BaseException as exc:
            job.fail(exc)

    def _settings_for_payload(self, payload: dict[str, Any]) -> Settings:
        return replace(
            self.settings,
            mock_mode=_parse_bool(payload.get("mock_mode"), self.settings.mock_mode),
            max_steps=_bounded_int(payload.get("max_steps"), self.settings.max_steps, 1, 50),
            max_retries=_bounded_int(payload.get("max_retries"), self.settings.max_retries, 0, 10),
            window_title_keyword=str(
                payload.get("window_title_keyword") or self.settings.window_title_keyword
            ).strip()
            or self.settings.window_title_keyword,
            ocr_backend=str(payload.get("ocr_backend") or self.settings.ocr_backend),
            provider_mode=str(payload.get("provider_mode") or self.settings.provider_mode),
            openai_model=str(payload.get("openai_model") or self.settings.openai_model),
            load_wait_enabled=_parse_bool(
                payload.get("load_wait_enabled"),
                self.settings.load_wait_enabled,
            ),
            runtime_logs=False,
        )

    def _resolve_case_path(self, payload: dict[str, Any]) -> Path:
        case_id = str(payload.get("case_id") or "").strip()
        raw_path = str(payload.get("case_path") or "").strip()
        case_root = (self.settings.repo_root / "cases").resolve()

        if case_id:
            for path in discover_case_files(case_root):
                task = load_task_spec(path)
                if task.id == case_id:
                    return path
            raise ApiError(f"未找到用例：{case_id}", status_code=404)

        if not raw_path:
            raise ApiError("缺少 case_id 或 case_path。")

        candidate = (self.settings.repo_root / raw_path).resolve()
        try:
            candidate.relative_to(case_root)
        except ValueError as exc:
            raise ApiError("case_path 必须位于 cases 目录内。") from exc
        if not candidate.exists():
            raise ApiError(f"用例文件不存在：{raw_path}", status_code=404)
        return candidate

    def _active_job_locked(self) -> RunJob | None:
        for job in self._jobs.values():
            if job.status not in TERMINAL_STATUSES:
                return job
        return None


def create_app(settings: Settings | None = None) -> Flask:
    resolved_settings = settings or Settings.from_env(Path.cwd())
    app = Flask(__name__, template_folder="templates", static_folder="static")
    manager = RunManager(resolved_settings)
    app.config["run_manager"] = manager
    app.config["settings"] = resolved_settings

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return jsonify({"error": str(error)}), error.status_code

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        return jsonify({"error": error.description}), error.code or 500

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        return jsonify({"error": str(error)}), 500

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(_diagnostics(resolved_settings, manager))

    @app.get("/api/cases")
    def cases():
        return jsonify({"cases": manager.list_cases()})

    @app.get("/api/runs")
    def runs():
        return jsonify({"runs": manager.list_runs()})

    @app.post("/api/runs")
    def start_run():
        payload = request.get_json(silent=True) or {}
        job = manager.start_run(payload)
        return jsonify({"run": job.to_dict()}), 202

    @app.get("/api/runs/<job_id>")
    def run_detail(job_id: str):
        return jsonify({"run": manager.get_job(job_id).to_dict()})

    @app.post("/api/runs/<job_id>/cancel")
    def cancel_run(job_id: str):
        return jsonify({"run": manager.cancel_run(job_id).to_dict()})

    @app.get("/api/runs/<job_id>/report")
    def run_report(job_id: str):
        job = manager.get_job(job_id)
        if not job.report_dir:
            raise ApiError("报告尚未生成。", status_code=404)
        report_path = Path(job.report_dir) / "report.md"
        if not report_path.exists():
            raise ApiError("Markdown 报告不存在。", status_code=404)
        return jsonify({"markdown": report_path.read_text(encoding="utf-8")})

    @app.get("/api/runs/<job_id>/run-json")
    def run_json(job_id: str):
        job = manager.get_job(job_id)
        if job.report_json is None:
            raise ApiError("结构化报告尚未生成。", status_code=404)
        return jsonify({"report": job.report_json})

    @app.get("/api/runs/<job_id>/timeline")
    def run_timeline(job_id: str):
        job = manager.get_job(job_id)
        timeline_dir = _timeline_dir(job)
        if timeline_dir is None:
            return jsonify({"images": []})
        images = [
            {
                "name": path.name,
                "url": url_for("timeline_image", job_id=job.id, filename=path.name),
            }
            for path in sorted(timeline_dir.glob("*.png"))
        ]
        return jsonify({"images": images})

    @app.get("/api/runs/<job_id>/timeline/<path:filename>")
    def timeline_image(job_id: str, filename: str):
        job = manager.get_job(job_id)
        timeline_dir = _timeline_dir(job)
        if timeline_dir is None:
            raise ApiError("截图时间线尚未生成。", status_code=404)
        return send_from_directory(timeline_dir, filename)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the CUA-Lark-Gui Flask control console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    settings = Settings.from_env(Path.cwd())
    app = create_app(settings)
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0


def _diagnostics(settings: Settings, manager: RunManager) -> dict[str, Any]:
    ocr_diagnostics = paddleocr_diagnostics()
    active_runs = [
        run for run in manager.list_runs() if run["status"] not in TERMINAL_STATUSES
    ]
    return {
        "repo_root": str(settings.repo_root),
        "mode": "mock" if settings.mock_mode else "desktop",
        "openai_base_url": settings.openai_base_url,
        "openai_model": settings.openai_model,
        "openai_api_key_set": bool(settings.openai_api_key),
        "window_title_keyword": settings.window_title_keyword,
        "ocr_backend": settings.ocr_backend,
        "paddleocr_importable": ocr_diagnostics["importable"],
        "paddleocr_error": ocr_diagnostics["error"],
        "busy": bool(active_runs),
        "active_run_id": active_runs[0]["id"] if active_runs else None,
    }


def _timeline_dir(job: RunJob) -> Path | None:
    if not job.artifact_dir:
        return None
    timeline_dir = Path(job.artifact_dir) / "timeline"
    if not timeline_dir.exists():
        return None
    return timeline_dir


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "mock"}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


if __name__ == "__main__":
    raise SystemExit(main())
