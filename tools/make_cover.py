"""One-off: generate assets/cover.png (needs Pillow: pip install pillow)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 1500
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
img = Image.new("RGB", (SIZE, SIZE))
px = img.load()
for y in range(SIZE):  # vertical gradient, deep indigo -> teal
    t = y / (SIZE - 1)
    c = (int(28 + 0 * t), int(24 + 110 * t), int(80 + 60 * t))
    for x in range(SIZE):
        px[x, y] = c
d = ImageDraw.Draw(img)
big, small = ImageFont.truetype(FONT, 190), ImageFont.truetype(FONT, 86)


def centered(text, y, font, fill):
    w = d.textlength(text, font=font)
    d.text(((SIZE - w) / 2, y), text, font=font, fill=fill)


centered("GenAI", 440, big, "white")
centered("Daily Brief", 660, big, "white")
d.rectangle([(SIZE / 2 - 150, 930), (SIZE / 2 + 150, 942)], fill=(120, 220, 255))
centered("practical AI, read aloud", 1000, small, (200, 235, 245))
out = Path(__file__).resolve().parents[1] / "assets" / "cover.png"
img.save(out, optimize=True)
print(out, out.stat().st_size, "bytes")
