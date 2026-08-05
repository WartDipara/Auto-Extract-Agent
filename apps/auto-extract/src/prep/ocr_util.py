from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from paddleocr import PaddleOCR
from PIL import Image

_log = logging.getLogger(__name__)

_ocr_engine = None

# Downscale long edge before OCR — phone UI text stays readable, CPU much faster.
_OCR_MAX_SIDE = 960


@dataclass
class OcrItem:
    text: str
    cx: int
    cy: int
    scale: float = 1.0  # ocr_image / original (≤1)


def _get_engine():
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    _ocr_engine = PaddleOCR(
        lang="ch",
        ocr_version="PP-OCRv4",
        device="cpu",
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        text_det_limit_side_len=_OCR_MAX_SIDE,
        text_det_limit_type="max",
    )
    _log.info("PaddleOCR ready (PP-OCRv4 mobile, cpu, mkldnn=off)")
    return _ocr_engine


def _prepare_ocr_image(image_path: Path) -> tuple[Path, float, int, int]:
    """Return (path_for_ocr, scale, src_w, src_h) where scale = shrunk/original (≤1)."""
    with Image.open(image_path) as im:
        w, h = im.size
        long_side = max(w, h)
        if long_side <= _OCR_MAX_SIDE:
            return image_path, 1.0, w, h
        scale = _OCR_MAX_SIDE / float(long_side)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        out = Path(tempfile.mkstemp(prefix="ocr_s_", suffix=".png")[1])
        im.resize((nw, nh), Image.Resampling.BILINEAR).save(out)
        return out, scale, w, h


def _center_of_box(box) -> tuple[int, int]:
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    return int(sum(xs) / len(xs)), int(sum(ys) / len(ys))


def ocr_image(
    image_path: Path,
    *,
    device_w: int | None = None,
    device_h: int | None = None,
) -> list[OcrItem]:
    """
    Run OCR. If device_w/device_h given, map box centers into that tap space
    (screenshot pixels → adb input tap coordinates).
    """
    ocr_path, scale, src_w, src_h = _prepare_ocr_image(image_path)
    try:
        pages = list(_get_engine().predict(str(ocr_path)))
    finally:
        if ocr_path != image_path:
            try:
                ocr_path.unlink()
            except OSError:
                pass

    inv = 1.0 / scale if scale else 1.0
    sx = (float(device_w) / float(src_w)) if (device_w and src_w) else 1.0
    sy = (float(device_h) / float(src_h)) if (device_h and src_h) else 1.0

    items: list[OcrItem] = []
    for page in pages:
        texts = page.get("rec_texts") or []
        boxes = page.get("rec_polys") or page.get("dt_polys") or []
        for idx, text in enumerate(texts):
            cx = cy = 0
            if idx < len(boxes):
                cx, cy = _center_of_box(boxes[idx])
                # shrunk → original image pixels → tap space
                cx = int(cx * inv * sx)
                cy = int(cy * inv * sy)
            items.append(OcrItem(text=str(text), cx=cx, cy=cy, scale=scale))
    return items


def find_tap_for_texts(
    items: list[OcrItem], needles: tuple[str, ...]
) -> tuple[int, int] | None:
    """
    Prefer exact / short button labels over long body copy that contains the needle
    (e.g. button 同意 vs 详细阅读并同意). Among ties, prefer lower on screen.
    """
    for needle in needles:
        needle_l = needle.lower()
        candidates: list[tuple[int, int, int, int, OcrItem]] = []
        for item in items:
            text = (item.text or "").strip()
            if not text:
                continue
            text_l = text.lower()
            if needle_l not in text_l:
                continue
            if not (item.cx or item.cy):
                continue
            if text_l == needle_l:
                rank = 0
            elif text_l.startswith(needle_l) or text_l.endswith(needle_l):
                rank = 1
            else:
                rank = 2
            # shorter label first; then lower on screen (modal buttons)
            candidates.append((rank, len(text), -item.cy, -item.cx, item))
        if candidates:
            candidates.sort()
            best = candidates[0][4]
            return best.cx, best.cy
    return None


def texts_joined(items: list[OcrItem]) -> str:
    return "\n".join(i.text for i in items)
