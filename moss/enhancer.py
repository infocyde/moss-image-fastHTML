"""Prompt / layout enhancer using any OpenAI-compatible endpoint (LM Studio by default).

The instructions are condensed from OpenMOSS/MOSS-Image skills/moss-image-prompt-enhancer (Apache-2.0).
"""
from __future__ import annotations

import json
import re

import httpx

from . import config as C
from .layout import normalize_draft, parse_llm_json

CAPTION_SYSTEM = """You expand short image ideas into a single detailed caption for the MOSS-Image text-to-image model.

Rules:
- Preserve the user's subjects, counts, relationships, medium, style, exclusions and any wording that must appear in the image.
- Describe visible choices: subject and action, appearance, setting, camera/framing, medium, lighting, materials, palette and mood. Add detail where it makes the image more specific.
- Avoid redundant quality tags ("masterpiece, 8k"), unrequested style changes and invisible process notes.
- Keep a minimalist brief minimalist.
- Any text to render in the image goes in double quotes, verbatim, in its original language, with real line breaks where lines should break. Write the actual copy, never placeholders.
- Write cohesive prose (one to three paragraphs). Describe spatial relations in words; no coordinates, no JSON.
- Default to English for the description unless the user writes in another language.

Reply with the caption only — no preface, no quotes around the whole thing, no markdown."""

LAYOUT_SYSTEM = """You turn an image idea into a spatial layout draft for the MOSS-Image model.

Return ONE JSON object and nothing else, with exactly these keys:
{
  "width": W, "height": H,
  "bbox_coord_space": "abs", "bbox_format": "xyxy",
  "summary": {"meta": ["genre/medium tags"], "canvas": "single" | "multi_panel" | "collage",
              "caption": "global scene, medium, palette, lighting, mood"},
  "items": [
    {"label": "object" | "character" | "text",
     "caption": "visible appearance; for text: typography, colour, weight, surface",
     "text": "exact visible characters (required for label text; use \\n for line breaks)",
     "bbox": [x_min, y_min, x_max, y_max]}
  ]
}

Rules:
- Boxes are actual pixels from the canvas top-left: 0 <= x <= width, 0 <= y <= height. Use the width/height given.
- Use boxes for coherent visible units; split only when independent placement matters. Overlap is fine.
- A box is a placement annotation, not a border or panel to draw.
- Establish reading order and prominence for designed images (posters, covers, UI); make text boxes big enough to be legible.
- Write the real copy, never placeholders. Preserve any wording the user gave verbatim.
- Keep descriptions of JSON/boxes out of the captions.

Example for 1024x1024, "minimalist travel poster, EXPLORE":
{"width":1024,"height":1024,"bbox_coord_space":"abs","bbox_format":"xyxy","summary":{"meta":["poster"],"canvas":"single","caption":"A minimalist travel poster with a cream background, a blue mountain illustration, and the title EXPLORE at the top."},"items":[{"label":"text","caption":"Large dark-blue uppercase title centered at the top.","text":"EXPLORE","bbox":[128,96,896,224]},{"label":"object","caption":"A flat blue mountain illustration in the lower center.","bbox":[224,320,800,896]}]}"""


class EnhancerError(RuntimeError):
    pass


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


async def _chat(system: str, user: str) -> str:
    headers = {"Authorization": f"Bearer {C.ENHANCER_API_KEY}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=4.0), headers=headers) as client:
        model = C.ENHANCER_MODEL
        try:
            if not model:
                r = await client.get(f"{C.ENHANCER_URL}/models")
                r.raise_for_status()
                models = [m["id"] for m in r.json().get("data", []) if "embed" not in m["id"].lower()]
                if not models:
                    raise EnhancerError("no chat model loaded in the enhancer endpoint")
                model = models[0]
            r = await client.post(f"{C.ENHANCER_URL}/chat/completions", json={
                "model": model, "temperature": 0.7, "max_tokens": 2000,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            })
            r.raise_for_status()
        except httpx.ConnectError as e:
            raise EnhancerError(f"can't reach {C.ENHANCER_URL} — start LM Studio's server or set ENHANCER_URL") from e
        except httpx.HTTPStatusError as e:
            raise EnhancerError(f"enhancer returned {e.response.status_code}: {e.response.text[:200]}") from e
        except httpx.HTTPError as e:
            raise EnhancerError(f"enhancer error: {e.__class__.__name__}") from e
        return _strip_think(r.json()["choices"][0]["message"]["content"])


async def enhance_caption(idea: str) -> str:
    if not idea.strip():
        raise EnhancerError("write a short idea in the prompt box first")
    out = await _chat(CAPTION_SYSTEM, idea.strip())
    return out.strip().strip('"').strip()


async def enhance_layout(idea: str, width: int, height: int) -> dict:
    if not idea.strip():
        raise EnhancerError("write a short idea in the prompt box first")
    user = f"Canvas: width={width}, height={height}.\nIdea: {idea.strip()}"
    raw = await _chat(LAYOUT_SYSTEM, user)
    draft = parse_llm_json(raw)
    draft["width"], draft["height"] = width, height
    return normalize_draft(draft)
