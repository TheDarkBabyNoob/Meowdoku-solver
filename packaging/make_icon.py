#!/usr/bin/env python3
"""Generate the Meowdoku Companion macOS app icon from simple shapes."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print(
        "Error: Pillow is required to generate the app icon.\n"
        "Run packaging/build_app.sh so it can install Pillow into the project .venv, "
        "or install it manually with .venv/bin/python -m pip install Pillow.",
        file=sys.stderr,
    )
    sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent
PACKAGING_DIR = ROOT / "packaging"
BASE_ICON = PACKAGING_DIR / "icon_1024.png"
ICONSET_DIR = PACKAGING_DIR / "AppIcon.iconset"
ICNS_FILE = PACKAGING_DIR / "AppIcon.icns"
SIZE = 1024

ICONSET_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def gradient_background(size: int) -> Image.Image:
    top = (135, 105, 218)
    bottom = (242, 166, 90)
    image = Image.new("RGBA", (size, size))
    pixels = image.load()

    for y in range(size):
        t = y / (size - 1)
        row = tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        for x in range(size):
            warm_shift = int(18 * (x / (size - 1)) * (1 - t))
            pixels[x, y] = (
                min(row[0] + warm_shift, 255),
                min(row[1] + warm_shift // 2, 255),
                row[2],
                255,
            )

    image.putalpha(rounded_mask(size, 220))
    return image


def draw_grid(draw: ImageDraw.ImageDraw) -> None:
    left, top, right, bottom = 166, 166, 858, 858
    line = (255, 255, 255, 72)
    width = 18

    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=72,
        outline=(255, 255, 255, 58),
        width=16,
    )
    draw.line((SIZE // 2, top + 10, SIZE // 2, bottom - 10), fill=line, width=width)
    draw.line((left + 10, SIZE // 2, right - 10, SIZE // 2), fill=line, width=width)


def draw_cat(draw: ImageDraw.ImageDraw) -> None:
    dark = (45, 37, 52, 255)
    shadow = (45, 37, 52, 42)
    eye = (255, 247, 225, 255)
    nose = (245, 139, 142, 255)

    draw.ellipse((287, 703, 737, 785), fill=shadow)
    draw.polygon([(308, 407), (383, 212), (489, 403)], fill=dark)
    draw.polygon([(535, 403), (641, 212), (716, 407)], fill=dark)
    draw.ellipse((258, 312, 766, 810), fill=dark)

    draw.polygon([(362, 392), (391, 302), (452, 406)], fill=(96, 71, 101, 255))
    draw.polygon([(572, 406), (633, 302), (662, 392)], fill=(96, 71, 101, 255))

    draw.ellipse((390, 518, 446, 596), fill=eye)
    draw.ellipse((578, 518, 634, 596), fill=eye)
    draw.polygon([(512, 614), (469, 574), (555, 574)], fill=nose)


def create_base_icon() -> Image.Image:
    image = gradient_background(SIZE)
    draw = ImageDraw.Draw(image, "RGBA")
    draw_grid(draw)
    draw_cat(draw)
    return image


def save_iconset(base: Image.Image) -> None:
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in ICONSET_SIZES.items():
        resized = base.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(ICONSET_DIR / name)


def run_iconutil() -> None:
    iconutil = shutil.which("iconutil")
    if not iconutil:
        print(
            "Error: iconutil was not found. This command is built into macOS and is "
            "required to create packaging/AppIcon.icns.",
            file=sys.stderr,
        )
        sys.exit(1)

    result = subprocess.run(
        [iconutil, "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_FILE)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print("Error: iconutil failed to create packaging/AppIcon.icns.", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        elif result.stdout.strip():
            print(result.stdout.strip(), file=sys.stderr)
        sys.exit(result.returncode)


def main() -> int:
    PACKAGING_DIR.mkdir(parents=True, exist_ok=True)
    base = create_base_icon()
    base.save(BASE_ICON)
    save_iconset(base)
    run_iconutil()
    print(f"Generated {BASE_ICON.relative_to(ROOT)}")
    print(f"Generated {ICONSET_DIR.relative_to(ROOT)}")
    print(f"Generated {ICNS_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
