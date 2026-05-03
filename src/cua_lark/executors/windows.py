from __future__ import annotations

import ctypes
import time
from typing import Any

from cua_lark.executors.base import DesktopExecutor
from cua_lark.models import ActionStep


class WindowsDesktopExecutor(DesktopExecutor):
    backend_name = "windows_executor"

    def __init__(self) -> None:
        self._enable_dpi_awareness()
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
        self._window_region: tuple[int, int, int, int] | None = None

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
            time.sleep(0.3)
            self._window_region = self._region_from_window(window)
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
        region = self._region_from_window(candidates[0])
        if region is None:
            return None
        self._window_region = region
        return region

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
        self._ensure_window_active()
        point = self._resolve_point(step)
        meta: dict[str, Any] = {"mode": "desktop", "action_type": step.action_type}
        if point is not None:
            meta["screen_coordinates"] = list(point)
        if self._window_region is not None:
            meta["window_region"] = list(self._window_region)

        if step.action_type == "click":
            if point is None:
                raise RuntimeError("Click action requires coordinates or target bbox.")
            pyautogui.click(*point, button=step.button)
        elif step.action_type == "double_click":
            if point is None:
                raise RuntimeError("Double click action requires coordinates or target bbox.")
            pyautogui.doubleClick(*point, button=step.button)
        elif step.action_type == "right_click":
            if point is None:
                raise RuntimeError("Right click action requires coordinates or target bbox.")
            pyautogui.click(*point, button="right")
        elif step.action_type == "drag":
            if point is None:
                raise RuntimeError("Drag action requires start coordinates.")
            to_coordinates = step.metadata.get("to_coordinates")
            if not isinstance(to_coordinates, (list, tuple)) or len(to_coordinates) != 2:
                raise RuntimeError("Drag action requires metadata.to_coordinates.")
            to_point = self._window_to_screen((int(to_coordinates[0]), int(to_coordinates[1])))
            pyautogui.moveTo(*point)
            pyautogui.dragTo(*to_point, duration=0.3)
            meta["screen_to_coordinates"] = list(to_point)
        elif step.action_type == "scroll":
            pyautogui.scroll(step.scroll_amount)
        elif step.action_type == "type_text":
            text = step.text or ""
            meta["text_length"] = len(text)
            if point is None:
                point = self._default_text_entry_point()
                if point is not None:
                    pyautogui.click(*point, button="left")
                    meta["screen_coordinates"] = list(point)
                    meta["used_default_text_entry_point"] = True
            self._paste_text(text)
        elif step.action_type == "hotkey":
            if not step.hotkey:
                raise RuntimeError("Hotkey action requires at least one key.")
            pyautogui.hotkey(*step.hotkey)
            meta["hotkey"] = list(step.hotkey)
            time.sleep(0.2)
        elif step.action_type == "wait":
            time.sleep(step.wait_seconds)
        elif step.action_type in {"assert", "noop"}:
            return meta
        else:
            raise RuntimeError(f"Unsupported action type: {step.action_type}")

        return meta

    def _resolve_point(self, step: ActionStep) -> tuple[int, int] | None:
        if step.coordinates:
            return self._window_to_screen(self._normalize_window_point(step.coordinates, step))
        if step.target and step.target.bbox:
            return self._window_to_screen(self._normalize_window_point(step.target.bbox.center, step))
        coords = step.metadata.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) == 2:
            return self._window_to_screen(self._normalize_window_point((int(coords[0]), int(coords[1])), step))
        normalized = step.metadata.get("normalized_coordinates")
        if isinstance(normalized, (list, tuple)) and len(normalized) == 2:
            return self._window_to_screen(self._point_from_normalized(normalized))
        return None

    def _ensure_window_active(self) -> None:
        if self._window_keyword:
            self.focus_window(self._window_keyword)

    def _region_from_window(self, window: Any) -> tuple[int, int, int, int] | None:
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

    def _normalize_window_point(self, point: tuple[int, int], step: ActionStep) -> tuple[int, int]:
        normalized = step.metadata.get("normalized_coordinates")
        if isinstance(normalized, (list, tuple)) and len(normalized) == 2:
            return self._point_from_normalized(normalized)

        coordinate_mode = str(step.metadata.get("coordinate_mode", "window"))
        if coordinate_mode not in {"api_image", "source_image", "model_image"}:
            return point

        source_size = self._parse_size(step.metadata.get("source_image_size"))
        screenshot_size = self._parse_size(step.metadata.get("screenshot_size"))
        if source_size is None or screenshot_size is None:
            return point
        if source_size == screenshot_size:
            return point
        source_width, source_height = source_size
        screenshot_width, screenshot_height = screenshot_size
        if source_width <= 0 or source_height <= 0:
            return point
        scale_x = screenshot_width / source_width
        scale_y = screenshot_height / source_height
        return (round(point[0] * scale_x), round(point[1] * scale_y))

    def _point_from_normalized(self, normalized: Any) -> tuple[int, int]:
        region = self.capture_region()
        if region is not None:
            _, _, width, height = region
        else:
            width, height = self._pyautogui.size()
        x_ratio = max(0.0, min(1.0, float(normalized[0])))
        y_ratio = max(0.0, min(1.0, float(normalized[1])))
        return (round(width * x_ratio), round(height * y_ratio))

    def _parse_size(self, value: Any) -> tuple[int, int] | None:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            width = int(float(value[0]))
            height = int(float(value[1]))
            if width > 0 and height > 0:
                return (width, height)
        return None

    def _window_to_screen(self, point: tuple[int, int]) -> tuple[int, int]:
        region = self.capture_region()
        if region is None:
            return point
        left, top, _, _ = region
        return (left + point[0], top + point[1])

    def _default_text_entry_point(self) -> tuple[int, int] | None:
        region = self.capture_region()
        if region is None:
            return None
        left, top, width, height = region
        return (left + int(width * 0.62), top + int(height * 0.86))

    def _enable_dpi_awareness(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:
            pass
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    def _paste_text(self, text: str) -> None:
        if not text:
            return
        pyautogui = self._pyautogui
        try:
            import pyperclip  # type: ignore

            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.1)
            return
        except Exception:
            pass
        pyautogui.write(text, interval=0.02)
