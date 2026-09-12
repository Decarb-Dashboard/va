"""Create small icon variants for map rendering.

This script is intentionally separate from the render pipeline so icon resizing
is an explicit pre-processing step.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np


DEFAULT_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg", "*.webp")


def _resize_nearest(image: np.ndarray, max_size_px: int) -> np.ndarray:
    """Resize an image to fit within max_size_px using nearest-neighbor sampling."""
    src_h, src_w = image.shape[:2]
    scale = min(max_size_px / src_w, max_size_px / src_h, 1.0)

    dst_w = max(1, int(round(src_w * scale)))
    dst_h = max(1, int(round(src_h * scale)))

    y_idx = np.linspace(0, src_h - 1, dst_h).astype(int)
    x_idx = np.linspace(0, src_w - 1, dst_w).astype(int)
    return image[np.ix_(y_idx, x_idx)]


def resize_icons(input_dir: Path, output_dir: Path, max_size_px: int) -> int:
    """Resize all icons to fit inside max_size_px while preserving aspect ratio."""
    output_dir.mkdir(parents=True, exist_ok=True)

    icon_paths: list[Path] = []
    for pattern in DEFAULT_EXTENSIONS:
        icon_paths.extend(sorted(input_dir.rglob(pattern)))

    processed = 0
    for icon_path in icon_paths:
        image = mpimg.imread(icon_path)
        resized = _resize_nearest(image, max_size_px=max_size_px)
        out_path = output_dir / icon_path.name
        mpimg.imsave(out_path, resized)
        processed += 1

    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate small icon versions for map labels")
    parser.add_argument(
        "--input-dir",
        default="geo-icons/original",
        help="Directory containing source icons",
    )
    parser.add_argument(
        "--output-dir",
        default="geo-icons/small",
        help="Directory to write resized icon files",
    )
    parser.add_argument(
        "--max-size-px",
        type=int,
        default=50,
        help="Maximum width/height (pixels) for resized icons",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input icon directory not found: {input_dir}")

    count = resize_icons(input_dir=input_dir, output_dir=output_dir, max_size_px=args.max_size_px)
    print(f"[OK] Wrote {count} resized icons to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
