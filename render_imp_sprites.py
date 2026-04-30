#!/usr/bin/env python3
"""Render Imp Zero sprite frames without WhisPlay hardware attached."""

from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path


def _install_test_stubs() -> None:
    whis = types.ModuleType("WhisPlay")

    class WhisPlayBoard:
        LCD_WIDTH = 240
        LCD_HEIGHT = 240

        def set_backlight(self, *_args):
            pass

        def draw_image(self, *_args):
            pass

    whis.WhisPlayBoard = WhisPlayBoard
    sys.modules.setdefault("WhisPlay", whis)

    if "dotenv" not in sys.modules:
        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda *_args, **_kwargs: None
        sys.modules["dotenv"] = dotenv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="assets/generated-sprites",
        help="Directory to write PNG sprites into.",
    )
    args = parser.parse_args()

    _install_test_stubs()
    import display

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    frames = display._generate_sprite_frames()
    for name, image in sorted(frames.items()):
        if name.endswith("_blink"):
            continue
        image.save(out_dir / f"{name}.png")
        if name == "idle":
            for accessory in display._ACCESSORY_NAMES:
                display._apply_accessory(image, accessory).save(
                    out_dir / f"idle_{accessory}.png"
                )

    count = len([k for k in frames if not k.endswith("_blink")]) + len(display._ACCESSORY_NAMES)
    print(f"wrote {count} sprites to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
