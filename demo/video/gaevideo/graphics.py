"""Pillow drawing: synthetic stand-in photos for the draft, captions and overlay labels.

The installed ffmpeg has no drawtext/subtitles filter, so every piece of text burned into the
video is a PNG drawn here and laid over the footage with ffmpeg's overlay filter.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Output frame: the 1280x800 app (recorded at 1.5x) scaled to 1536x960, centred, with a
# 120 px caption band underneath and 192 px side margins.
W, H = 1920, 1080
APP_W, APP_H, APP_X = 1536, 960, 192
BAND_H = H - APP_H
BG = (17, 17, 17)

_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _FONTS if bold else _FONTS[1:]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def caption(text: str, out: Path) -> Path:
    """One caption line, white on the dark band, sized to the band."""
    im = Image.new("RGBA", (W, BAND_H), (*BG, 255))
    g = ImageDraw.Draw(im)
    size = 38
    while size > 22 and g.textlength(text, font=font(size)) > APP_W - 40:
        size -= 2
    f = font(size)
    g.text((W / 2, BAND_H / 2), text, font=f, fill=(245, 245, 240), anchor="mm")
    im.save(out)
    return out


def side_label(lines: list[str], out: Path, colour=(240, 170, 60)) -> Path:
    """A small stacked label for the left margin (e.g. that the draft is Sam's offline sample)."""
    im = Image.new("RGBA", (APP_X, 260), (0, 0, 0, 0))
    g = ImageDraw.Draw(im)
    y = 24
    for i, line in enumerate(lines):
        f = font(21 if i == 0 else 19, bold=i == 0)
        g.text((APP_X / 2, y), line, font=f, fill=colour, anchor="mt")
        y += 34 if i == 0 else 28
    im.save(out)
    return out


def banner(text: str, out: Path) -> Path:
    """The "shortened" notice laid over the top of the app for a few seconds after a cut."""
    f = font(30, bold=True)
    tw = int(ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(text, font=f))
    im = Image.new("RGBA", (tw + 64, 64), (0, 0, 0, 0))
    g = ImageDraw.Draw(im)
    g.rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=18, fill=(25, 25, 25, 235))
    g.text((im.width / 2, im.height / 2), text, font=f, fill=(255, 200, 90), anchor="mm")
    im.save(out)
    return out


def card(title: str, body: str, out: Path) -> Path:
    """A full-frame still (used when no clip is inserted and nothing was recorded)."""
    im = Image.new("RGB", (W, H), BG)
    g = ImageDraw.Draw(im)
    g.text((W / 2, H / 2 - 50), title, font=font(56, bold=True), fill=(245, 245, 240), anchor="mm")
    g.text((W / 2, H / 2 + 40), body, font=font(32), fill=(200, 200, 195), anchor="mm")
    im.save(out)
    return out


# --- Synthetic stand-in photos for the draft (never real material) ---------------------------

SYNTH_STAMP = "SYNTHETIC SAMPLE - NOT A REAL PHOTO"
# Where the fake identifying line sits on the synthetic bill, as fractions of the image, so the
# draft's Black out drag covers exactly that line.
BILL_IDENTITY_BOX = (0.05, 0.13, 0.75, 0.25)


def _stamp(g: ImageDraw.ImageDraw, w: int, h: int) -> None:
    g.text((w / 2, h - 40), SYNTH_STAMP, font=font(30, bold=True), fill=(200, 40, 40), anchor="mm")


def synth_photos(out: Path) -> dict[str, Path]:
    """Drawn stand-ins for the draft: gas bill, boiler plate, fuse label, one radiator."""
    out.mkdir(parents=True, exist_ok=True)
    made = {}

    w, h = 1200, 900
    im = Image.new("RGB", (w, h), (250, 250, 247))
    g = ImageDraw.Draw(im)
    g.text((60, 40), "Your gas usage - last 12 months", font=font(44, bold=True), fill=(20, 20, 20))
    x1, y1 = int(BILL_IDENTITY_BOX[0] * w), int(BILL_IDENTITY_BOX[1] * h)
    g.text(
        (x1 + 10, y1 + 10), "Name: A. SAMPLE   Account: 0000 0000", font=font(32), fill=(40, 40, 40)
    )
    g.text((x1 + 10, y1 + 55), "Supply address: 1 Example Road", font=font(32), fill=(40, 40, 40))
    g.text(
        (60, 260),
        "1 Oct 2025 - 30 Sep 2026: 12,000 kWh",
        font=font(36, bold=True),
        fill=(20, 20, 20),
    )
    monthly = [1650, 1900, 2100, 1950, 1500, 1050, 600, 380, 320, 330, 480, 940]
    for i, v in enumerate(monthly):
        bx = 80 + i * 88
        g.rectangle((bx, 780 - v * 0.2, bx + 60, 780), fill=(46, 110, 160))
        g.text((bx + 30, 800), "ONDJFMAMJJAS"[i], font=font(24), fill=(40, 40, 40), anchor="mt")
    _stamp(g, w, h)
    made["gas-bill"] = out / "gas-bill.png"
    im.save(made["gas-bill"])

    im = Image.new("RGB", (w, h), (178, 182, 186))
    g = ImageDraw.Draw(im)
    g.rounded_rectangle(
        (120, 140, 1080, 760), radius=24, fill=(214, 216, 218), outline=(90, 90, 90), width=6
    )
    for i, line in enumerate(
        [
            "SAMPLE BOILER CO.",
            "Model: Greenstar 24i (sample)",
            "Heat output: 24 kW",
            "Hot water output: 24 kW",
            "Fuel: natural gas",
            "GC No: 00-000-00",
        ]
    ):
        g.text((180, 190 + i * 88), line, font=font(48, bold=i == 0), fill=(30, 30, 30))
    _stamp(g, w, h)
    made["boiler-plate"] = out / "boiler-plate.png"
    im.save(made["boiler-plate"])

    im = Image.new("RGB", (w, h), (120, 120, 118))
    g = ImageDraw.Draw(im)
    g.rectangle((380, 150, 820, 750), fill=(40, 40, 40))
    g.rectangle((440, 260, 760, 460), fill=(235, 235, 230))
    g.text((600, 330), "60A", font=font(110, bold=True), fill=(20, 20, 20), anchor="mm")
    g.text((600, 420), "BS 1361 cutout", font=font(30), fill=(20, 20, 20), anchor="mm")
    _stamp(g, w, h)
    made["fuse-cutout"] = out / "fuse-cutout.png"
    im.save(made["fuse-cutout"])

    im = Image.new("RGB", (w, h), (232, 226, 214))
    g = ImageDraw.Draw(im)
    g.rectangle((150, 250, 1050, 650), fill=(250, 250, 250), outline=(160, 160, 160), width=4)
    for x in range(170, 1040, 28):
        g.line((x, 260, x, 640), fill=(215, 215, 215), width=6)
    g.line((150, 700, 1050, 700), fill=(230, 180, 0), width=10)
    g.text((600, 730), "1200 mm", font=font(40, bold=True), fill=(30, 30, 30), anchor="mt")
    g.text((1058, 450), "600 mm", font=font(36, bold=True), fill=(30, 30, 30), anchor="lm")
    _stamp(g, w, h)
    made["radiator-1"] = out / "radiator-1.png"
    im.save(made["radiator-1"])
    return made
