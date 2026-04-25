from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from .config import Settings


class VLMError(RuntimeError):
    """Raised when the VLM client cannot return valid structured output."""


def extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise VLMError("Model response did not contain a JSON object")
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise VLMError("Model response JSON must be an object")
    return parsed


def image_to_data_url(path: str | Path) -> str:
    image_path = Path(path)
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
    payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


class VLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._clients: dict[str, Any] = {}

    def client(self, base_url: str):
        if base_url not in self._clients:
            if not self.settings.has_api_key:
                raise VLMError("OPENAI_API_KEY is missing")
            try:
                from openai import OpenAI
            except Exception as exc:  # pragma: no cover - import guard
                raise VLMError("The openai package is not installed") from exc

            self._clients[base_url] = OpenAI(
                api_key=self.settings.openai_api_key,
                base_url=base_url,
            )
        return self._clients[base_url]

    def complete_json(
        self,
        prompt: str,
        *,
        images: list[str | Path] | None = None,
        system_prompt: str | None = None,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        user_content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images or []:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": image_to_data_url(image)},
                }
            )

        last_error: Exception | None = None
        for base_url in self.settings.normalized_base_url_candidates():
            try:
                response = self.client(base_url).chat.completions.create(
                    model=self.settings.openai_model,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt
                            or "You are a GUI testing agent. Return one valid JSON object only.",
                        },
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                content = self._extract_response_content(response)
                return extract_json_object(content)
            except Exception as exc:
                last_error = exc
                if not self._should_try_next_candidate(exc):
                    break
        raise VLMError(str(last_error) if last_error else "VLM request failed")

    @staticmethod
    def _extract_response_content(response: Any) -> str:
        if hasattr(response, "choices"):
            content = response.choices[0].message.content
            return content or "{}"
        if isinstance(response, dict):
            choices = response.get("choices")
            if isinstance(choices, list) and choices:
                message = choices[0].get("message", {})
                content = message.get("content", "{}")
                return str(content)
        if isinstance(response, str):
            stripped = response.lstrip()
            if stripped.startswith("<!doctype html") or stripped.startswith("<html"):
                raise VLMError("Gateway returned HTML instead of an OpenAI chat completion payload")
            return response
        raise VLMError(f"Unsupported VLM response type: {type(response)!r}")

    @staticmethod
    def _should_try_next_candidate(exc: Exception) -> bool:
        message = str(exc).lower()
        return "html" in message or "404" in message or "not found" in message


class ReplayVLMClient:
    """Deterministic VLM client for tests and dry-run demos."""

    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        prompt: str,
        *,
        images: list[str | Path] | None = None,
        system_prompt: str | None = None,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "prompt": prompt,
                "images": [str(image) for image in images or []],
                "system_prompt": system_prompt,
                "max_tokens": max_tokens,
            }
        )
        if not self.responses:
            raise VLMError("ReplayVLMClient has no responses left")
        return self.responses.pop(0)
