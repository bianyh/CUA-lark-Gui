from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .models import Bounds


class WindowError(RuntimeError):
    pass


class WindowNotFoundError(WindowError):
    pass


@dataclass(frozen=True)
class WindowInfo:
    title: str
    bounds: Bounds


class FeishuWindowManager:
    """Find and activate the Feishu/Lark desktop window before capture/actions."""

    def __init__(
        self,
        *,
        title_pattern: str = r"飞书|Feishu|Lark",
        activation_wait_seconds: float = 0.35,
    ):
        self.title_pattern = title_pattern
        self.activation_wait_seconds = activation_wait_seconds
        self._compiled_pattern = re.compile(title_pattern, re.IGNORECASE)

    def ensure_active(self) -> WindowInfo:
        window = self._find_with_pygetwindow()
        if window is not None:
            return self._activate_pygetwindow(window)

        info = self._find_and_activate_with_pywinauto()
        if info is not None:
            return info

        raise WindowNotFoundError(
            f"Could not find a Feishu/Lark window matching: {self.title_pattern}"
        )

    def _find_with_pygetwindow(self):
        try:
            import pygetwindow as gw
        except Exception:
            return None

        matches = []
        for window in gw.getAllWindows():
            title = (getattr(window, "title", "") or "").strip()
            width = int(getattr(window, "width", 0) or 0)
            height = int(getattr(window, "height", 0) or 0)
            if title and width > 0 and height > 0 and self._compiled_pattern.search(title):
                matches.append(window)
        if not matches:
            return None
        matches.sort(key=lambda item: int(getattr(item, "width", 0)) * int(getattr(item, "height", 0)), reverse=True)
        return matches[0]

    def _activate_pygetwindow(self, window) -> WindowInfo:
        try:
            if getattr(window, "isMinimized", False):
                window.restore()
            window.activate()
        except Exception:
            # Some Windows shells deny activate; pyautogui operations still need
            # the window bounds, so keep going after a best-effort restore.
            try:
                window.restore()
            except Exception:
                pass
        time.sleep(self.activation_wait_seconds)
        return WindowInfo(
            title=(getattr(window, "title", "") or "").strip(),
            bounds=Bounds(
                left=int(getattr(window, "left", 0)),
                top=int(getattr(window, "top", 0)),
                width=int(getattr(window, "width", 1)),
                height=int(getattr(window, "height", 1)),
            ),
        )

    def _find_and_activate_with_pywinauto(self) -> WindowInfo | None:
        try:
            from pywinauto import Desktop
        except Exception:
            return None

        try:
            windows = Desktop(backend="uia").windows()
        except Exception:
            return None

        for window in windows:
            title = (window.window_text() or "").strip()
            if not title or not self._compiled_pattern.search(title):
                continue
            try:
                if window.is_minimized():
                    window.restore()
                window.set_focus()
                rectangle = window.rectangle()
            except Exception:
                continue
            time.sleep(self.activation_wait_seconds)
            return WindowInfo(
                title=title,
                bounds=Bounds(
                    left=int(rectangle.left),
                    top=int(rectangle.top),
                    width=max(1, int(rectangle.width())),
                    height=max(1, int(rectangle.height())),
                ),
            )
        return None
