"""Generate PWA web icons for Mindmeld from the master 1024×1024 source icon.

Produces (written to app/web/icons/):
  Icon-192.png          — 192×192 standard PWA icon.
  Icon-512.png          — 512×512 standard PWA icon.
  Icon-maskable-192.png — 192×192 maskable icon (safe-zone padded, solid bg).
  Icon-maskable-512.png — 512×512 maskable icon (safe-zone padded, solid bg).
  Icon-180.png          — 180×180 apple-touch-icon.

Maskable icons pad the source icon to 80% of the canvas so the foreground
sits within the recommended "safe zone" for all mask shapes (circle, squircle,
etc). The background is filled with the brand freezing-blue #1976D2.

Usage (from repo root):
    uv run --with pillow python scripts/make_web_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
SOURCE_ICON: Path = REPO_ROOT / "app" / "assets" / "icon-1024.png"
OUT_DIR: Path = REPO_ROOT / "app" / "web" / "icons"

# ---------------------------------------------------------------------------
# Brand colours
# ---------------------------------------------------------------------------

# Theme colour (freezing blue) — used as maskable icon background.
BRAND_BG: tuple[int, int, int, int] = (0x19, 0x76, 0xD2, 0xFF)

# ---------------------------------------------------------------------------
# Icon specs
# ---------------------------------------------------------------------------

# (filename, size, is_maskable)
ICONS: list[tuple[str, int, bool]] = [
    ("Icon-192.png", 192, False),
    ("Icon-512.png", 512, False),
    ("Icon-maskable-192.png", 192, True),
    ("Icon-maskable-512.png", 512, True),
    ("Icon-180.png", 180, False),
]

# Foreground scale for maskable icons — 80% keeps artwork in the safe zone
# for all adaptive mask shapes (circle, squircle, rounded-square, full-bleed).
MASKABLE_FG_SCALE: float = 0.80


def _make_standard(src: Image.Image, size: int) -> Image.Image:
    """Resize [src] to [size]×[size] preserving transparency."""
    return src.resize((size, size), Image.LANCZOS)


def _make_maskable(src: Image.Image, size: int) -> Image.Image:
    """Create a maskable icon: brand-colour background + centred, scaled artwork.

    The source icon is shrunk to [MASKABLE_FG_SCALE * size] and composited onto
    a solid brand-colour canvas so every mask shape sees correct colours in the
    bleed area.
    """
    canvas = Image.new("RGBA", (size, size), BRAND_BG)

    fg_size = int(size * MASKABLE_FG_SCALE)
    fg = src.resize((fg_size, fg_size), Image.LANCZOS)

    # Centre the foreground on the canvas.
    offset = (size - fg_size) // 2
    # Use the source alpha as the paste mask.
    canvas.paste(fg, (offset, offset), fg)
    return canvas


def main() -> None:
    """Generate all PWA web icons from the master source."""
    if not SOURCE_ICON.exists():
        raise FileNotFoundError(
            f"Source icon not found: {SOURCE_ICON}\n"
            "Run scripts/make_app_icon.py first to generate app/assets/icon-1024.png."
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    src = Image.open(SOURCE_ICON).convert("RGBA")

    for filename, size, is_maskable in ICONS:
        out_path = OUT_DIR / filename
        if is_maskable:
            img = _make_maskable(src, size)
        else:
            img = _make_standard(src, size)
        img.save(out_path, "PNG", optimize=True)
        print(f"  created: {out_path} ({out_path.stat().st_size:,} bytes)")

    print(f"\nAll {len(ICONS)} icons written to {OUT_DIR}")


if __name__ == "__main__":
    main()
