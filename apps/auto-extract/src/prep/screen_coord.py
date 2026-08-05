from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from prep.adb_device import AdbDevice

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScreenCoordSpace:
    tap_w: int
    tap_h: int
    src_w: int
    src_h: int
    rotation: int
    is_landscape: bool
    aspect_corrected: bool


def _read_image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return int(im.size[0]), int(im.size[1])


def resolve_screen_coord_space(
    adb: AdbDevice,
    screenshot_path: Path | str,
    *,
    rotation: int | None = None,
) -> ScreenCoordSpace:
    """
    Align tap space to screenshot orientation.

    Uses touch_size (wm size + rotation). If screenshot landscape/portrait
    disagrees with touch, swap tap W/H (same contract as android-ai-driven-test).
    """
    path = Path(screenshot_path)
    tap_w, tap_h = adb.touch_size()
    rot = rotation if rotation is not None else adb.get_screen_rotation()
    src_w, src_h = _read_image_size(path)

    src_landscape = src_w > src_h
    tap_landscape = tap_w > tap_h
    aspect_corrected = False
    if src_landscape != tap_landscape:
        tap_w, tap_h = tap_h, tap_w
        aspect_corrected = True

    space = ScreenCoordSpace(
        tap_w=tap_w,
        tap_h=tap_h,
        src_w=src_w,
        src_h=src_h,
        rotation=rot,
        is_landscape=src_landscape,
        aspect_corrected=aspect_corrected,
    )
    _log.info(
        "screen coord src=%dx%d tap=%dx%d rot=%d landscape=%s corrected=%s",
        src_w,
        src_h,
        tap_w,
        tap_h,
        rot,
        src_landscape,
        aspect_corrected,
    )
    return space
