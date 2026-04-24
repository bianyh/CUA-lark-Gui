from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def load_dotenv_if_present(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        cleaned = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), cleaned)


@dataclass(slots=True)
class Settings:
    repo_root: Path
    artifact_root: Path
    report_root: Path
    openai_api_key: str | None
    openai_base_url: str = "https://api.chattoken.cc/v1"
    openai_model: str = "gpt-4o"
    provider_mode: str = "responses"
    window_title_keyword: str = "飞书"
    max_steps: int = 15
    max_retries: int = 2
    mock_mode: bool = False
    ocr_backend: str = "paddleocr"
    paddleocr_lang: str = "ch"
    runtime_logs: bool = True
    runtime_preview_chars: int = 80

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "Settings":
        root = repo_root or Path.cwd()
        load_dotenv_if_present(root / ".env")
        load_dotenv_if_present(root / ".env.local")
        return cls(
            repo_root=root,
            artifact_root=root / "artifacts",
            report_root=root / "reports" / "generated",
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.chattoken.cc/v1"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            provider_mode=os.getenv("CUA_PROVIDER_MODE", "responses"),
            window_title_keyword=os.getenv("CUA_WINDOW_TITLE_KEYWORD", "飞书"),
            max_steps=_parse_int(os.getenv("CUA_MAX_STEPS"), 15),
            max_retries=_parse_int(os.getenv("CUA_MAX_RETRIES"), 2),
            mock_mode=_parse_bool(os.getenv("CUA_MOCK_MODE"), False),
            ocr_backend=os.getenv("CUA_OCR_BACKEND", "paddleocr"),
            paddleocr_lang=os.getenv("CUA_PADDLE_OCR_LANG", "ch"),
            runtime_logs=_parse_bool(os.getenv("CUA_RUNTIME_LOGS"), True),
            runtime_preview_chars=_parse_int(os.getenv("CUA_RUNTIME_PREVIEW_CHARS"), 80),
        )

    def ensure_runtime_dirs(self) -> None:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.report_root.mkdir(parents=True, exist_ok=True)

    def with_mock_mode(self, mock_mode: bool) -> "Settings":
        return replace(self, mock_mode=mock_mode)
