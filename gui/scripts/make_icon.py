"""Generate the Expedient Employment app icon.

Dark navy rounded-square background, cyan "EE" monogram with a magnifying
glass glyph drawn over it (magnifier lens frames the monogram).

Outputs:
  build/icon.png  (512x512)
  build/icon.ico  (multi-size 16..256)
Run with the managed Python (Pillow available).
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 512
BG = (15, 23, 42, 255)          # #0f172a slate-900
ACCENT = (34, 211, 238, 255)    # #22d3ee cyan-400
ACCENT_DIM = (34, 211, 238, 90)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build"
OUT.mkdir(exist_ok=True)


def rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def draw_base(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    radius = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BG)

    # subtle inner ring accent
    inset = int(size * 0.045)
    d.rounded_rectangle(
        [inset, inset, size - 1 - inset, size - 1 - inset],
        radius=int(radius * 0.85),
        outline=ACCENT_DIM,
        width=max(2, size // 128),
    )

    # ---- briefcase glyph (drawn dim, behind) ----
    bw, bh = int(size * 0.46), int(size * 0.28)
    bx = (size - bw) // 2
    by = int(size * 0.47)
    line = max(3, size // 64)
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=line * 2,
                        outline=ACCENT_DIM, width=line)
    # handle
    hw, hh = int(bw * 0.36), int(size * 0.075)
    hx = size // 2 - hw // 2
    d.arc([hx, by - hh, hx + hw, by + hh], 180, 360, fill=ACCENT_DIM, width=line)
    # clasp
    cw = int(bw * 0.18)
    d.rectangle([size // 2 - cw // 2, by - line, size // 2 + cw // 2, by + line * 2],
                fill=ACCENT_DIM)

    # ---- "EE" monogram ----
    fs = int(size * 0.42)
    font = None
    for cand in ("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(cand, fs)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    text = "EE"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = int(size * 0.40) - th // 2 - bbox[1]
    d.text((tx, ty), text, font=font, fill=ACCENT)

    # ---- magnifying glass over the monogram ----
    lw = max(4, size // 36)
    lens_r = int(size * 0.335)
    cx, cy = size // 2, int(size * 0.44)
    d.ellipse([cx - lens_r, cy - lens_r, cx + lens_r, cy + lens_r],
              outline=ACCENT, width=lw)
    # handle: 45 degrees down-right
    import math
    ang = math.radians(45)
    sx = cx + (lens_r - lw // 2) * math.cos(ang)
    sy = cy + (lens_r - lw // 2) * math.sin(ang)
    ex = cx + (lens_r + size * 0.155) * math.cos(ang)
    ey = cy + (lens_r + size * 0.155) * math.sin(ang)
    d.line([sx, sy, ex, ey], fill=ACCENT, width=int(lw * 1.6))

    return img


def main() -> None:
    base = draw_base(SIZE)
    png_path = OUT / "icon.png"
    base.save(png_path)

    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    base.save(
        OUT / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
    )
    print(f"wrote {png_path} and {OUT / 'icon.ico'}")


if __name__ == "__main__":
    main()
