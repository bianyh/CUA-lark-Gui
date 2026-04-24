from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageGrab


class Screenshotter:
    def __init__(self, mock_mode: bool = False, mock_size: tuple[int, int] = (1440, 900)) -> None:
        self.mock_mode = mock_mode
        self.mock_size = mock_size

    def capture(self, output_path: Path, overlay_lines: Sequence[str] | None = None) -> tuple[Path, tuple[int, int]]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.mock_mode:
            image = Image.new("RGB", self.mock_size, color=(245, 247, 250))
            draw = ImageDraw.Draw(image)
            lines = list(overlay_lines or [])
            lines.insert(0, "CUA-Lark mock screenshot")
            lines.insert(1, datetime.now(UTC).isoformat())
            for index, line in enumerate(lines):
                draw.text((24, 24 + index * 28), line, fill=(26, 32, 44))
            image.save(output_path)
            return output_path, image.size

        image = ImageGrab.grab(all_screens=True)
        image.save(output_path)
        return output_path, image.size
