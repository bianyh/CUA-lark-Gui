from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


def encode_image_as_data_url(
    path: Path,
    *,
    max_side: int | None = None,
    jpeg_quality: int = 75,
) -> str:
    image = Image.open(path)
    image.load()
    image = image.convert("RGB")

    if max_side and max(image.size) > max_side:
        ratio = max_side / float(max(image.size))
        resized = (
            max(1, int(image.size[0] * ratio)),
            max(1, int(image.size[1] * ratio)),
        )
        image = image.resize(resized)

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
    payload = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{payload}"


def compare_images(path_a: Path, path_b: Path) -> dict[str, float]:
    image_a = Image.open(path_a).convert("RGB")
    image_b = Image.open(path_b).convert("RGB")
    if image_a.size != image_b.size:
        image_b = image_b.resize(image_a.size)
    diff = ImageChops.difference(image_a, image_b)
    stats = ImageStat.Stat(diff)
    mean_delta = sum(stats.mean) / len(stats.mean)
    normalized = mean_delta / 255.0
    return {
        "difference": normalized,
        "similarity": max(0.0, 1.0 - normalized),
    }
