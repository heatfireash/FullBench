"""
Generate the Full Bench logo.

    py make_logo.py

Writes:
    logo.png          512px mark
    logo_small.png    64px, for the app header
    icon.ico          multi-size Windows icon
    wordmark.png      mark plus "FULL BENCH", for a site header

The mark is the name laid out as the board it refers to: FULL in gold
above a bench of five cards spelling BENCH, a letter to a card. Drawn
from scratch -- rounded rectangles and text, no game artwork.

Icons simplify in two steps, because a five-letter wordmark cannot
survive a taskbar: blank cards at 40-48px, and the FB monogram at 32px
and below.
"""

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("pip install pillow")

HERE = Path(__file__).parent

# Palette taken from the colours on the back of a Pokemon card -- deep
# blue, white, gold. Colours themselves aren't protectable; the mark is
# still plain rectangles and copies no artwork.
BG = (26, 45, 104)          # deep blue
CARD = (247, 248, 252)      # white
ACTIVE = (245, 197, 57)     # gold


# Bold sans, whichever exists. Windows has Segoe UI and Arial; Linux
# builds fall back to DejaVu.
_FONTS = ("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf",
          "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")


def _font(px):
    for name in _FONTS:
        try:
            return ImageFont.truetype(name, px)
        except Exception:
            continue
    return ImageFont.load_default()


def _rr(d, box, r, fill):
    d.rounded_rectangle(box, radius=max(1, r), fill=fill)


def _centred_text(d, text, font, cx, top, fill):
    """Draw text centred horizontally, with its top at `top`.

    Glyph bounding boxes carry side bearings and ascent padding, so
    centring on the nominal text size leaves the mark visibly off. This
    measures the actual ink and positions that."""
    b = d.textbbox((0, 0), text, font=font)
    d.text((cx - (b[2] - b[0]) // 2 - b[0], top - b[1]), text,
           font=font, fill=fill)


def _centred(d, text, font, cx, top, fill):
    """Centre on the glyph ink, not the nominal text box."""
    b = d.textbbox((0, 0), text, font=font)
    d.text((cx - (b[2] - b[0]) // 2 - b[0], top - b[1]), text,
           font=font, fill=fill)


def _centred_in(d, text, font, box, fill):
    x0, y0, x1, y1 = box
    b = d.textbbox((0, 0), text, font=font)
    d.text((x0 + ((x1 - x0) - (b[2] - b[0])) // 2 - b[0],
            y0 + ((y1 - y0) - (b[3] - b[1])) // 2 - b[1]),
           text, font=font, fill=fill)


def full_mark(S, letters=True, background=True, card_h=0.33,
              bottom_pad=0.11):
    """
    The logo: FULL in gold above BENCH, a letter to a card.

    letters=False keeps the five cards but leaves them blank, for sizes
    where a letter would be three pixels tall.
    """
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        r = 0 if S <= 20 else max(2, round(S * 0.20))
        if r:
            d.rounded_rectangle((0, 0, S - 1, S - 1), radius=r, fill=BG)
        else:
            d.rectangle((0, 0, S - 1, S - 1), fill=BG)

    _centred(d, "FULL", _font(max(6, round(S * 0.31))), S // 2,
             round(S * 0.12), ACTIVE)

    n = 5
    bw = max(2, round(S * 0.144))
    bh = max(3, round(S * card_h))
    gap = max(1, round(S * 0.038))
    total = n * bw + (n - 1) * gap
    x = (S - total) // 2
    y = S - bh - max(1, round(S * bottom_pad))
    lf = _font(max(5, round(bh * 0.64)))
    for ch in "BENCH":
        box = (x, y, x + bw, y + bh)
        d.rounded_rectangle(box, radius=max(1, round(S * 0.03)), fill=CARD)
        if letters:
            _centred_in(d, ch, lf, box, BG)
        x += bw + gap
    return img


def monogram(S):
    """FB over three cards: the small-size mark."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = 0 if S <= 20 else max(2, round(S * 0.20))
    if r:
        d.rounded_rectangle((0, 0, S - 1, S - 1), radius=r, fill=BG)
    else:
        d.rectangle((0, 0, S - 1, S - 1), fill=BG)
    _centred(d, "FB", _font(max(6, round(S * 0.42))), S // 2,
             max(0, round(S * 0.10)), ACTIVE)
    n = 3
    gap = max(1, round(S * 0.045))
    bw = max(2, (round(S * 0.70) - (n - 1) * gap) // n)
    bh = max(2, round(S * 0.24))
    x = (S - (n * bw + (n - 1) * gap)) // 2
    y = S - bh - max(1, round(S * 0.10))
    br = 0 if S <= 32 else max(1, round(S * 0.03))
    for _ in range(n):
        box = (x, y, x + bw - 1, y + bh - 1)
        d.rounded_rectangle(box, radius=br, fill=CARD) if br else \
            d.rectangle(box, fill=CARD)
        x += bw + gap
    return img


def icon_mark(S):
    """
    The right mark for a given size.

    A five-letter wordmark cannot survive a taskbar. Rendering it at
    each size shows where it fails: below about 48px the letters in the
    cards turn to mud and the gaps between cards disappear. So the mark
    simplifies in two steps rather than being shrunk past legibility --
    which is how any wordmark logo is handled at icon sizes.

      >= 64px   FULL over BENCH, a letter to a card
      40-48px   FULL over five blank cards
      <= 32px   the FB monogram
    """
    if S >= 64:
        return full_mark(S, letters=True)
    if S >= 40:
        # blank cards need less height than lettered ones, which also
        # buys clearance under FULL
        return full_mark(S, letters=False, card_h=0.26, bottom_pad=0.14)
    return monogram(S)


def wordmark(height=160):
    """
    A horizontal lockup for a site header.

    The mark already spells the name, so repeating it in full beside
    itself reads as a stutter. This sets the mark next to a smaller,
    quieter subtitle instead.
    """
    H = height
    m = full_mark(H)
    W = int(H * 5.2)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.paste(m, (0, 0), m)
    d = ImageDraw.Draw(img)
    title = _font(int(H * 0.30))
    sub = _font(int(H * 0.15))
    x = int(H * 1.18)
    _centred_text_left = None
    b = d.textbbox((0, 0), "Full Bench", font=title)
    d.text((x, int(H * 0.30) - b[1]), "Full Bench", font=title, fill=CARD)
    d.text((x, int(H * 0.62)), "stat tracker for Pokemon TCG Live",
           font=sub, fill=(150, 160, 195))
    return img


def social_header(W=1500, H=500):
    """
    Twitter/X header, 1500x500.

    The profile picture covers the lower left and the display name
    overlaps the bottom, so everything that must stay readable sits
    right of centre and above the lower third. Mobile crops the sides,
    so nothing important goes near either edge.
    """
    img = Image.new("RGBA", (W, H), BG)

    # a faint bench of cards, far left, where the avatar will cover it
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    card_w, card_h, gap = int(H * 0.26), int(H * 0.40), int(H * 0.05)
    x, y = int(W * 0.02), int(H * 0.22)
    for _ in range(4):
        ld.rounded_rectangle((x, y, x + card_w, y + card_h),
                             radius=int(H * 0.04), fill=(255, 255, 255, 16))
        x += card_w + gap
    img = Image.alpha_composite(img, layer)
    d = ImageDraw.Draw(img)

    # mark and wordmark as one block, measured so it sits centred in the
    # safe area rather than guessed at
    mark_size = int(H * 0.42)
    title_f = _font(int(H * 0.17))
    sub_f = _font(int(H * 0.068))
    title, subtitle = "Full Bench", "stat tracker for Pokemon TCG Live"
    tb = d.textbbox((0, 0), title, font=title_f)
    sb = d.textbbox((0, 0), subtitle, font=sub_f)
    text_w = max(tb[2] - tb[0], sb[2] - sb[0])
    block_w = mark_size + int(H * 0.07) + text_w

    # centre the block in the right-hand two thirds, clear of the avatar
    left = int(W * 0.30)
    bx = left + max(0, (W - int(W * 0.06) - left - block_w) // 2)
    by = int(H * 0.22)

    mark = full_mark(mark_size)
    img.paste(mark, (bx, by), mark)
    d = ImageDraw.Draw(img)

    tx = bx + mark_size + int(H * 0.07)
    d.text((tx, by + int(H * 0.02) - tb[1]), title, font=title_f, fill=CARD)
    d.text((tx + 2, by + int(H * 0.23) - sb[1]), subtitle, font=sub_f,
           fill=(155, 168, 205))
    rule_y = by + int(H * 0.36)
    d.rounded_rectangle((tx, rule_y, tx + text_w, rule_y + max(3, int(H * 0.011))),
                        radius=3, fill=ACTIVE)
    return img.convert("RGB")


def web_icons(out):
    """
    The website's icons, written to `out` (server/static):

      favicon.ico            16/32/48 -- the browser tab
      apple-touch-icon.png   180, solid square -- iPhone home screen,
                             which rounds the corners itself and would
                             show transparent ones as black
      icon-192.png, icon-512.png + site.webmanifest -- Android
    """
    out.mkdir(parents=True, exist_ok=True)
    small = [16, 32, 48]
    fr = [icon_mark(s) for s in small]
    fr[-1].save(out / "favicon.ico", format="ICO",
                sizes=[(s, s) for s in small], append_images=fr[:-1])

    def solid(S):
        img = Image.new("RGBA", (S, S), BG + (255,))
        img.alpha_composite(full_mark(S))
        return img.convert("RGB")

    solid(180).save(out / "apple-touch-icon.png")
    for S in (192, 512):
        solid(S).save(out / f"icon-{S}.png")
    (out / "site.webmanifest").write_text(
        '{"name": "Full Bench", "short_name": "Full Bench",\n'
        ' "icons": [{"src": "/static/icon-192.png", "sizes": "192x192",'
        ' "type": "image/png"},\n'
        '           {"src": "/static/icon-512.png", "sizes": "512x512",'
        ' "type": "image/png"}],\n'
        ' "theme_color": "#1a2d68", "background_color": "#1a2d68",'
        ' "display": "browser"}\n', encoding="utf-8")


def main():
    full_mark(512).save(HERE / "logo.png")
    print("wrote logo.png (512)")

    full_mark(64).save(HERE / "logo_small.png")
    print("wrote logo_small.png (64)")

    # Windows picks the frame that matches what it's drawing, and only
    # scales -- blurrily -- when there isn't one. The taskbar draws at 24px
    # times the display scale (24, 30, 36, 48 at 100/125/150/200%); title
    # bars at 16 times the scale; the desktop and Alt-Tab at 32 or 48
    # times it. Every one of those sizes has its own frame.
    sizes = [16, 20, 24, 28, 30, 32, 36, 40, 42, 48, 56, 60, 64, 72, 80, 96,
             128, 256]
    frames = [icon_mark(s) for s in sizes]
    # Saved from the LARGEST frame: Pillow drops every requested size
    # bigger than the image it saves from, so starting at 16 produced an
    # icon.ico with nothing but 16x16 in it -- stretched and blurry on
    # the desktop and taskbar. The smaller frames still go in as drawn.
    frames[-1].save(HERE / "icon.ico", format="ICO",
                    sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    print("wrote icon.ico", sizes, "(drawn at native size, not downscaled)")

    # zoomed sheet so the small sizes can be eyeballed
    Z = 8
    sheet = Image.new("RGBA",
                      (sum(s * Z + 12 for s in sizes[:7]) + 12, 64 * Z + 24),
                      (70, 70, 76, 255))
    x = 12
    for s in sizes[:7]:
        sheet.paste(icon_mark(s).resize((s * Z, s * Z), Image.NEAREST),
                    (x, 12))
        x += s * Z + 12
    sheet.save(HERE / "icon_preview.png")
    print("wrote icon_preview.png (8x zoom, check the small sizes)")

    web_icons(HERE / "server" / "static")
    print("wrote server/static: favicon.ico, apple-touch-icon.png, "
          "icon-192/512.png, site.webmanifest")

    wordmark(160).save(HERE / "wordmark.png")
    print("wrote wordmark.png")

    social_header().save(HERE / "social_header.png")
    print("wrote social_header.png (1500x500, for X/Twitter)")

    # the profile picture: the mark on its own, square
    full_mark(400).convert("RGB").save(HERE / "avatar.png")
    print("wrote avatar.png (400x400, profile picture)")

    # side by side, so the two simplification steps can be judged
    row = [16, 24, 32, 40, 48, 64, 128]
    zoom = {16: 12, 24: 9, 32: 7, 40: 6, 48: 5, 64: 4, 128: 2}
    w = sum(s * zoom[s] + 14 for s in row) + 14
    sheet = Image.new("RGBA", (w, 256 + 28), (70, 70, 76, 255))
    x = 14
    for s in row:
        sheet.paste(icon_mark(s).resize((s * zoom[s], s * zoom[s]),
                                        Image.NEAREST), (x, 14))
        x += s * zoom[s] + 14
    sheet.save(HERE / "icon_preview.png")
    print("wrote icon_preview.png")


if __name__ == "__main__":
    main()
