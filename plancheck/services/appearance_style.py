"""Sample a small reusable interior palette from the exterior photograph."""

from __future__ import annotations

import io

from PIL import Image


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))  # type: ignore[return-value]


def sample_palette(png: bytes) -> dict[str, str]:
    image = Image.open(io.BytesIO(png)).convert("RGB")
    image.thumbnail((96, 96))
    px = image.load()
    width, height = image.size
    pixels = [
        px[x, y]
        for x in range(width)
        for y in range(height)
        if 40 < max(px[x, y]) < 228 and (max(px[x, y]) - min(px[x, y])) > 8
    ]
    if not pixels:
        return {
            "primary": "#8a6a4e",
            "secondary": "#d8d0c4",
            "accent": "#5c6b70",
            "floor": "#c4b49a",
        }
    count = len(pixels)
    avg = tuple(sum(channel[i] for channel in pixels) // count for i in range(3))
    warm = sorted(pixels, key=lambda p: p[0] * 2 + p[1] - p[2])
    cool = sorted(pixels, key=lambda p: p[2] * 2 + p[1] - p[0])
    primary = warm[int(count * 0.72)]
    accent = cool[int(count * 0.72)]
    floor = _mix(avg, primary, 0.35)
    secondary = _mix(avg, (232, 226, 216), 0.55)
    return {
        "primary": _hex(primary),
        "secondary": _hex(secondary),
        "accent": _hex(accent),
        "floor": _hex(floor),
    }


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _bbox(image: Image.Image) -> tuple[int, int, int, int]:
    px = image.load()
    width, height = image.size
    xs: list[int] = []
    ys: list[int] = []
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            if max(px[x, y]) > 28:
                xs.append(x)
                ys.append(y)
    if not xs:
        return 0, 0, width, height
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def _score(crop: Image.Image, kind: str) -> float:
    px = crop.load()
    width, height = crop.size
    step = max(1, min(width, height) // 24)
    dark = 0
    count = 0
    luma_sum = 0.0
    luma_sq = 0.0
    red = 0
    blue = 0
    for y in range(0, height, step):
        for x in range(0, width, step):
            r, g, b = px[x, y]
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            count += 1
            luma_sum += luma
            luma_sq += luma * luma
            red += r
            blue += b
            if r + g + b < 42:
                dark += 1
    if not count:
        return -1
    mean = luma_sum / count
    variance = max(0.0, luma_sq / count - mean * mean)
    dark_frac = dark / count
    if dark_frac > 0.32 or mean < 38 or mean > 208:
        return -1
    warm = (red - blue) / count
    if kind == "wall":
        return variance + warm * 0.45 - dark_frac * 90
    return variance * 0.7 - abs(warm) * 0.15 - dark_frac * 90


def _best_patch(image: Image.Image, kind: str) -> Image.Image:
    width, height = image.size
    if width < 24 or height < 24:
        return image.resize((256, 256))
    x0, y0, x1, y1 = _bbox(image)
    box_w, box_h = x1 - x0, y1 - y0
    size = max(24, min(256, int(min(box_w, box_h) * (0.28 if kind == "roof" else 0.36))))
    y_start = y0 if kind == "roof" else y0 + int(box_h * 0.34)
    y_end = y0 + max(size, int(box_h * 0.42)) if kind == "roof" else y1 - size
    best = (-1.0, x0, y_start)
    step = max(6, size // 4)
    for y in range(y_start, max(y_start, y_end) + 1, step):
        for x in range(x0, max(x0, x1 - size), step):
            crop = image.crop((x, y, x + size, y + size))
            score = _score(crop, kind)
            if score > best[0]:
                best = (score, x, y)
    _, x, y = best
    return image.crop((x, y, x + size, y + size)).resize((256, 256), Image.Resampling.BICUBIC)


def extract_cladding(png: bytes) -> tuple[bytes, bytes]:
    image = Image.open(io.BytesIO(png)).convert("RGB")
    return _png(_best_patch(image, "wall")), _png(_best_patch(image, "roof"))
