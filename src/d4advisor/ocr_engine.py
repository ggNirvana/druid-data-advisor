from __future__ import annotations

import hashlib
import re
from importlib.metadata import version
from pathlib import Path

import numpy as np
from PIL import Image

from .ocr_parser import OCRLine


def _box_bounds(box: list[list[float]]) -> tuple[int, int, int, int]:
    xs = [point[0] for point in box]
    ys = [point[1] for point in box]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def _looks_like_explicit_affix(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(re.match(r"^[+xX×]?\d+(?:\.\d+)?%?(?:点|级)?.+", compact)) and "物品强度" not in compact


def _has_greater_affix_marker(image: np.ndarray, box: list[list[float]]) -> bool:
    x0, y0, _, y1 = _box_bounds(box)
    marker_region = image[max(0, y0 - 3) : y1 + 4, max(0, x0 - 35) : max(0, x0 - 2)]
    if marker_region.size == 0:
        return False
    bright_warm_pixels = (
        (marker_region[:, :, 0] > 170)
        & (marker_region[:, :, 1] > 90)
        & (marker_region[:, :, 2] > 70)
    )
    return int(bright_warm_pixels.sum()) >= 15


def recognize_item_image(image_path: str | Path) -> tuple[list[OCRLine], dict[str, object]]:
    """Run local OCR and annotate item-panel membership and GA markers."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "RapidOCR is not installed. Run `scripts/setup-local.sh` first."
        ) from exc

    image_path = Path(image_path)
    image = np.asarray(Image.open(image_path).convert("RGB"))
    result, elapsed = RapidOCR()(str(image_path))
    result = result or []

    anchor_left_edges = []
    for box, text, _ in result:
        if "物品强度" in text or any(label in text for label in ("传奇", "暗金", "神话", "稀有")):
            anchor_left_edges.append(_box_bounds(box)[0])
    panel_text_left = min(anchor_left_edges, default=int(image.shape[1] * 0.20))
    panel_cutoff = max(0, panel_text_left - 35)

    lines: list[OCRLine] = []
    for box, text, confidence in result:
        x0, _, x1, _ = _box_bounds(box)
        in_item_panel = x1 >= panel_cutoff and x0 >= panel_cutoff
        has_marker = (
            in_item_panel
            and _looks_like_explicit_affix(text)
            and _has_greater_affix_marker(image, box)
        )
        lines.append(
            OCRLine(
                text=text,
                confidence=float(confidence),
                box=tuple(tuple(float(value) for value in point) for point in box),
                in_item_panel=in_item_panel,
                has_greater_affix_marker=has_marker,
            )
        )

    metadata = {
        "engine": "rapidocr_onnxruntime",
        "engine_version": version("rapidocr_onnxruntime"),
        "panel_text_left": panel_text_left,
        "panel_cutoff": panel_cutoff,
        "elapsed_seconds": elapsed,
        "image_width": int(image.shape[1]),
        "image_height": int(image.shape[0]),
        "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
    }
    return lines, metadata
