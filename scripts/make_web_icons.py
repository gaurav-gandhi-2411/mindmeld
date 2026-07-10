"""Generate PWA web icons + favicons for Warmer from the master heat-rings sources.

Produces (written to app/web/):
  icons/Icon-192.png          — 192x192 standard PWA icon (opaque tile).
  icons/Icon-512.png          — 512x512 standard PWA icon (opaque tile).
  icons/Icon-maskable-192.png — 192x192 maskable icon (safe-zone padded, dark ground).
  icons/Icon-maskable-512.png — 512x512 maskable icon (safe-zone padded, dark ground).
  icons/Icon-180.png          — 180x180 apple-touch-icon (opaque tile; iOS ignores alpha).
  icons/favicon-16.png        — 16px favicon: simplified 2-ring + dot (see below).
  favicon.png                 — 32px favicon: full 3-ring + dot (top-level; Flutter's
                                 web build copies this exact filename verbatim).

Two source masters (see scripts/make_app_icon.py):
  - app/assets/icon-1024.png     — opaque tile (dark ground + rings). Used for the
    standard/apple-touch derivations, which must NOT be transparent (iOS renders
    alpha unpredictably).
  - app/assets/icon-1024-fg.png  — transparent rings-only. Used for maskable
    derivation, which composites the foreground onto a dark-ground canvas itself
    via the alpha channel to get correct safe-zone padding.

Favicons are drawn fresh at their target size (not just resized) because the
locked identity spec calls for a *simplified* 16px variant (blue ring + amber
ring + red dot, skipping the cyan ring) — a naive downscale of the 3-ring
32px mark would blur into an illegible smudge at 16px.

Usage (from repo root):
    uv run --with pillow python scripts/make_web_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
SOURCE_TILE: Path = REPO_ROOT / "app" / "assets" / "icon-1024.png"
SOURCE_FG: Path = REPO_ROOT / "app" / "assets" / "icon-1024-fg.png"
OUT_DIR: Path = REPO_ROOT / "app" / "web" / "icons"
WEB_ROOT: Path = REPO_ROOT / "app" / "web"

# ---------------------------------------------------------------------------
# Locked heat-rings palette — must match scripts/make_app_icon.py exactly.
# ---------------------------------------------------------------------------

COLD: tuple[int, int, int] = (0x25, 0x63, 0xEB)
WARM: tuple[int, int, int] = (0xF5, 0x9E, 0x0B)
HOT: tuple[int, int, int] = (0xEF, 0x44, 0x44)

# App-tile ground (dark) — background for maskable icons.
BRAND_BG: tuple[int, int, int, int] = (0x0F, 0x17, 0x2A, 0xFF)

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

FAVICON_32: int = 32
FAVICON_16: int = 16


def _make_standard(src: Image.Image, size: int) -> Image.Image:
    """Resize [src] (the opaque tile) to [size]x[size]."""
    return src.resize((size, size), Image.LANCZOS)


def _make_maskable(fg: Image.Image, size: int) -> Image.Image:
    """Create a maskable icon: dark-ground background + centred, scaled rings.

    [fg] must be the transparent rings-only source — its alpha channel is the
    paste mask, so the dark-ground bleed area is always correct regardless of
    which mask shape (circle, squircle, rounded-square) the OS applies.
    """
    canvas = Image.new("RGBA", (size, size), BRAND_BG)

    fg_size = int(size * MASKABLE_FG_SCALE)
    scaled = fg.resize((fg_size, fg_size), Image.LANCZOS)

    offset = (size - fg_size) // 2
    canvas.paste(scaled, (offset, offset), scaled)
    return canvas


def _draw_favicon_32(size: int = FAVICON_32) -> Image.Image:
    """Full 3-ring + centre-dot mark, transparent background, tuned for 32px."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2
    stroke_w = max(1, round(size * 0.125))

    for frac, colour in ((0.44, COLD), (0.30, (0x06, 0xB6, 0xD4)), (0.16, WARM)):
        r = size * frac
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=colour, width=stroke_w)

    r_dot = size * 0.06
    draw.ellipse((cx - r_dot, cy - r_dot, cx + r_dot, cy + r_dot), fill=(*HOT, 255))
    return img


def _draw_favicon_16(size: int = FAVICON_16) -> Image.Image:
    """Simplified: blue ring + amber ring + red dot (cyan ring dropped for
    legibility at 16px), transparent background."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2
    stroke_w = max(1, round(size * 0.16))

    for frac, colour in ((0.42, COLD), (0.22, WARM)):
        r = size * frac
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=colour, width=stroke_w)

    r_dot = size * 0.10
    draw.ellipse((cx - r_dot, cy - r_dot, cx + r_dot, cy + r_dot), fill=(*HOT, 255))
    return img


def main() -> None:
    """Generate all PWA web icons + favicons from the two master sources."""
    for path in (SOURCE_TILE, SOURCE_FG):
        if not path.exists():
            raise FileNotFoundError(
                f"Source icon not found: {path}\n"
                "Run scripts/make_app_icon.py first to generate the master icons."
            )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tile = Image.open(SOURCE_TILE).convert("RGBA")
    fg = Image.open(SOURCE_FG).convert("RGBA")

    for filename, size, is_maskable in ICONS:
        out_path = OUT_DIR / filename
        img = _make_maskable(fg, size) if is_maskable else _make_standard(tile, size)
        img.save(out_path, "PNG", optimize=True)
        print(f"  created: {out_path} ({out_path.stat().st_size:,} bytes)")

    favicon_32 = _draw_favicon_32()
    favicon_32_path = WEB_ROOT / "favicon.png"
    favicon_32.save(favicon_32_path, "PNG", optimize=True)
    print(f"  created: {favicon_32_path} ({favicon_32_path.stat().st_size:,} bytes)")

    favicon_16 = _draw_favicon_16()
    favicon_16_path = OUT_DIR / "favicon-16.png"
    favicon_16.save(favicon_16_path, "PNG", optimize=True)
    print(f"  created: {favicon_16_path} ({favicon_16_path.stat().st_size:,} bytes)")

    print(f"\nAll icons + favicons written to {OUT_DIR} and {WEB_ROOT}")


if __name__ == "__main__":
    main()
