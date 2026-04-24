from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


def encode_image_as_data_url(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".") or "png"
    payload = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:image/{suffix};base64,{payload}"


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

