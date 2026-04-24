from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image

from cua_lark.models import BoundingBox, OCRBlock


class OCRProvider(ABC):
    @abstractmethod
    def extract(self, image_path: Path) -> list[OCRBlock]:
        raise NotImplementedError


class NullOCRProvider(OCRProvider):
    def extract(self, image_path: Path) -> list[OCRBlock]:
        return []


class TesseractOCRProvider(OCRProvider):
    def __init__(self, language: str = "chi_sim+eng") -> None:
        try:
            import pytesseract  # type: ignore
            from pytesseract import Output  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pytesseract is not installed. Install the desktop extras first.") from exc

        self._pytesseract = pytesseract
        self._output_type = Output
        self.language = language

    def extract(self, image_path: Path) -> list[OCRBlock]:
        image = Image.open(image_path)
        result = self._pytesseract.image_to_data(
            image,
            output_type=self._output_type.DICT,
            lang=self.language,
        )
        blocks: list[OCRBlock] = []
        total = len(result.get("text", []))
        for index in range(total):
            text = str(result["text"][index]).strip()
            if not text:
                continue
            confidence = float(result["conf"][index]) if str(result["conf"][index]).strip() else 0.0
            bbox = BoundingBox(
                x=int(result["left"][index]),
                y=int(result["top"][index]),
                width=int(result["width"][index]),
                height=int(result["height"][index]),
            )
            blocks.append(OCRBlock(text=text, confidence=confidence, bbox=bbox))
        return blocks

