"""Generate branded app icons for Warmer — the heat-rings mark.

Design (locked palette, see spec-aesthetic-pass.md):
  Concentric rings closing to a hot center — cold blue outer, cyan, amber,
  red-hot center dot. It IS the mechanic (closing in, getting warmer).
    cold/outer #6B89A8, cool #7E9BB5, warm #D9AE6B, hot/center #D65F49
    app-tile dark ground #171614

Produces TWO master images per size, because Android adaptive icons need a
transparent foreground composited over a separate solid background layer,
while Play Store / iOS / legacy Android need one full-bleed opaque square:

  docs/store-assets/icon-512.png, icon-1024.png   — opaque "tile" (dark
    ground + rings), full-bleed square. Also copied to app/assets/icon-1024.png
    (source for scripts/make_web_icons.py's standard/apple-touch derivation
    and flutter_launcher_icons' image_path).
  app/assets/icon-1024-fg.png                     — transparent rings-only
    (no background). Source for scripts/make_web_icons.py's maskable
    derivation (safe-zone compositing needs alpha) and
    flutter_launcher_icons' adaptive_icon_foreground (composited over the
    solid adaptive_icon_background colour).

Usage (from repo root):
    uv run --with pillow python scripts/make_app_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Locked heat-rings palette — see spec-aesthetic-pass.md
# ---------------------------------------------------------------------------

COLD: tuple[int, int, int] = (0x6B, 0x89, 0xA8)
COOL: tuple[int, int, int] = (0x7E, 0x9B, 0xB5)
WARM: tuple[int, int, int] = (0xD9, 0xAE, 0x6B)
HOT: tuple[int, int, int] = (0xD6, 0x5F, 0x49)
GROUND: tuple[int, int, int] = (0x17, 0x16, 0x14)

# ---------------------------------------------------------------------------
# Ring geometry — fractions of icon size S. Same ratios reused at every
# size/variant so the mark reads identically at any scale.
# ---------------------------------------------------------------------------

R_OUTER_FRAC: float = 0.30  # cold ring
R_MID_FRAC: float = 0.22  # cool ring
R_INNER_FRAC: float = 0.14  # warm ring
R_DOT_FRAC: float = 0.065  # hot centre
STROKE_FRAC: float = 0.05

CORNER_RADIUS_FRACTION: float = 0.22  # tile corner rounding, matches Material You

SIZE_512: int = 512
SIZE_1024: int = 1024


def _draw_rings(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Draw the three concentric ring strokes + filled centre dot at *size*."""
    cx = cy = size / 2
    stroke_w = max(1, round(size * STROKE_FRAC))

    for frac, colour in (
        (R_OUTER_FRAC, COLD),
        (R_MID_FRAC, COOL),
        (R_INNER_FRAC, WARM),
    ):
        r = size * frac
        bbox = (cx - r, cy - r, cx + r, cy + r)
        draw.ellipse(bbox, outline=colour, width=stroke_w)

    r_dot = size * R_DOT_FRAC
    dot_bbox = (cx - r_dot, cy - r_dot, cx + r_dot, cy + r_dot)
    draw.ellipse(dot_bbox, fill=(*HOT, 255))


def _render_transparent(size: int) -> Image.Image:
    """Rings only, transparent background — adaptive-icon foreground / maskable source."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _draw_rings(draw, size)
    return img


def _render_tile(size: int) -> Image.Image:
    """Rounded-square dark-ground tile + rings — full-bleed opaque square."""
    img = Image.new("RGBA", (size, size), (*GROUND, 255))
    radius = int(size * CORNER_RADIUS_FRACTION)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, (0, 0), mask)
    draw = ImageDraw.Draw(canvas)
    _draw_rings(draw, size)
    return canvas


def generate_icons(store_out_dir: Path, app_assets_dir: Path) -> None:
    """Render tile + transparent masters at both sizes and write all outputs."""
    store_out_dir.mkdir(parents=True, exist_ok=True)
    app_assets_dir.mkdir(parents=True, exist_ok=True)

    for size, name in [(SIZE_512, "icon-512.png"), (SIZE_1024, "icon-1024.png")]:
        tile = _render_tile(size)
        out_path = store_out_dir / name
        tile.save(str(out_path), "PNG")
        print(f"Tile icon saved: {out_path} ({size}x{size})")

    # app/assets/icon-1024.png — opaque tile, source for standard web icons +
    # flutter_launcher_icons image_path (legacy/iOS square).
    tile_1024 = _render_tile(SIZE_1024)
    tile_1024.save(str(app_assets_dir / "icon-1024.png"), "PNG")
    print(f"Icon saved: {app_assets_dir / 'icon-1024.png'} (opaque tile, source)")

    # app/assets/icon-1024-fg.png — transparent rings-only, source for
    # maskable web icons + flutter_launcher_icons adaptive_icon_foreground.
    fg_1024 = _render_transparent(SIZE_1024)
    fg_1024.save(str(app_assets_dir / "icon-1024-fg.png"), "PNG")
    print(f"Icon saved: {app_assets_dir / 'icon-1024-fg.png'} (transparent, source)")


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent
    generate_icons(
        store_out_dir=repo_root / "docs" / "store-assets",
        app_assets_dir=repo_root / "app" / "assets",
    )
