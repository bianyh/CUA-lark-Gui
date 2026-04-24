from __future__ import annotations

from typing import Any

from cua_lark.executors.base import DesktopExecutor
from cua_lark.models import ActionStep


class MockDesktopExecutor(DesktopExecutor):
    def __init__(self) -> None:
        self._state: dict[str, Any] = {
            "visible_texts": [],
            "typed_texts": [],
            "sent_messages": [],
            "last_typed_text": "",
            "last_hotkey": [],
            "focused_window": "",
        }

    def focus_window(self, keyword: str) -> bool:
        self._state["focused_window"] = keyword
        self._add_visible_text(keyword)
        return True

    def execute(self, step: ActionStep) -> dict[str, Any]:
        meta: dict[str, Any] = {"mode": "mock", "action_type": step.action_type}
        if step.action_type == "type_text":
            typed = step.text or ""
            self._state["typed_texts"].append(typed)
            self._state["last_typed_text"] = typed
            self._add_visible_text(typed)
        elif step.action_type == "hotkey":
            self._state["last_hotkey"] = list(step.hotkey)
            lowered = [item.lower() for item in step.hotkey]
            if lowered == ["ctrl", "k"]:
                self._add_visible_text("搜索")
            if lowered == ["ctrl", "2"]:
                self._add_visible_text("日历")
            if lowered == ["enter"] or lowered == ["return"]:
                if self._state["last_typed_text"]:
                    self._state["sent_messages"].append(self._state["last_typed_text"])
                    self._add_visible_text(self._state["last_typed_text"])
        elif step.action_type == "scroll":
            meta["scroll_amount"] = step.scroll_amount
        elif step.action_type == "wait":
            meta["wait_seconds"] = step.wait_seconds

        if step.validation_hint:
            self._add_visible_text(step.validation_hint)

        return meta

    def snapshot_state(self) -> dict[str, Any]:
        return {
            "visible_texts": list(self._state["visible_texts"]),
            "typed_texts": list(self._state["typed_texts"]),
            "sent_messages": list(self._state["sent_messages"]),
            "last_hotkey": list(self._state["last_hotkey"]),
            "focused_window": str(self._state["focused_window"]),
        }

    def _add_visible_text(self, value: str) -> None:
        if value and value not in self._state["visible_texts"]:
            self._state["visible_texts"].append(value)

