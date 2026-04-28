from __future__ import annotations

import time
from pathlib import Path

from .models import ActionName, ActionProposal, ExecutionResult, Observation, Point


class ActionExecutionError(RuntimeError):
    pass


def scale_point(point: Point, scale_factor: float) -> Point:
    return Point(x=round(point.x / scale_factor), y=round(point.y / scale_factor))


class ActionExecutor:
    def __init__(self, *, dry_run: bool = False, pause_seconds: float = 0.15):
        self.dry_run = dry_run
        self.pause_seconds = pause_seconds

    def execute(
        self,
        proposal: ActionProposal,
        observation: Observation | None = None,
        *,
        run_dir: str | Path | None = None,
    ) -> ExecutionResult:
        started = time.monotonic()
        try:
            self._validate(proposal, observation)
            if self.dry_run:
                return ExecutionResult(
                    executed=True,
                    message=f"dry-run: {proposal.action.value}",
                    duration_ms=self._elapsed_ms(started),
                )
            self._execute_real(proposal, observation, run_dir=run_dir)
            return ExecutionResult(
                executed=True,
                message=f"executed: {proposal.action.value}",
                duration_ms=self._elapsed_ms(started),
            )
        except Exception as exc:
            return ExecutionResult(
                executed=False,
                message=str(exc),
                duration_ms=self._elapsed_ms(started),
            )

    def _validate(self, proposal: ActionProposal, observation: Observation | None) -> None:
        if proposal.needs_coordinates() and proposal.coordinates is None:
            raise ActionExecutionError(f"{proposal.action.value} requires coordinates")

        if observation and proposal.coordinates:
            bounds = observation.window_bounds
            if not bounds.contains(proposal.coordinates):
                raise ActionExecutionError(
                    f"coordinates {proposal.coordinates.x},{proposal.coordinates.y} "
                    f"are outside screenshot bounds {bounds.width}x{bounds.height}"
                )

    def _execute_real(
        self,
        proposal: ActionProposal,
        observation: Observation | None,
        *,
        run_dir: str | Path | None = None,
    ) -> None:
        try:
            import pyautogui
        except Exception as exc:  # pragma: no cover - import guard
            raise ActionExecutionError("pyautogui is required for real execution") from exc

        scale_factor = observation.scale_factor if observation else 1.0

        if proposal.action == ActionName.CLICK:
            point = self._to_screen_point(proposal.coordinates, observation, scale_factor)  # type: ignore[arg-type]
            pyautogui.click(point.x, point.y)
        elif proposal.action == ActionName.DOUBLE_CLICK:
            point = self._to_screen_point(proposal.coordinates, observation, scale_factor)  # type: ignore[arg-type]
            pyautogui.doubleClick(point.x, point.y)
        elif proposal.action == ActionName.RIGHT_CLICK:
            point = self._to_screen_point(proposal.coordinates, observation, scale_factor)  # type: ignore[arg-type]
            pyautogui.rightClick(point.x, point.y)
        elif proposal.action == ActionName.DRAG:
            start = self._to_screen_point(proposal.coordinates, observation, scale_factor)  # type: ignore[arg-type]
            end = self._to_screen_point(proposal.end_coordinates, observation, scale_factor)  # type: ignore[arg-type]
            pyautogui.moveTo(start.x, start.y)
            pyautogui.dragTo(end.x, end.y, duration=0.3, button="left")
        elif proposal.action == ActionName.SCROLL:
            pyautogui.scroll(proposal.scroll_amount or -5)
        elif proposal.action == ActionName.TYPE_TEXT:
            self._paste_text(proposal.text or "")
        elif proposal.action == ActionName.HOTKEY:
            if not proposal.hotkeys:
                raise ActionExecutionError("hotkey action requires hotkeys")
            pyautogui.hotkey(*proposal.hotkeys)
        elif proposal.action == ActionName.WAIT:
            time.sleep(proposal.wait_seconds)
        elif proposal.action == ActionName.SCREENSHOT:
            if run_dir is None:
                raise ActionExecutionError("screenshot action requires run_dir")
            output = Path(run_dir) / "screenshots" / f"{int(time.time() * 1000)}_manual.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            if observation and observation.screen_bounds:
                bounds = observation.screen_bounds
                pyautogui.screenshot(
                    region=(bounds.left, bounds.top, bounds.width, bounds.height)
                ).save(output)
            else:
                pyautogui.screenshot().save(output)
        elif proposal.action in {ActionName.ASSERT_STATE, ActionName.FINISH}:
            return
        else:  # pragma: no cover - enum safety
            raise ActionExecutionError(f"unsupported action: {proposal.action}")

        time.sleep(self.pause_seconds)

    @staticmethod
    def _to_screen_point(
        screenshot_point: Point,
        observation: Observation | None,
        scale_factor: float,
    ) -> Point:
        point = scale_point(screenshot_point, scale_factor)
        if observation and observation.screen_bounds:
            return Point(
                x=observation.screen_bounds.left + point.x,
                y=observation.screen_bounds.top + point.y,
            )
        return point

    @staticmethod
    def _paste_text(text: str) -> None:
        try:
            import pyautogui
            import pyperclip
        except Exception as exc:  # pragma: no cover - import guard
            raise ActionExecutionError("pyautogui and pyperclip are required for text input") from exc

        previous = None
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        if previous is not None:
            pyperclip.copy(previous)

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.monotonic() - started) * 1000)
