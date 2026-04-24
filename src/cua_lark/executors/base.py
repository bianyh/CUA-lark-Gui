from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from cua_lark.models import ActionStep


class DesktopExecutor(ABC):
    @abstractmethod
    def execute(self, step: ActionStep) -> dict[str, Any]:
        raise NotImplementedError

    def focus_window(self, keyword: str) -> bool:
        return False

    def snapshot_state(self) -> dict[str, Any]:
        return {}

