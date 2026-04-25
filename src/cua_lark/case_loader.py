from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import TestCase


def load_yaml(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def load_case(path: str | Path) -> TestCase:
    return TestCase(**load_yaml(path))


def load_suite(path: str | Path) -> list[Path]:
    suite_path = Path(path)
    data = load_yaml(suite_path)
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError(f"{path} must contain a non-empty 'cases' list")
    return [(suite_path.parent / case_path).resolve() for case_path in raw_cases]
