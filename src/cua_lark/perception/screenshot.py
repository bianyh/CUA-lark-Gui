from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageGrab


MAX_SCREENSHOT_PIXELS = 80_000_000
MAX_SCREENSHOT_SIDE = 20_000


class Screenshotter:
    def __init__(self, mock_mode: bool = False, mock_size: tuple[int, int] = (1440, 900)) -> None:
        self.mock_mode = mock_mode
        self.mock_size = mock_size

    def capture(
        self,
        output_path: Path,
        overlay_lines: Sequence[str] | None = None,
        region: tuple[int, int, int, int] | None = None,
    ) -> tuple[Path, tuple[int, int], str]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.mock_mode:
            size = (region[2], region[3]) if region is not None else self.mock_size
            image = Image.new("RGB", size, color=(245, 247, 250))
            draw = ImageDraw.Draw(image)
            lines = list(overlay_lines or [])
            lines.insert(0, "CUA-Lark mock screenshot")
            lines.insert(1, datetime.now(UTC).isoformat())
            for index, line in enumerate(lines):
                draw.text((24, 24 + index * 28), line, fill=(26, 32, 44))
            image.save(output_path)
            return output_path, image.size, "mock"

        if region is not None:
            left, top, width, height = region
            self._validate_capture_size(width, height)
            image = ImageGrab.grab(bbox=(left, top, left + width, top + height))
            image.save(output_path)
            return output_path, image.size, "window"

        image = ImageGrab.grab(all_screens=True)
        self._validate_capture_size(*image.size)
        image.save(output_path)
        return output_path, image.size, "full_screen"

    def _validate_capture_size(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise RuntimeError(f"Invalid screenshot size: {width}x{height}.")
        if width > MAX_SCREENSHOT_SIDE or height > MAX_SCREENSHOT_SIDE:
            raise RuntimeError(
                "Screenshot region is too large: "
                f"{width}x{height}. This usually means an invalid desktop window region was detected."
            )
        pixels = width * height
        if pixels > MAX_SCREENSHOT_PIXELS:
            raise RuntimeError(
                "Screenshot region is too large: "
                f"{width}x{height} ({pixels} pixels). "
                "This usually means an invalid desktop window region was detected."
            )
