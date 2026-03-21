"""CLI entrypoint for the VA GHG dashboard map render."""

from __future__ import annotations

import argparse

from scripts.config import load_yaml_config, validate_config
from scripts.build_deck import build_deck_assets
from scripts.render import render_map


def main() -> int:
    parser = argparse.ArgumentParser(description="Build VA GHG dashboard artifacts")
    parser.add_argument("--config", default="config.yml", help="Path to YAML config")
    parser.add_argument(
        "--target",
        choices=["png", "deck"],
        default="png",
        help="Build target: static PNG render or deck.gl web assets",
    )
    args = parser.parse_args()

    try:
        cfg = load_yaml_config(args.config)
        validate_config(cfg)
        print(f"[OK] Loaded and validated config: {args.config}")

        if args.target == "png":
            output_path = render_map(cfg)
            print(f"[OK] Rendered map: {output_path}")
        else:
            output_path = build_deck_assets(cfg)
            print(f"[OK] Prepared deck.gl assets: {output_path}")

        print("[OK] Build finished.")
        return 0
    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"[ERR] Build failed: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
