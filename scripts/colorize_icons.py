"""Convert black-on-white line-art icons into the neon-on-transparent icon set.

The `icon_v2_*` assets are neon glyphs on a transparent background. A few
subparts (power generation, coal, chemical, cement) only ever had legacy
black-on-white JPGs, which are invisible against the dark map and are not
present in `geo-icons/small`. This utility renders those sources in the same
style so every subpart in `config.yml` resolves to a real icon file.

Usage:
    python -m scripts.colorize_icons
    python -m scripts.colorize_icons --source geo-icons/old/power.jpg \
        --name icon_v2_D --color "#ffffff"
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

# source file -> (output icon name, neon colour) for the subparts that had no
# icon_v2 asset. Colours are chosen to stay distinct from the existing set.
DEFAULT_ICONS: dict[str, tuple[str, str]] = {
    "power.jpg": ("icon_v2_D", "#ffffff"),
    "coal.jpg": ("icon_v2_FF", "#9aa7b4"),
    "chemical.jpg": ("icon_v2_G_PP", "#00ffd5"),
    "cement.jpg": ("icon_v2_H", "#ffa64d"),
}

# Luminance range mapped to alpha: ink darker than INK_MAX is fully opaque,
# paper brighter than PAPER_MIN is fully transparent, edges ramp between.
INK_MAX = 90.0
PAPER_MIN = 235.0


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"Colour must be a 6-digit hex string, got: {value!r}")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def colorize(source: Path, color: str) -> Image.Image:
    """Return a transparent RGBA glyph: dark ink becomes `color`, paper becomes alpha 0."""
    luminance = np.asarray(Image.open(source).convert("L"), dtype=np.float32)
    alpha = np.clip((PAPER_MIN - luminance) / (PAPER_MIN - INK_MAX), 0.0, 1.0)

    red, green, blue = _hex_to_rgb(color)
    rgba = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    rgba[..., 0] = red
    rgba[..., 1] = green
    rgba[..., 2] = blue
    rgba[..., 3] = np.round(alpha * 255).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")


def _write(image: Image.Image, path: Path, size_px: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = image
    if size_px is not None and max(image.size) > size_px:
        scale = size_px / max(image.size)
        out = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.LANCZOS,
        )
    out.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Colorize legacy line-art icons")
    parser.add_argument("--source", help="Single source image (defaults to the built-in set)")
    parser.add_argument("--name", help="Output icon name (without extension)")
    parser.add_argument("--color", help="Neon hex colour for --source")
    parser.add_argument("--source-dir", default="geo-icons/old")
    parser.add_argument("--original-dir", default="geo-icons/original")
    parser.add_argument("--small-dir", default="geo-icons/small")
    parser.add_argument("--small-size-px", type=int, default=100)
    args = parser.parse_args()

    if args.source:
        if not (args.name and args.color):
            parser.error("--source requires --name and --color")
        jobs = {Path(args.source).name: (args.name, args.color)}
        source_dir = Path(args.source).parent
    else:
        jobs = DEFAULT_ICONS
        source_dir = Path(args.source_dir)

    written = 0
    for filename, (name, color) in jobs.items():
        source = source_dir / filename
        if not source.exists():
            raise FileNotFoundError(f"Source icon not found: {source}")
        glyph = colorize(source, color)
        _write(glyph, Path(args.original_dir) / f"{name}.png", size_px=None)
        _write(glyph, Path(args.small_dir) / f"{name}.png", size_px=args.small_size_px)
        print(f"[OK] {source} -> {name}.png ({color})")
        written += 1

    print(f"[OK] Wrote {written} icons.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
