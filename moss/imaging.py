"""Image prep for edit mode: decode uploads, fit to a working resolution, masks, outpaint padding."""
from __future__ import annotations

import base64
import io

from PIL import Image, ImageFilter, ImageOps

from .layout import fit_size, snap16


def decode_data_url(data: str) -> Image.Image:
    if not data:
        raise ValueError("no image")
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    img = Image.open(io.BytesIO(base64.b64decode(data)))
    img.load()
    return img


def to_data_url(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    mime = "image/png" if fmt.upper() == "PNG" else f"image/{fmt.lower()}"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def working_size(src_w: int, src_h: int, budget: str) -> tuple[int, int]:
    """budget: 'original' (snap to 16) or a pixel count like '1048576'."""
    if budget == "original":
        return snap16(src_w), snap16(src_h)
    return fit_size(int(budget), src_w / src_h)


def mask_has_paint(mask: Image.Image | None) -> bool:
    return mask is not None and mask.convert("L").getextrema()[1] > 127


def prepare_edit(init: Image.Image, mask: Image.Image | None, budget: str,
                 pad: tuple[int, int, int, int] = (0, 0, 0, 0), feather: int = 24,
                 grow: int = 8) -> tuple[Image.Image, Image.Image | None, int, int]:
    """Returns (init_rgb, mask_L or None, width, height), all at the generation size.

    pad = (left, top, right, bottom) in *source* pixels for outpainting. The padded area is
    filled with a blurred edge-stretch so img2img has colour to start from, and it is
    added to the mask (white = regenerate)."""
    init = ImageOps.exif_transpose(init).convert("RGB")
    sw, sh = init.size
    if mask is not None:
        mask = mask.convert("L").resize((sw, sh), Image.NEAREST)
        if not mask_has_paint(mask):
            mask = None

    l, t, r, b = (max(0, int(v)) for v in pad)
    if l or t or r or b:
        cw, ch = sw + l + r, sh + t + b
        # edge-stretch fill: scale the image up to the canvas, blur hard, then paste original
        fill = init.resize((cw, ch), Image.BILINEAR).filter(ImageFilter.GaussianBlur(max(cw, ch) / 24))
        fill.paste(init, (l, t))
        new_mask = Image.new("L", (cw, ch), 255)
        keep = Image.new("L", (sw, sh), 0) if mask is None else mask
        # pull the keep-region in by `feather` px so the seam is regenerated too
        inner = Image.new("L", (cw, ch), 255)
        inner.paste(0, (l + (feather if l else 0), t + (feather if t else 0),
                        l + sw - (feather if r else 0), t + sh - (feather if b else 0)))
        new_mask.paste(keep, (l, t))
        new_mask = _lighter(inner, new_mask)
        init, mask, sw, sh = fill, new_mask, cw, ch

    w, h = working_size(sw, sh, budget)
    init = init.resize((w, h), Image.LANCZOS)
    if mask is not None:
        mask = mask.resize((w, h), Image.BILINEAR)
        if grow:
            mask = mask.filter(ImageFilter.MaxFilter(min(grow, 8) * 2 + 1))
        mask = mask.point(lambda v: 255 if v > 32 else 0)
    return init, mask, w, h


def _lighter(a: Image.Image, b: Image.Image) -> Image.Image:
    from PIL import ImageChops
    return ImageChops.lighter(a, b)


def thumbnail(png_bytes: bytes, size: int = 320) -> bytes:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    img.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return buf.getvalue()
