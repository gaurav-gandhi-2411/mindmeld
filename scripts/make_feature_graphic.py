"""Generate the Play Store feature graphic (1024 × 500 px) for Warmer.

Design:
  - Horizontal gradient background using the locked heat-rings identity palette:
      cold #2563EB → cool #06B6D4 → warm #F59E0B → hot #EF4444
      (see spec-warmer-rename.md — same palette as the app icon/OG card, not
      the separate 5-band gameplay guess-tile palette in guess_tile.dart).
  - "Warmer" wordmark in white with a light shadow (segoeuib.ttf, fallback Arial/DejaVu).
  - Tagline below the wordmark.
  - A row of emoji-style rounded squares in the heat-rings palette, echoing the mark.

Usage (from repo root):
    uv run --with pillow python scripts/make_feature_graphic.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

WIDTH: int = 1024
HEIGHT: int = 500

# ---------------------------------------------------------------------------
# Locked heat-rings identity palette — see spec-warmer-rename.md /
# scripts/make_app_icon.py. Distinct from the 5-band gameplay guess-tile
# palette in app/lib/features/puzzle/guess_tile.dart.
# ---------------------------------------------------------------------------

COLOUR_COLD: tuple[int, int, int] = (0x25, 0x63, 0xEB)  # #2563EB
COLOUR_COOL: tuple[int, int, int] = (0x06, 0xB6, 0xD4)  # #06B6D4
COLOUR_WARM: tuple[int, int, int] = (0xF5, 0x9E, 0x0B)  # #F59E0B
COLOUR_HOT: tuple[int, int, int] = (0xEF, 0x44, 0x44)  # #EF4444

# Gradient stops as (x_fraction, RGB) from left to right.
GRADIENT_STOPS: list[tuple[float, tuple[int, int, int]]] = [
    (0.00, COLOUR_COLD),
    (0.35, COLOUR_COOL),
    (0.68, COLOUR_WARM),
    (1.00, COLOUR_HOT),
]

# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

WORDMARK: str = "Warmer"
TAGLINE: str = "Guess the word by meaning — new puzzle daily · English & Hinglish"

# Safe horizontal margin (Play Store requires 15 % margin on each side = ~154 px;
# use 80 px for a cleaner look while staying comfortably inside).
MARGIN_X: int = 80
MARGIN_Y: int = 48

# ---------------------------------------------------------------------------
# Emoji-square motif — one rounded square per temperature band
# ---------------------------------------------------------------------------

BAND_COLOURS: list[tuple[int, int, int]] = [
    COLOUR_COLD,
    COLOUR_COOL,
    COLOUR_WARM,
    COLOUR_HOT,
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lerp_colour(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    t: float,
) -> tuple[int, int, int]:
    """Linearly interpolate between two RGB colours."""
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _gradient_colour(x_fraction: float) -> tuple[int, int, int]:
    """Return the interpolated gradient colour at horizontal position [0, 1]."""
    stops = GRADIENT_STOPS
    for i in range(len(stops) - 1):
        x0, c0 = stops[i]
        x1, c1 = stops[i + 1]
        if x0 <= x_fraction <= x1:
            t = (x_fraction - x0) / (x1 - x0)
            return _lerp_colour(c0, c1, t)
    # Clamp to endpoints.
    return stops[-1][1] if x_fraction >= 1.0 else stops[0][1]


def _build_gradient(width: int, height: int) -> Image.Image:
    """Render the horizontal temperature gradient onto a new RGB image."""
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    assert pixels is not None
    for x in range(width):
        colour = _gradient_colour(x / (width - 1))
        for y in range(height):
            pixels[x, y] = colour
    return img


def _find_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Load the best available TrueType font at *size* pts.

    Preference order:
      1. segoeuib.ttf (Windows Segoe UI Bold) — clean, modern sans-serif.
      2. arialbd.ttf  (Windows Arial Bold).
      3. DejaVuSans-Bold.ttf bundled with Pillow/Matplotlib.

    Falls back to the Pillow default bitmap font (no size guarantee) if none
    of the above are found — the banner will still render, just with a smaller
    glyph.
    """
    candidates: list[str] = []
    if bold:
        candidates = [
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            "/c/Windows/Fonts/segoeuib.ttf",
            "/c/Windows/Fonts/arialbd.ttf",
        ]
    else:
        candidates = [
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            "/c/Windows/Fonts/segoeui.ttf",
            "/c/Windows/Fonts/arial.ttf",
        ]

    # Also look for DejaVu which ships with Pillow data extras on some installs.
    try:
        import matplotlib.font_manager as fm  # type: ignore[import-untyped]

        for name, is_bold in [("DejaVu Sans", bold)]:
            props = fm.FontProperties(family=name, weight="bold" if is_bold else "normal")
            path = fm.findfont(props)
            if path and Path(path).exists():
                candidates.append(path)
    except ImportError:
        pass

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)

    # Last resort: Pillow's bundled DejaVuSans (inside the package).
    try:
        import PIL
        pil_dir = Path(PIL.__file__).parent
        for candidate in pil_dir.glob("**/*Bold*.ttf"):
            return ImageFont.truetype(str(candidate), size)
    except Exception:
        pass

    # Absolute fallback — bitmap font, no size control.
    return ImageFont.load_default()  # type: ignore[return-value]


def _draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int],
) -> None:
    """Draw a filled rounded rectangle on *draw*."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=fill)


def _text_shadow(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    shadow_offset: int = 3,
    shadow_alpha: int = 120,
) -> None:
    """Render text with a soft drop shadow for legibility on the gradient."""
    # Shadow pass on a separate RGBA layer, then composite.
    shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_layer)
    sdraw.text(
        (xy[0] + shadow_offset, xy[1] + shadow_offset),
        text,
        font=font,
        fill=(0, 0, 0, shadow_alpha),
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_offset))
    img.paste(Image.alpha_composite(img.convert("RGBA"), shadow_layer).convert("RGB"))

    # Redraw draw on refreshed img.
    draw = ImageDraw.Draw(img)
    draw.text(xy, text, font=font, fill=fill)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def generate_feature_graphic(out_path: Path) -> None:
    """Render and save the 1024 × 500 feature graphic to *out_path*."""
    img = _build_gradient(WIDTH, HEIGHT)
    draw = ImageDraw.Draw(img)

    # ── Wordmark ────────────────────────────────────────────────────────────
    wordmark_font = _find_font(size=112, bold=True)
    # Centre horizontally.
    bbox = wordmark_font.getbbox(WORDMARK)
    w_text = bbox[2] - bbox[0]
    wordmark_x = (WIDTH - w_text) // 2
    wordmark_y = MARGIN_Y

    _text_shadow(
        img, draw,
        xy=(wordmark_x, wordmark_y),
        text=WORDMARK,
        font=wordmark_font,
        fill=(255, 255, 255),
        shadow_offset=4,
        shadow_alpha=140,
    )
    # Refresh draw after shadow compositing.
    draw = ImageDraw.Draw(img)

    # ── Tagline ─────────────────────────────────────────────────────────────
    tagline_font = _find_font(size=26, bold=False)
    bbox_tag = tagline_font.getbbox(TAGLINE)
    tag_w = bbox_tag[2] - bbox_tag[0]
    tag_x = (WIDTH - tag_w) // 2
    # bbox[3] is the pixel offset of the glyph bottom from the draw origin —
    # use it to place the tagline strictly below the rendered wordmark pixels.
    tag_y = wordmark_y + bbox[3] + 16  # 16px gap below wordmark bottom

    # Shadow for tagline too.
    _text_shadow(
        img, draw,
        xy=(tag_x, tag_y),
        text=TAGLINE,
        font=tagline_font,
        fill=(255, 255, 255),
        shadow_offset=2,
        shadow_alpha=100,
    )
    draw = ImageDraw.Draw(img)

    # ── Emoji-square row ────────────────────────────────────────────────────
    # Render below the tagline, centred, matching the share-card motif.
    square_size: int = 52
    square_gap: int = 16
    radius: int = 10
    n_squares = len(BAND_COLOURS)
    row_width = n_squares * square_size + (n_squares - 1) * square_gap
    row_x0 = (WIDTH - row_width) // 2

    # Place emoji row below the tagline's rendered bottom pixel.
    bbox_tag_size = tagline_font.getbbox(TAGLINE)
    # bbox_tag_size[3] is the visual bottom offset from draw origin.
    row_y = tag_y + bbox_tag_size[3] + 28

    for i, colour in enumerate(BAND_COLOURS):
        x0 = row_x0 + i * (square_size + square_gap)
        x1 = x0 + square_size
        y0 = row_y
        y1 = row_y + square_size
        _draw_rounded_rect(draw, (x0, y0, x1, y1), radius=radius, fill=colour)

    # Ensure output directory exists.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "PNG")
    print(f"Feature graphic saved: {out_path} ({WIDTH}x{HEIGHT})")


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent
    out = repo_root / "docs" / "store-assets" / "feature-graphic.png"
    generate_feature_graphic(out)
