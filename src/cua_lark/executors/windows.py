from __future__ import annotations

import ctypes
import time
from typing import Any

from cua_lark.executors.base import DesktopExecutor
from cua_lark.models import ActionStep


MAX_CAPTURE_REGION_PIXELS = 80_000_000
MAX_CAPTURE_REGION_SIDE = 20_000
MIN_CAPTURE_WINDOW_WIDTH = 80
MIN_CAPTURE_WINDOW_HEIGHT = 60


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
        self._main_window_region: tuple[int, int, int, int] | None = None
        self._active_context_region: tuple[int, int, int, int] | None = None
        self._window_infos: list[dict[str, Any]] = []

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
            region = self._region_from_window(window)
            self._main_window_region = region
            self._window_region = region
            return region is not None
        except Exception:
            return False

    def capture_region(self) -> tuple[int, int, int, int] | None:
        if not self._gw or not self._window_keyword:
            return None
        context = self._discover_window_context()
        if context is None:
            return None
        region, window_infos, active_region, main_region = context
        self._window_region = region
        self._window_infos = window_infos
        self._active_context_region = active_region
        if main_region is not None:
            self._main_window_region = main_region
        return region

    def snapshot_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        region = self.capture_region()
        if region is not None:
            state["capture_region"] = list(region)
        if self._main_window_region is not None:
            state["main_window_region"] = list(self._main_window_region)
        if self._active_context_region is not None:
            state["active_context_region"] = list(self._active_context_region)
        if self._window_infos:
            state["window_candidates"] = self._window_infos
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
        if self._active_context_region is not None:
            meta["active_context_region"] = list(self._active_context_region)

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
                point, point_strategy = self._default_text_entry_point(step)
                if point is not None:
                    pyautogui.click(*point, button="left")
                    meta["screen_coordinates"] = list(point)
                    meta["used_default_text_entry_point"] = True
                    meta["default_text_entry_strategy"] = point_strategy
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
        if self._window_region is not None:
            return
        if self._window_keyword:
            self.focus_window(self._window_keyword)

    def _discover_window_context(
        self,
    ) -> tuple[
        tuple[int, int, int, int],
        list[dict[str, Any]],
        tuple[int, int, int, int] | None,
        tuple[int, int, int, int] | None,
    ] | None:
        if not self._gw or not self._window_keyword:
            return None
        try:
            keyword_windows = list(self._gw.getWindowsWithTitle(self._window_keyword))
        except Exception:
            keyword_windows = []
        keyword_regions = [
            region for region in (self._region_from_window(window) for window in keyword_windows) if region is not None
        ]
        if not keyword_regions:
            return None

        main_region = self._largest_region(keyword_regions)
        candidates: list[tuple[Any, tuple[int, int, int, int], str]] = []
        seen: set[tuple[int, int, int, int]] = set()

        for window in keyword_windows:
            region = self._region_from_window(window)
            if region is None:
                continue
            candidates.append((window, region, "keyword"))
            seen.add(region)

        active_window = self._active_window()
        active_region = self._region_from_window(active_window) if active_window is not None else None
        active_context_region: tuple[int, int, int, int] | None = None
        if active_window is not None and active_region is not None and self._is_context_window(active_region, main_region):
            active_context_region = active_region
            if active_region not in seen:
                candidates.append((active_window, active_region, "active_child"))
                seen.add(active_region)

        for window in self._all_windows():
            region = self._region_from_window(window)
            if region is None or region in seen:
                continue
            if self._looks_like_child_window(window, region, main_region):
                candidates.append((window, region, "overlap_child"))
                seen.add(region)

        regions = [region for _, region, _ in candidates]
        union_region = self._union_regions(regions)
        window_infos = [
            self._window_info(window, region, role, union_region, active_region)
            for window, region, role in candidates
        ]
        return (union_region, window_infos, active_context_region, main_region)

    def _region_from_window(self, window: Any) -> tuple[int, int, int, int] | None:
        if window is None or self._is_minimized(window):
            return None
        try:
            left = int(window.left)
            top = int(window.top)
            width = int(window.width)
            height = int(window.height)
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        if width > MAX_CAPTURE_REGION_SIDE or height > MAX_CAPTURE_REGION_SIDE:
            return None
        if self._region_area((left, top, width, height)) > MAX_CAPTURE_REGION_PIXELS:
            return None

        clipped = self._clip_region_to_virtual_screen((left, top, width, height))
        if clipped is None:
            return None
        _, _, clipped_width, clipped_height = clipped
        if clipped_width < MIN_CAPTURE_WINDOW_WIDTH or clipped_height < MIN_CAPTURE_WINDOW_HEIGHT:
            return None
        if self._region_area(clipped) > MAX_CAPTURE_REGION_PIXELS:
            return None
        return clipped

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
        region = getattr(self, "_window_region", None) or self.capture_region()
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
        region = getattr(self, "_window_region", None) or self.capture_region()
        if region is None:
            return point
        left, top, _, _ = region
        return (left + point[0], top + point[1])

    def _default_text_entry_point(self, step: ActionStep | None = None) -> tuple[tuple[int, int] | None, str]:
        region = (
            getattr(self, "_active_context_region", None)
            or getattr(self, "_window_region", None)
            or self.capture_region()
        )
        if region is None:
            return None, "none"
        left, top, width, height = region
        if self._looks_like_calendar_form_context(step):
            return (left + int(width * 0.18), top + int(height * 0.12)), "calendar_form_title"
        return (left + int(width * 0.62), top + int(height * 0.86)), "generic_bottom_input"

    def _looks_like_calendar_form_context(self, step: ActionStep | None) -> bool:
        text = " ".join(
            str(part)
            for part in [
                step.description if step else "",
                step.text if step else "",
                step.validation_hint if step else "",
                *(info.get("title", "") for info in getattr(self, "_window_infos", [])),
            ]
            if part
        )
        markers = ("创建日程", "新建日程", "添加主题", "会议", "日程", "周会")
        return any(marker in text for marker in markers)

    def _active_window(self) -> Any:
        if not self._gw:
            return None
        getter = getattr(self._gw, "getActiveWindow", None)
        if getter is None:
            return None
        try:
            return getter()
        except Exception:
            return None

    def _all_windows(self) -> list[Any]:
        if not self._gw:
            return []
        getter = getattr(self._gw, "getAllWindows", None)
        if getter is None:
            return []
        try:
            return list(getter())
        except Exception:
            return []

    def _looks_like_child_window(
        self,
        window: Any,
        region: tuple[int, int, int, int],
        main_region: tuple[int, int, int, int],
    ) -> bool:
        title = str(getattr(window, "title", "") or "").strip()
        if self._window_keyword and self._window_keyword in title:
            return True
        if self._is_minimized(window):
            return False
        left, top, width, height = region
        if width < 120 or height < 80:
            return False
        _, _, main_width, main_height = main_region
        if width * height >= main_width * main_height * 0.98:
            return False
        return self._is_context_window(region, main_region)

    def _is_context_window(
        self,
        region: tuple[int, int, int, int],
        main_region: tuple[int, int, int, int],
    ) -> bool:
        if region == main_region:
            return True
        if self._contains_point(main_region, self._center(region), padding=80):
            return True
        overlap = self._overlap_area(region, main_region)
        area = max(1, region[2] * region[3])
        return overlap / area >= 0.25

    def _window_info(
        self,
        window: Any,
        region: tuple[int, int, int, int],
        role: str,
        union_region: tuple[int, int, int, int],
        active_region: tuple[int, int, int, int] | None,
    ) -> dict[str, Any]:
        left, top, width, height = region
        union_left, union_top, _, _ = union_region
        return {
            "title": str(getattr(window, "title", "") or ""),
            "role": role,
            "active": bool(active_region is not None and region == active_region),
            "region": [left, top, width, height],
            "relative_region": [left - union_left, top - union_top, width, height],
        }

    def _is_minimized(self, window: Any) -> bool:
        try:
            return bool(window.isMinimized)
        except Exception:
            return False

    def _largest_region(self, regions: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
        return max(regions, key=lambda region: region[2] * region[3])

    def _union_regions(self, regions: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
        left = min(region[0] for region in regions)
        top = min(region[1] for region in regions)
        right = max(region[0] + region[2] for region in regions)
        bottom = max(region[1] + region[3] for region in regions)
        union = (left, top, right - left, bottom - top)
        if self._region_area(union) <= MAX_CAPTURE_REGION_PIXELS:
            return union

        virtual_region = self._virtual_screen_region()
        clipped = self._intersection_region(union, virtual_region)
        if clipped is not None and self._region_area(clipped) <= MAX_CAPTURE_REGION_PIXELS:
            return clipped
        return self._largest_region(regions)

    def _clip_region_to_virtual_screen(
        self,
        region: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int] | None:
        return self._intersection_region(region, self._virtual_screen_region())

    def _virtual_screen_region(self) -> tuple[int, int, int, int]:
        try:
            user32 = ctypes.windll.user32
            left = int(user32.GetSystemMetrics(76))
            top = int(user32.GetSystemMetrics(77))
            width = int(user32.GetSystemMetrics(78))
            height = int(user32.GetSystemMetrics(79))
            if width > 0 and height > 0:
                return (left, top, width, height)
        except Exception:
            pass

        pyautogui = getattr(self, "_pyautogui", None)
        if pyautogui is not None:
            try:
                width, height = pyautogui.size()
                width = int(width)
                height = int(height)
                if width > 0 and height > 0:
                    return (0, 0, width, height)
            except Exception:
                pass
        return (-10_000, -10_000, 20_000, 20_000)

    def _intersection_region(
        self,
        a: tuple[int, int, int, int],
        b: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int] | None:
        left = max(a[0], b[0])
        top = max(a[1], b[1])
        right = min(a[0] + a[2], b[0] + b[2])
        bottom = min(a[1] + a[3], b[1] + b[3])
        if right <= left or bottom <= top:
            return None
        return (left, top, right - left, bottom - top)

    def _region_area(self, region: tuple[int, int, int, int]) -> int:
        return max(0, region[2]) * max(0, region[3])

    def _center(self, region: tuple[int, int, int, int]) -> tuple[int, int]:
        left, top, width, height = region
        return (left + width // 2, top + height // 2)

    def _contains_point(
        self,
        region: tuple[int, int, int, int],
        point: tuple[int, int],
        padding: int = 0,
    ) -> bool:
        left, top, width, height = region
        x, y = point
        return left - padding <= x <= left + width + padding and top - padding <= y <= top + height + padding

    def _overlap_area(
        self,
        a: tuple[int, int, int, int],
        b: tuple[int, int, int, int],
    ) -> int:
        left = max(a[0], b[0])
        top = max(a[1], b[1])
        right = min(a[0] + a[2], b[0] + b[2])
        bottom = min(a[1] + a[3], b[1] + b[3])
        if right <= left or bottom <= top:
            return 0
        return (right - left) * (bottom - top)

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
