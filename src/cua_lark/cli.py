from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .case_loader import load_case, load_suite
from .config import DEFAULT_PIP_INDEX_URL, Settings
from .executor import ActionExecutor
from .llm import ReplayVLMClient, VLMClient
from .orchestrator import Orchestrator
from .perception import PerceptionAgent, ScreenCapturer
from .windowing import FeishuWindowManager

app = typer.Typer(help="CUA-Lark GUI testing agent for Feishu/Lark desktop.")
console = Console()


def _settings() -> Settings:
    return Settings.from_env()


def _log(message: str) -> None:
    console.print(message, markup=False)


@app.command()
def doctor(
    check_vlm: bool = typer.Option(False, help="Call the configured VLM once."),
    screenshot: bool = typer.Option(False, help="Capture one local screenshot."),
) -> None:
    """Check local runtime, mirror guidance, config, and optional VLM access."""
    settings = _settings()
    table = Table(title="CUA-Lark Doctor")
    table.add_column("Item")
    table.add_column("Value")
    table.add_row("Python", sys.executable)
    table.add_row("Pip mirror", DEFAULT_PIP_INDEX_URL)
    table.add_row("OPENAI_BASE_URL", settings.openai_base_url)
    table.add_row("OPENAI_MODEL", settings.openai_model)
    table.add_row("OPENAI_API_KEY", settings.redacted_api_key)
    table.add_row("Window pattern", settings.window_title_pattern)
    table.add_row("Runs dir", str(settings.runs_dir))
    console.print(table)

    if screenshot:
        capturer = ScreenCapturer(
            window_manager=FeishuWindowManager(
                title_pattern=settings.window_title_pattern
            )
        )
        output = settings.runs_dir / "doctor_screenshot.png"
        capture = capturer.capture(output)
        bounds = capture.screenshot_bounds
        console.print(
            "Screenshot saved: "
            f"{output} ({bounds.width}x{bounds.height}) "
            f"window={capture.window_title or 'unknown'}"
        )

    if check_vlm:
        data = VLMClient(settings).complete_json(
            "Return JSON exactly like {\"ok\": true, \"message\": \"ready\"}."
        )
        console.print_json(json=json.dumps(data, ensure_ascii=False, indent=2))


@app.command("run")
def run_case(
    case_path: Path,
    dry_run: bool = typer.Option(False, help="Do not move mouse or keyboard."),
    replay_vlm: Optional[Path] = typer.Option(
        None, help="JSON file containing a list of deterministic VLM responses."
    ),
    dry_run_image: Optional[Path] = typer.Option(
        None, help="Image file used as screenshot source in dry-run mode."
    ),
) -> None:
    """Run one YAML test case."""
    settings = _settings()
    case = load_case(case_path)
    vlm = _build_vlm(settings, replay_vlm, allow_none=dry_run and replay_vlm is None)
    capturer = _build_capturer(dry_run=dry_run, dry_run_image=dry_run_image)
    perception = PerceptionAgent(
        vlm,
        capturer=capturer,
    )
    orchestrator = Orchestrator(
        settings,
        vlm=vlm,
        perception=perception,
        executor=ActionExecutor(dry_run=dry_run),
        logger=_log,
    )
    context = orchestrator.run(case)
    console.print(f"Run {context.run_id}: {context.status}")
    if context.failure_reason:
        console.print(f"Failure: {context.failure_reason}")


@app.command("run-suite")
def run_suite(
    suite_path: Path,
    dry_run: bool = typer.Option(False, help="Do not move mouse or keyboard."),
) -> None:
    """Run all cases listed in a YAML suite."""
    settings = _settings()
    for case_path in load_suite(suite_path):
        case = load_case(case_path)
        vlm = None if dry_run else VLMClient(settings)
        perception = PerceptionAgent(vlm, capturer=_build_capturer(dry_run=dry_run))
        orchestrator = Orchestrator(
            settings,
            vlm=vlm,
            perception=perception,
            executor=ActionExecutor(dry_run=dry_run),
            logger=_log,
        )
        context = orchestrator.run(case)
        console.print(f"{case.id}: {context.status}")


@app.command("report")
def report(run_dir: Path) -> None:
    """Print generated report paths for a completed run directory."""
    for name in ("report.json", "report.md", "report.html"):
        path = run_dir / name
        console.print(f"{name}: {'exists' if path.exists() else 'missing'} - {path}")


def _build_vlm(
    settings: Settings,
    replay_vlm: Path | None,
    *,
    allow_none: bool = False,
):
    if replay_vlm is not None:
        raw = json.loads(replay_vlm.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise typer.BadParameter("replay_vlm must contain a JSON list")
        return ReplayVLMClient(raw)
    if allow_none:
        return None
    return VLMClient(settings)


def _build_capturer(
    *,
    dry_run: bool,
    dry_run_image: Path | None = None,
) -> ScreenCapturer | None:
    settings = _settings()
    if dry_run_image is not None:
        return ScreenCapturer(dry_run_image=dry_run_image)
    if dry_run:
        return ScreenCapturer(blank_size=(1280, 800))
    return ScreenCapturer(
        window_manager=FeishuWindowManager(title_pattern=settings.window_title_pattern)
    )


if __name__ == "__main__":
    app()
