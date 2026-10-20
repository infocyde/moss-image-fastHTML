"""MOSS-Image layout prompts.

The editor works in a readable *draft* (top-left origin, xyxy pixels, with width/height).
`compile_layout` converts it to the model-facing form (abs_centralized + yxyx) — a port of
OpenMOSS/MOSS-Image skills/moss-image-prompt-enhancer/scripts/compile_prompt.py (Apache-2.0),
except boxes are clamped to the canvas instead of rejected, since the editor can nudge them.
"""
from __future__ import annotations

import json
import math

LABELS = ("object", "character", "text")
CANVASES = ("single", "multi_panel", "collage")
RATIOS = ("1:8", "1:4", "1:3", "1:2", "9:16", "2:3", "3:4", "1:1", "4:3", "3:2", "16:9", "2:1", "3:1", "4:1", "8:1")
PIXELS = (262144, 1048576, 1572864, 2097152, 4194304)


def fit_size(pixels: int, ratio: str | float) -> tuple[int, int]:
    """Same as MOSS gradio_presets.fit_size: dims for a pixel budget + aspect, multiples of 16."""
    if isinstance(ratio, str):
        w, h = map(float, ratio.split(":"))
        ratio = w / h
    width, height = math.sqrt(pixels * ratio), math.sqrt(pixels / ratio)
    return tuple(max(16, math.floor(edge / 16 + 0.5) * 16) for edge in (width, height))  # type: ignore


def snap16(v: float) -> int:
    return max(16, int(round(v / 16)) * 16)


class LayoutError(ValueError):
    pass


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise LayoutError(msg)


def _nonempty(v, where: str) -> str:
    _need(isinstance(v, str) and bool(v.strip()), f"{where} must be non-empty text")
    return v


def normalize_draft(draft: dict) -> dict:
    """Validate + clean an editor/LLM draft. Returns a clean draft (still xyxy/top-left)."""
    _need(isinstance(draft, dict), "layout must be a JSON object")
    w, h = int(draft.get("width", 1024)), int(draft.get("height", 1024))
    _need(w > 0 and h > 0 and w % 16 == 0 and h % 16 == 0, "width/height must be positive multiples of 16")
    summary = draft.get("summary") or {}
    _need(isinstance(summary, dict), "summary must be an object")
    out_summary = {"caption": _nonempty(summary.get("caption", ""), "summary.caption").strip()}
    meta = [m.strip() for m in summary.get("meta") or [] if isinstance(m, str) and m.strip()]
    if meta:
        out_summary["meta"] = meta
    canvas = summary.get("canvas") or "single"
    out_summary["canvas"] = canvas if canvas in CANVASES else "single"
    palette = [p for p in summary.get("palette") or [] if isinstance(p, str) and p.strip()]
    if palette:
        out_summary["palette"] = palette

    items = draft.get("items") or []
    _need(isinstance(items, list) and items, "add at least one box")
    clean = []
    for i, it in enumerate(items):
        where = f"box {i + 1}"
        _need(isinstance(it, dict), f"{where} must be an object")
        label = it.get("label", "object")
        _need(label in LABELS, f"{where}: label must be object, character or text")
        bbox = it.get("bbox")
        _need(isinstance(bbox, list) and len(bbox) == 4, f"{where}: bbox must be [x1,y1,x2,y2]")
        x1, y1, x2, y2 = (float(v) for v in bbox)
        x1, x2 = sorted((max(0.0, min(w, x1)), max(0.0, min(w, x2))))
        y1, y2 = sorted((max(0.0, min(h, y1)), max(0.0, min(h, y2))))
        _need(x2 - x1 >= 1 and y2 - y1 >= 1, f"{where} is too small")
        item = {"label": label, "caption": _nonempty(it.get("caption", ""), f"{where} caption").strip()}
        txt = it.get("text")
        if label == "text":
            _need(isinstance(txt, str) and txt.strip() != "", f"{where}: text boxes need the literal text")
        if isinstance(txt, str) and txt.strip():
            item["text"] = txt
        for key in ("tags", "palette"):
            vals = [v for v in it.get(key) or [] if isinstance(v, str) and v.strip()]
            if vals:
                item[key] = vals
        item["bbox"] = [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)]
        clean.append(item)
    return {"width": w, "height": h, "bbox_coord_space": "abs", "bbox_format": "xyxy",
            "summary": out_summary, "items": clean}


def compile_layout(draft: dict) -> str:
    """Draft -> single-line MOSS prompt JSON (abs_centralized, yxyx)."""
    d = normalize_draft(draft)
    w, h = d["width"], d["height"]
    items = []
    for it in d["items"]:
        x1, y1, x2, y2 = it["bbox"]
        box = [math.floor(round(y1, 9)) - h // 2, math.floor(round(x1, 9)) - w // 2,
               math.ceil(round(y2, 9)) - h // 2, math.ceil(round(x2, 9)) - w // 2]
        items.append({**{k: v for k, v in it.items() if k != "bbox"}, "bbox": box})
    out = {"summary": d["summary"], "items": items,
           "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"}
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def parse_llm_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM reply (handles ``` fences and chatter)."""
    t = text.strip()
    if "```" in t:
        parts = t.split("```")
        for p in parts[1::2]:
            p = p.split("\n", 1)[1] if p.lstrip().lower().startswith("json") else p
            try:
                return json.loads(p.strip())
            except ValueError:
                continue
    start = t.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except ValueError:
                        break
        start = t.find("{", start + 1)
    raise LayoutError("the model did not return JSON")
