"""Generate branded app icons for Mindmeld.

Produces:
  docs/store-assets/icon-512.png  — 512 × 512, 32-bit RGBA, for Play Store hi-res icon.
  docs/store-assets/icon-1024.png — 1024 × 1024, 32-bit RGBA, master export.

Design:
  - Rounded-square shape with a diagonal temperature gradient background
    (bottom-left deep-blue → top-right deep-red, matching app band colours).
  - Centred bold "M" glyph in white with a light drop shadow.
  - Small flame/spark accent (◆ diamond glyph) top-right of the "M", in amber
    (#FBC02D), suggesting warmth without adding visual noise at small sizes.
  - Transparent corners outside the rounded square (32-bit PNG with alpha).

Usage (from repo root):
    uv run --with pillow python scripts/make_app_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Band colour palette — exact hex values from app/lib/features/puzzle/guess_tile.dart
# ---------------------------------------------------------------------------

COLOUR_FREEZING: tuple[int, int, int] = (0x19, 0x76, 0xD2)   # #1976D2 deep blue
COLOUR_SCORCHING: tuple[int, int, int] = (0xD3, 0x2F, 0x2F)  # #D32F2F deep red
COLOUR_WARM: tuple[int, int, int] = (0xFB, 0xC0, 0x2D)       # #FBC02D amber (accent)

# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

SIZE_512: int = 512
SIZE_1024: int = 1024

# Corner radius as a fraction of icon size (matches Material You adaptive icon spec ~22 %).
CORNER_RADIUS_FRACTION: float = 0.22

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


def _build_diagonal_gradient(size: int) -> Image.Image:
    """Render a diagonal gradient (bottom-left → top-right) at *size* × *size*.

    Colour range: COLOUR_FREEZING (deep blue) → COLOUR_SCORCHING (deep red).
    """
    img = Image.new("RGB", (size, size))
    pixels = img.load()
    assert pixels is not None
    for y in range(size):
        for x in range(size):
            # t=0 at bottom-left (x=0,y=size-1), t=1 at top-right (x=size-1,y=0).
            t = (x / (size - 1) + (1.0 - y / (size - 1))) / 2.0
            t = max(0.0, min(1.0, t))
            pixels[x, y] = _lerp_colour(COLOUR_FREEZING, COLOUR_SCORCHING, t)
    return img


def _find_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Load the best available TrueType font at *size* pts.

    Preference order: segoeuib.ttf → arialbd.ttf → DejaVuSans-Bold via matplotlib.
    """
    candidates: list[str]
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

    try:
        import matplotlib.font_manager as fm  # type: ignore[import-untyped]

        props = fm.FontProperties(family="DejaVu Sans", weight="bold" if bold else "normal")
        path = fm.findfont(props)
        if path and Path(path).exists():
            candidates.append(path)
    except ImportError:
        pass

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)

    # Pillow bundled fallback.
    try:
        import PIL
        pil_dir = Path(PIL.__file__).parent
        for candidate in pil_dir.glob("**/*Bold*.ttf"):
            return ImageFont.truetype(str(candidate), size)
    except Exception:
        pass

    return ImageFont.load_default()  # type: ignore[return-value]


def _make_rounded_mask(size: int, radius: int) -> Image.Image:
    """Create an RGBA mask with a white rounded square on a transparent background."""
    mask = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=(255, 255, 255, 255))
    return mask


def _render_icon(size: int) -> Image.Image:
    """Render the Mindmeld icon at *size* × *size* with alpha channel."""
    # ── Background ──────────────────────────────────────────────────────────
    bg = _build_diagonal_gradient(size)

    # Apply rounded-square mask.
    radius = int(size * CORNER_RADIUS_FRACTION)
    mask = _make_rounded_mask(size, radius)

    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon.paste(bg, (0, 0))
    icon.putalpha(mask.split()[3])  # alpha channel from the mask

    draw = ImageDraw.Draw(icon)

    # ── "M" glyph ───────────────────────────────────────────────────────────
    glyph = "M"
    # Choose font size so "M" fills ~55 % of the icon width.
    glyph_target_width = int(size * 0.55)
    # Binary search for the right font size.
    lo, hi = 10, size
    glyph_font: ImageFont.FreeTypeFont | None = None
    for _ in range(16):
        mid = (lo + hi) // 2
        f = _find_font(mid, bold=True)
        bbox = f.getbbox(glyph)
        w = bbox[2] - bbox[0]
        if w < glyph_target_width:
            lo = mid
        else:
            hi = mid
        glyph_font = f

    # Final pass at lo.
    glyph_font = _find_font(lo, bold=True)
    bbox = glyph_font.getbbox(glyph)
    gw = bbox[2] - bbox[0]
    gh = bbox[3] - bbox[1]

    # Centre the "M" slightly above centre to leave room for accent.
    gx = (size - gw) // 2 - bbox[0]
    gy = (size - gh) // 2 - bbox[1] - int(size * 0.04)

    # Drop shadow for the glyph.
    shadow_offset = max(2, size // 80)
    shadow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_layer)
    sdraw.text(
        (gx + shadow_offset, gy + shadow_offset),
        glyph,
        font=glyph_font,
        fill=(0, 0, 0, 130),
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_offset * 2))
    icon = Image.alpha_composite(icon, shadow_layer)
    draw = ImageDraw.Draw(icon)

    # White "M".
    draw.text((gx, gy), glyph, font=glyph_font, fill=(255, 255, 255, 255))

    # ── Flame/spark accent (◆ diamond) ──────────────────────────────────────
    # Small amber diamond top-right of the "M".  Size ~15 % of icon width.
    accent_char = "◆"
    accent_size = max(10, int(size * 0.13))
    accent_font = _find_font(accent_size, bold=False)
    abbox = accent_font.getbbox(accent_char)
    aw = abbox[2] - abbox[0]
    ah = abbox[3] - abbox[1]

    # Position: right edge of the "M" bounding box + small padding, at the top.
    ax = gx + gw + int(size * 0.01) - abbox[0]
    ay = gy - int(size * 0.02) - abbox[1]

    # Keep within icon bounds.
    ax = min(ax, size - aw - 4)

    draw.text((ax, ay), accent_char, font=accent_font, fill=(*COLOUR_WARM, 255))

    return icon


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def generate_icons(out_dir: Path) -> None:
    """Render both icon sizes and save them to *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)

    for size, name in [(SIZE_512, "icon-512.png"), (SIZE_1024, "icon-1024.png")]:
        icon = _render_icon(size)
        out_path = out_dir / name
        icon.save(str(out_path), "PNG")
        assert icon.size == (size, size), f"Icon size mismatch: {icon.size}"
        print(f"Icon saved: {out_path} ({size}x{size}, mode={icon.mode})")


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / "docs" / "store-assets"
    generate_icons(out_dir)
