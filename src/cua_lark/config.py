from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional import guard
    load_dotenv = None


DEFAULT_PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    openai_base_url: str = "https://api.chattoken.cc/"
    openai_model: str = "gpt-4o"
    openai_api_key: str | None = None
    runs_dir: Path = Path("runs")
    min_action_confidence: float = 0.55
    max_recovery_attempts: int = 2
    require_confirmation_for_risky: bool = True

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> "Settings":
        if load_dotenv is not None and env_file is not None:
            load_dotenv(env_file)

        return cls(
            openai_base_url=os.getenv("OPENAI_BASE_URL", cls.openai_base_url),
            openai_model=os.getenv("OPENAI_MODEL", cls.openai_model),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            runs_dir=Path(os.getenv("CUA_LARK_RUNS_DIR", str(cls.runs_dir))),
            min_action_confidence=float(
                os.getenv("CUA_LARK_MIN_ACTION_CONFIDENCE", cls.min_action_confidence)
            ),
            max_recovery_attempts=int(
                os.getenv("CUA_LARK_MAX_RECOVERY_ATTEMPTS", cls.max_recovery_attempts)
            ),
            require_confirmation_for_risky=_as_bool(
                os.getenv("CUA_LARK_REQUIRE_CONFIRMATION_FOR_RISKY"),
                cls.require_confirmation_for_risky,
            ),
        )

    @property
    def has_api_key(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())

    @property
    def redacted_api_key(self) -> str:
        if not self.openai_api_key:
            return "<missing>"
        key = self.openai_api_key
        if len(key) <= 10:
            return "<redacted>"
        return f"{key[:5]}...{key[-4:]}"

    def normalized_base_url_candidates(self) -> list[str]:
        base = self.openai_base_url.rstrip("/")
        candidates = [self.openai_base_url]
        if not base.endswith("/v1"):
            candidates.append(f"{base}/v1")
        return candidates
