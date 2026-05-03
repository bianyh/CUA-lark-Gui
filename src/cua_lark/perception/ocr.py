from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from importlib import util as importlib_util
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from cua_lark.models import BoundingBox, OCRBlock


class OCRProvider(ABC):
    backend_name = "unknown"

    @abstractmethod
    def extract(self, image_path: Path) -> list[OCRBlock]:
        raise NotImplementedError

    @property
    def status_message(self) -> str:
        return "ready"


class NullOCRProvider(OCRProvider):
    backend_name = "none"

    def __init__(self, reason: str = "OCR 已禁用。") -> None:
        self.reason = reason

    def extract(self, image_path: Path) -> list[OCRBlock]:
        return []

    @property
    def status_message(self) -> str:
        return self.reason


class PaddleOCRProvider(OCRProvider):
    backend_name = "paddleocr"

    def __init__(
        self,
        language: str = "ch",
        use_textline_orientation: bool = True,
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
    ) -> None:
        self.language = language
        self.use_textline_orientation = use_textline_orientation
        self.use_doc_orientation_classify = use_doc_orientation_classify
        self.use_doc_unwarping = use_doc_unwarping
        self._engine: Any | None = None
        self._status_message = "ready"

    def extract(self, image_path: Path) -> list[OCRBlock]:
        engine = self._get_engine()
        raw_results = engine.predict(str(image_path))
        return self._parse_blocks(raw_results)

    @property
    def status_message(self) -> str:
        return self._status_message

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as exc:
            self._status_message = f"PaddleOCR 导入失败：{exc}"
            raise RuntimeError(
                "PaddleOCR 不可用，请先安装兼容的 PaddleOCR 运行环境。"
            ) from exc
        except Exception as exc:
            self._status_message = f"PaddleOCR 导入失败：{exc}"
            raise RuntimeError(
                f"PaddleOCR 导入失败。常见原因是 NumPy 或其他已编译依赖不兼容。详情：{exc}"
            ) from exc

        self._engine = PaddleOCR(
            lang=self.language,
            use_textline_orientation=self.use_textline_orientation,
            use_doc_orientation_classify=self.use_doc_orientation_classify,
            use_doc_unwarping=self.use_doc_unwarping,
        )
        self._status_message = "ready"
        return self._engine

    def _parse_blocks(self, raw_results: Any) -> list[OCRBlock]:
        if raw_results is None:
            return []
        if not isinstance(raw_results, list):
            try:
                raw_results = list(raw_results)
            except TypeError:
                raw_results = [raw_results]

        blocks: list[OCRBlock] = []
        for item in raw_results:
            normalized = self._normalize_result_item(item)
            texts = self._to_list(normalized.get("rec_texts"))
            scores = self._to_list(normalized.get("rec_scores"))
            boxes = self._to_list(
                self._first_present(normalized, ("rec_boxes", "rec_polys", "dt_polys"))
            )
            max_len = max(len(texts), len(scores), len(boxes))
            for index in range(max_len):
                text = str(texts[index]).strip() if index < len(texts) else ""
                if not text:
                    continue
                score = float(scores[index]) if index < len(scores) and scores[index] is not None else 0.0
                bbox = self._bbox_from_any(boxes[index]) if index < len(boxes) else None
                blocks.append(OCRBlock(text=text, confidence=score, bbox=bbox))
        return blocks

    def _first_present(self, data: Mapping[str, Any], keys: Sequence[str]) -> Any:
        for key in keys:
            value = data.get(key)
            if value is not None:
                return value
        return None

    def _normalize_result_item(self, item: Any) -> dict[str, Any]:
        if isinstance(item, Mapping):
            return dict(item)

        json_view = getattr(item, "json", None)
        if isinstance(json_view, Mapping):
            if isinstance(json_view.get("res"), Mapping):
                return dict(json_view["res"])
            return dict(json_view)

        if hasattr(item, "keys"):
            try:
                return {key: item[key] for key in item.keys()}
            except Exception:
                pass

        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            return {"rec_texts": list(item)}

        return {}

    def _to_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        return [value]

    def _bbox_from_any(self, value: Any) -> BoundingBox | None:
        if value is None:
            return None
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, Sequence) and len(value) == 4 and all(
            isinstance(item, (int, float)) for item in value
        ):
            x1, y1, x2, y2 = value
            return BoundingBox(
                x=int(min(x1, x2)),
                y=int(min(y1, y2)),
                width=max(1, int(abs(x2 - x1))),
                height=max(1, int(abs(y2 - y1))),
            )

        if isinstance(value, Sequence) and value:
            points: list[tuple[float, float]] = []
            for point in value:
                if hasattr(point, "tolist"):
                    point = point.tolist()
                if isinstance(point, Sequence) and len(point) >= 2:
                    try:
                        points.append((float(point[0]), float(point[1])))
                    except (TypeError, ValueError):
                        continue
            if points:
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                return BoundingBox(
                    x=int(min(xs)),
                    y=int(min(ys)),
                    width=max(1, int(max(xs) - min(xs))),
                    height=max(1, int(max(ys) - min(ys))),
                )
        return None


def paddleocr_diagnostics() -> dict[str, Any]:
    package_found = importlib_util.find_spec("paddleocr") is not None
    try:
        package_version = version("paddleocr")
    except PackageNotFoundError:
        package_version = None

    diagnostics: dict[str, Any] = {
        "package_found": package_found,
        "package_version": package_version,
        "importable": False,
        "error": None,
    }
    if not package_found:
        diagnostics["error"] = "未找到 paddleocr 包"
        return diagnostics

    probe_script = """
import json
data = {"importable": False, "class_name": None, "error": None}
try:
    from paddleocr import PaddleOCR
    data["importable"] = True
    data["class_name"] = PaddleOCR.__name__
except Exception as exc:
    data["error"] = str(exc)
print(json.dumps(data, ensure_ascii=False))
""".strip()

    try:
        result = subprocess.run(
            [sys.executable, "-c", probe_script],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
        probe = json.loads(payload)
        diagnostics["importable"] = bool(probe.get("importable"))
        diagnostics["class_name"] = probe.get("class_name")
        diagnostics["error"] = probe.get("error")
        if not diagnostics["importable"] and result.stderr.strip():
            diagnostics["stderr_tail"] = result.stderr.strip().splitlines()[-1]
    except Exception as exc:
        diagnostics["error"] = str(exc)
    return diagnostics
