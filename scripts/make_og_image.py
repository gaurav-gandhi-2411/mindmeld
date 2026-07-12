"""Generate the 1200x630 Open Graph / Twitter share-preview card for Warmer.

Design: dark ground background, heat-rings mark on the left, "warmer"
wordmark ("warm" in white, "er" in the wordmark-accent orange) to its right,
tagline below. Matches warmer_heat_rings_identity.svg's icon + wordmark
lockup, scaled up for a social-preview card.

Usage (from repo root):
    uv run --with pillow python scripts/make_og_image.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH: int = 1200
HEIGHT: int = 630

COLD: tuple[int, int, int] = (0x6B, 0x89, 0xA8)
COOL: tuple[int, int, int] = (0x7E, 0x9B, 0xB5)
WARM: tuple[int, int, int] = (0xD9, 0xAE, 0x6B)
HOT: tuple[int, int, int] = (0xD6, 0x5F, 0x49)
WORDMARK_ACCENT: tuple[int, int, int] = (0xE8, 0x7A, 0x5C)
GROUND: tuple[int, int, int] = (0x17, 0x16, 0x14)
TAGLINE_GREY: tuple[int, int, int] = (0x9C, 0x96, 0x8C)
WARM_TEXT: tuple[int, int, int] = (0xF2, 0xEF, 0xE9)

TAGLINE = "The daily word game where closer means warmer."


def _find_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = (
        [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]
        if bold
        else [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"]
    )
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    try:
        import matplotlib.font_manager as fm  # type: ignore[import-untyped]

        props = fm.FontProperties(family="DejaVu Sans", weight="bold" if bold else "normal")
        path = fm.findfont(props)
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    except ImportError:
        pass
    return ImageFont.load_default()  # type: ignore[return-value]


def _draw_rings(draw: ImageDraw.ImageDraw, cx: float, cy: float, r_outer: float) -> None:
    stroke_w = max(2, round(r_outer * 0.17))
    for frac, colour in ((1.0, COLD), (0.74, COOL), (0.48, WARM)):
        r = r_outer * frac
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=colour, width=stroke_w)
    r_dot = r_outer * 0.22
    draw.ellipse((cx - r_dot, cy - r_dot, cx + r_dot, cy + r_dot), fill=(*HOT, 255))


def render() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), GROUND)
    draw = ImageDraw.Draw(img)

    # Heat-rings mark, left third.
    mark_cx, mark_cy = 230, HEIGHT // 2 - 20
    _draw_rings(draw, mark_cx, mark_cy, r_outer=170)

    # Wordmark, right of the mark.
    word_font = _find_font(128, bold=True)
    warm_text = "warm"
    er_text = "er"
    warm_bbox = draw.textbbox((0, 0), warm_text, font=word_font)
    warm_w = warm_bbox[2] - warm_bbox[0]

    word_x = 520
    word_y = HEIGHT // 2 - 130
    draw.text((word_x, word_y), warm_text, font=word_font, fill=WARM_TEXT)
    draw.text((word_x + warm_w, word_y), er_text, font=word_font, fill=WORDMARK_ACCENT)

    # Tagline below the wordmark — shrink to fit the available width so it
    # never clips against the card's right edge.
    max_tagline_width = WIDTH - (word_x + 6) - 40
    tagline_size = 34
    tagline_font = _find_font(tagline_size, bold=False)
    while tagline_size > 16:
        bbox = draw.textbbox((0, 0), TAGLINE, font=tagline_font)
        if bbox[2] - bbox[0] <= max_tagline_width:
            break
        tagline_size -= 1
        tagline_font = _find_font(tagline_size, bold=False)
    draw.text((word_x + 6, word_y + 175), TAGLINE, font=tagline_font, fill=TAGLINE_GREY)

    return img


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    img = render()

    out_paths = [
        repo_root / "app" / "web" / "icons" / "og-image.png",
        repo_root / "docs" / "store-assets" / "og-image.png",
    ]
    for out_path in out_paths:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, "PNG", optimize=True)
        print(f"OG image saved: {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
