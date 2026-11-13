#!/usr/bin/env python3
"""Turn site/originals/ into the web-sized images under site/public/assets/img/.

    python3 site/tools/build_images.py

Needs Pillow and numpy. Run it again whenever a photo in originals/ changes or
a new one is added; everything in public/assets/img/ is an output of this file
and can be deleted and rebuilt.

The originals are the full-resolution files as downloaded from the old Wix
site on 2026-11-12. They are never modified.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps

SITE = Path(__file__).resolve().parent.parent
SRC = SITE / "originals"
OUT = SITE / "public" / "assets" / "img"

# The studio portraits carry the name and instrument as part of the picture,
# top right. On the page those are real text under each photo, so the lettering
# is painted out here. Each box is (left, top, right, bottom) as fractions of
# the picture, drawn around the lettering and clear of the person.
MEMBERS = {
    "max-stoklasa": (0.53, 0.08, 0.98, 0.22),
    "tomas-becka": (0.51, 0.08, 0.93, 0.22),
    "rudy-horvat": (0.49, 0.10, 0.92, 0.235),
    "marek-krygel": (0.49, 0.135, 0.94, 0.268),
    "adela-schlesingerova": (0.28, 0.04, 0.97, 0.168),
    "katerina-eichlerova": (0.53, 0.04, 0.94, 0.235),
    "petr-moczek": (0.50, 0.11, 0.95, 0.24),
    "tereza-schvanova": (0.36, 0.09, 0.96, 0.218),
}

GALLERY = [
    "live-01", "live-02", "live-03", "live-04", "live-05", "live-06", "live-07",
    "live-08", "live-09", "live-10", "bubenik", "klub", "zpevaci-detail", "selfie",
]


def save_webp(image: Image.Image, name: str, *, quality: int = 80) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "WEBP", quality=quality, method=6)
    print(f"  {name:38} {image.size[0]:5}x{image.size[1]:<5} {path.stat().st_size / 1024:6.0f} KB")


def fit_width(image: Image.Image, width: int) -> Image.Image:
    if image.width <= width:
        return image.copy()
    return image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)


def fit_long_edge(image: Image.Image, edge: int) -> Image.Image:
    scale = edge / max(image.size)
    if scale >= 1:
        return image.copy()
    return image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)


def paint_out_lettering(image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    """Replace dark lettering inside `box` with the studio backdrop behind it.

    The backdrop is a smooth light gradient, so a wide median over the box is
    the backdrop without the letters. Only pixels clearly darker than that are
    replaced, which leaves the paper grain everywhere else untouched.
    """
    w, h = image.size
    left, top, right, bottom = (round(box[0] * w), round(box[1] * h), round(box[2] * w), round(box[3] * h))
    pad = round(0.03 * w)
    region = (max(0, left - pad), max(0, top - pad), min(w, right + pad), min(h, bottom + pad))
    patch = image.crop(region)

    backdrop = patch.filter(ImageFilter.MedianFilter(size=2 * round(0.022 * w) + 1))
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(radius=0.006 * w))

    darker = np.asarray(ImageChops.subtract(backdrop.convert("L"), patch.convert("L")), dtype=np.uint8)
    mask = Image.fromarray(((darker > 5) * 255).astype(np.uint8))
    # Only inside the box itself, never in the padding around it.
    inner = Image.new("L", patch.size, 0)
    inner.paste(255, (left - region[0], top - region[1], right - region[0], bottom - region[1]))
    mask = ImageChops.multiply(mask, inner)
    mask = mask.filter(ImageFilter.MaxFilter(size=2 * round(0.004 * w) + 1))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=0.0015 * w))

    cleaned = image.copy()
    cleaned.paste(Image.composite(backdrop, patch, mask), region[:2])
    return cleaned


def build_members() -> None:
    print("members")
    for name, box in MEMBERS.items():
        portrait = Image.open(SRC / "members" / f"{name}.jpg").convert("RGB")
        portrait = fit_width(portrait, 1000)
        portrait = paint_out_lettering(portrait, box)
        save_webp(fit_width(portrait, 900), f"members/{name}.webp", quality=80)
        save_webp(fit_width(portrait, 480), f"members/{name}-480.webp", quality=78)


def build_hero() -> None:
    print("hero and group")
    hall = Image.open(SRC / "live" / "ples-sal.jpg").convert("RGB")
    save_webp(fit_width(hall, 1620), "hero.webp", quality=76)
    save_webp(fit_width(hall, 900), "hero-900.webp", quality=72)

    group = Image.open(SRC / "group.png").convert("RGB")
    # The studio shot has wide white margins; trim to the people plus a little air.
    ink = ImageOps.invert(group.convert("L")).point(lambda v: 255 if v > 18 else 0)
    left, top, right, bottom = ink.getbbox()
    air = round(0.02 * group.width)
    group = group.crop((max(0, left - air), max(0, top - air),
                        min(group.width, right + air), min(group.height, bottom + air)))
    save_webp(fit_width(group, 1200), "group.webp", quality=82)
    save_webp(fit_width(group, 700), "group-700.webp", quality=80)

    # Link previews (Facebook, Messenger, WhatsApp) want a 1200x630 JPEG.
    card = Image.open(SRC / "live" / "zpevaci-detail.jpg").convert("RGB")
    card = ImageOps.fit(card, (1200, 630), Image.LANCZOS, centering=(0.5, 0.4))
    card.save(OUT / "og.jpg", "JPEG", quality=84, optimize=True, progressive=True)
    print(f"  {'og.jpg':38} 1200x630   {(OUT / 'og.jpg').stat().st_size / 1024:6.0f} KB")


def trim_black_bars(photo: Image.Image) -> Image.Image:
    """Cut off the pure-black side bars some of the live shots were exported with.

    A bar is a run of edge columns that are black from top to bottom. A dark
    corner of a stage is not one: it still has light somewhere in the column.
    """
    grey = np.asarray(photo.convert("L"))
    lit = np.nonzero((grey.mean(axis=0) > 6) | (grey.max(axis=0) > 40))[0]
    if len(lit) == 0:
        return photo
    left, right = int(lit[0]), int(lit[-1]) + 1
    if left < 0.01 * photo.width and photo.width - right < 0.01 * photo.width:
        return photo
    return photo.crop((left, 0, right, photo.height))


def build_gallery() -> None:
    print("gallery")
    for name in GALLERY:
        photo = Image.open(SRC / "live" / f"{name}.jpg").convert("RGB")
        photo = trim_black_bars(photo)
        save_webp(fit_long_edge(photo, 1600), f"gallery/{name}.webp", quality=80)
        save_webp(fit_long_edge(photo, 720), f"gallery/{name}-720.webp", quality=74)


def trim_alpha(image: Image.Image, air: int) -> Image.Image:
    left, top, right, bottom = image.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    return image.crop((max(0, left - air), max(0, top - air),
                       min(image.width, right + air), min(image.height, bottom + air)))


def build_brand() -> None:
    print("brand")
    dark = trim_alpha(Image.open(SRC / "logo-dark.png").convert("RGBA"), air=24)
    save_webp(fit_width(dark, 1100), "logo-dark.webp", quality=90)
    save_webp(fit_width(dark, 440), "logo-dark-440.webp", quality=90)

    light = trim_alpha(Image.open(SRC / "logo-light.png").convert("RGBA"), air=24)
    save_webp(fit_width(light, 900), "logo-light.webp", quality=90)

    # Icons: the band's own favicon artwork, centred on a square of its black.
    art = Image.open(SRC / "favicon-source.png").convert("RGB")
    square = Image.new("RGB", (art.width, art.width), art.getpixel((2, 2)))
    square.paste(art, (0, (art.width - art.height) // 2))
    for size, name in ((512, "icon-512.png"), (180, "apple-touch-icon.png"), (48, "favicon-48.png")):
        square.resize((size, size), Image.LANCZOS).save(OUT / name, "PNG", optimize=True)
        print(f"  {name:38} {size:5}x{size:<5} {(OUT / name).stat().st_size / 1024:6.0f} KB")


def build_refs() -> None:
    print("references")
    for path in sorted((SRC / "refs").glob("*.png")):
        logo = Image.open(path).convert("RGBA")
        # These are small screenshots; keep them lossless and at their own size.
        target = OUT / "refs" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        logo.save(target, "PNG", optimize=True)
        print(f"  refs/{path.name:33} {logo.width:5}x{logo.height:<5} {target.stat().st_size / 1024:6.0f} KB")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    build_brand()
    build_hero()
    build_members()
    build_gallery()
    build_refs()
