from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from PIL import Image

from .llm import VLMClient
from .models import Bounds, Observation, UICandidate


class ScreenCaptureError(RuntimeError):
    pass


class ScreenCapturer:
    def __init__(
        self,
        *,
        dry_run_image: str | Path | None = None,
        blank_size: tuple[int, int] | None = None,
    ):
        self.dry_run_image = Path(dry_run_image) if dry_run_image else None
        self.blank_size = blank_size

    def capture(self, output_path: str | Path) -> Bounds:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if self.dry_run_image:
            image = Image.open(self.dry_run_image)
            image.save(path)
            return Bounds(left=0, top=0, width=image.width, height=image.height)

        if self.blank_size:
            image = Image.new("RGB", self.blank_size, "white")
            image.save(path)
            return Bounds(left=0, top=0, width=image.width, height=image.height)

        try:
            import pyautogui
        except Exception as exc:  # pragma: no cover - import guard
            raise ScreenCaptureError("pyautogui is required for screenshot capture") from exc

        try:
            image = pyautogui.screenshot()
        except Exception as exc:  # pragma: no cover - depends on desktop
            raise ScreenCaptureError(f"Screenshot capture failed: {exc}") from exc

        image.save(path)
        return Bounds(left=0, top=0, width=image.width, height=image.height)


class PerceptionAgent:
    def __init__(
        self,
        vlm: VLMClient | None,
        *,
        capturer: ScreenCapturer | None = None,
        scale_factor: float = 1.0,
    ):
        self.vlm = vlm
        self.capturer = capturer or ScreenCapturer()
        self.scale_factor = scale_factor

    def observe(self, run_dir: str | Path, *, label: str = "observe") -> Observation:
        screenshots_dir = Path(run_dir) / "screenshots"
        timestamp = int(time.time() * 1000)
        screenshot_path = screenshots_dir / f"{timestamp}_{label}.png"
        bounds = self.capturer.capture(screenshot_path)

        page_summary = ""
        ui_candidates: list[UICandidate] = []
        alerts: list[str] = []
        if self.vlm is not None:
            prompt = (
                "Analyze this Feishu/Lark desktop screenshot for GUI testing. "
                "Return JSON with keys: page_summary, ui_candidates, alerts. "
                "ui_candidates should be a list of objects with label, role, "
                "optional bounds {left, top, width, height}, and confidence."
            )
            data = self.vlm.complete_json(prompt, images=[screenshot_path])
            page_summary = str(data.get("page_summary", ""))
            alerts = [str(item) for item in data.get("alerts", []) if item]
            ui_candidates = self._parse_candidates(data.get("ui_candidates", []))

        return Observation(
            screenshot_path=str(screenshot_path),
            window_bounds=bounds,
            scale_factor=self.scale_factor,
            page_summary=page_summary,
            ui_candidates=ui_candidates,
            alerts=alerts,
        )

    @staticmethod
    def _parse_candidates(raw_candidates: Any) -> list[UICandidate]:
        candidates: list[UICandidate] = []
        if not isinstance(raw_candidates, list):
            return candidates
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                continue
            try:
                candidates.append(UICandidate(**raw))
            except Exception:
                continue
        return candidates
