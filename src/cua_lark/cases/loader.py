from __future__ import annotations

import json
from pathlib import Path

import yaml

from cua_lark.models import TaskSpec


def load_task_spec(path: Path) -> TaskSpec:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw)
    task = TaskSpec.from_dict(data)
    task.metadata.setdefault("source_path", str(path))
    return task


def discover_case_files(base_dir: Path) -> list[Path]:
    candidates = list(base_dir.rglob("*.yaml")) + list(base_dir.rglob("*.yml")) + list(base_dir.rglob("*.json"))
    return sorted(candidates)


def load_case_directory(base_dir: Path) -> list[TaskSpec]:
    return [load_task_spec(path) for path in discover_case_files(base_dir)]

