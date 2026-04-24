from __future__ import annotations

import time
from typing import Any

from cua_lark.executors.base import DesktopExecutor
from cua_lark.models import ActionStep


class WindowsDesktopExecutor(DesktopExecutor):
    backend_name = "windows_executor"

    def __init__(self) -> None:
        try:
            import pyautogui  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "pyautogui is not installed. Run `python -m pip install -e .[desktop]`."
            ) from exc

        self._pyautogui = pyautogui
        self._pyautogui.FAILSAFE = True
        self._pyautogui.PAUSE = 0.1

        try:
            import pygetwindow as gw  # type: ignore
        except ImportError:
            gw = None
        self._gw = gw
        self._window_keyword: str | None = None

    def focus_window(self, keyword: str) -> bool:
        self._window_keyword = keyword
        if not self._gw:
            return False
        candidates = self._gw.getWindowsWithTitle(keyword)
        if not candidates:
            return False
        window = candidates[0]
        try:
            if window.isMinimized:
                window.restore()
            window.activate()
            return True
        except Exception:
            return False

    def capture_region(self) -> tuple[int, int, int, int] | None:
        if not self._gw or not self._window_keyword:
            return None
        try:
            candidates = self._gw.getWindowsWithTitle(self._window_keyword)
        except Exception:
            return None
        if not candidates:
            return None
        window = candidates[0]
        try:
            left = int(window.left)
            top = int(window.top)
            width = int(window.width)
            height = int(window.height)
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        return (left, top, width, height)

    def snapshot_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        region = self.capture_region()
        if region is not None:
            state["capture_region"] = list(region)
        if self._window_keyword:
            state["focused_window_keyword"] = self._window_keyword
        return state

    def execute(self, step: ActionStep) -> dict[str, Any]:
        pyautogui = self._pyautogui
        point = self._resolve_point(step)

        if step.action_type == "click":
            pyautogui.click(*point, button=step.button)
        elif step.action_type == "double_click":
            pyautogui.doubleClick(*point, button=step.button)
        elif step.action_type == "right_click":
            pyautogui.click(*point, button="right")
        elif step.action_type == "drag":
            if point is None:
                raise RuntimeError("Drag action requires start coordinates.")
            to_coordinates = step.metadata.get("to_coordinates")
            if not isinstance(to_coordinates, (list, tuple)) or len(to_coordinates) != 2:
                raise RuntimeError("Drag action requires metadata.to_coordinates.")
            pyautogui.moveTo(*point)
            pyautogui.dragTo(int(to_coordinates[0]), int(to_coordinates[1]), duration=0.3)
        elif step.action_type == "scroll":
            pyautogui.scroll(step.scroll_amount)
        elif step.action_type == "type_text":
            pyautogui.write(step.text or "", interval=0.02)
        elif step.action_type == "hotkey":
            pyautogui.hotkey(*step.hotkey)
        elif step.action_type == "wait":
            time.sleep(step.wait_seconds)
        elif step.action_type in {"assert", "noop"}:
            return {"mode": "desktop", "action_type": step.action_type}
        else:
            raise RuntimeError(f"Unsupported action type: {step.action_type}")

        return {"mode": "desktop", "action_type": step.action_type}

    def _resolve_point(self, step: ActionStep) -> tuple[int, int] | None:
        if step.coordinates:
            return step.coordinates
        if step.target and step.target.bbox:
            return step.target.bbox.center
        coords = step.metadata.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) == 2:
            return (int(coords[0]), int(coords[1]))
        return None
