from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from cua_lark.models import ActionStep


class DesktopExecutor(ABC):
    backend_name = "executor"

    @abstractmethod
    def execute(self, step: ActionStep) -> dict[str, Any]:
        raise NotImplementedError

    def focus_window(self, keyword: str) -> bool:
        return False

    def snapshot_state(self) -> dict[str, Any]:
        return {}

    def configure_window_handoff(self, metadata: dict[str, Any]) -> None:
        return None

    def refresh_window_context(self, wait_seconds: float = 0.0) -> dict[str, Any] | None:
        return None

    def reset(self) -> None:
        return None

    def capture_region(self) -> tuple[int, int, int, int] | None:
        return None
