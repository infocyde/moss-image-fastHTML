"""A fake sd-server that speaks the native /sdcpp/v1 API, so the UI runs with no GPU or models.

    python -m moss.mock_server --port 7861

It honours the same request fields the real server does (size, steps, seed, batch, init_image,
mask_image, strength, lora, preview) and renders deterministic procedural art so you can
check every UI path: progress, previews, cancel, img2img, inpaint masks, LoRA plumbing.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import base64
import io
import math
import random
import time
import uuid
from pathlib import Path

import uvicorn
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

ARGS: argparse.Namespace
JOBS: dict[str, dict] = {}
QUEUE: asyncio.Queue | None = None


def _decode(data: str | None) -> Image.Image | None:
    if not data:
        return None
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    img = Image.open(io.BytesIO(base64.b64decode(data)))
    img.load()
    return img


def _b64png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _font(size: int):
    for name in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(body: dict, seed: int) -> Image.Image:
    w, h = int(body["width"]), int(body["height"])
    rnd = random.Random(seed)
    small = (max(16, w // 8), max(16, h // 8))
    base = Image.new("RGB", small)
    px = base.load()
    blobs = [(rnd.random(), rnd.random(), rnd.random() * 0.5 + 0.2,
              tuple(rnd.randint(30, 255) for _ in range(3))) for _ in range(6)]
    for y in range(small[1]):
        for x in range(small[0]):
            u, v = x / small[0], y / small[1]
            r = g = b = 0.0
            tw = 0.0
            for bx, by, rad, col in blobs:
                d = math.hypot(u - bx, v - by) / rad
                wgt = math.exp(-d * d * 2)
                r += col[0] * wgt
                g += col[1] * wgt
                b += col[2] * wgt
                tw += wgt
            tw = max(tw, 1e-3)
            px[x, y] = (int(r / tw), int(g / tw), int(b / tw))
    img = base.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(2))

    init = _decode(body.get("init_image"))
    if init is not None:
        init = init.convert("RGB").resize((w, h))
        strength = float(body.get("strength", 0.75))
        img = Image.blend(init, img, max(0.0, min(1.0, strength)))
        mask = _decode(body.get("mask_image"))
        if mask is not None:
            img = Image.composite(img, init, mask.convert("L").resize((w, h)))

    d = ImageDraw.Draw(img, "RGBA")
    pad = max(12, w // 48)
    loras = ", ".join(f"{Path(l.get('path', '?')).stem}×{l.get('multiplier', 1)}" for l in body.get("lora") or [])
    sp = body.get("sample_params") or {}
    lines = [
        "MOCK ENGINE",
        (body.get("prompt") or "")[:160],
        f"{w}×{h}  seed {seed}  steps {sp.get('sample_steps', '?')}  cfg {(sp.get('guidance') or {}).get('txt_cfg', '?')}",
    ]
    if init is not None:
        lines.append(f"img2img strength {body.get('strength')}" + ("  + mask" if body.get("mask_image") else ""))
    if loras:
        lines.append("LoRA: " + loras)
    f_big, f_small = _font(max(14, w // 28)), _font(max(11, w // 56))
    y = pad
    for i, line in enumerate(lines):
        f = f_big if i == 0 else f_small
        for chunk in [line[j:j + 70] for j in range(0, len(line), 70)] or [""]:
            bbox = d.textbbox((pad, y), chunk, font=f)
            d.rectangle((bbox[0] - 6, bbox[1] - 4, bbox[2] + 6, bbox[3] + 4), fill=(0, 0, 0, 120))
            d.text((pad, y), chunk, font=f, fill=(255, 255, 255, 235))
            y = bbox[3] + 10
    return img


async def worker() -> None:
    assert QUEUE is not None
    while True:
        jid = await QUEUE.get()
        job = JOBS.get(jid)
        if not job or job["status"] == "cancelled":
            continue
        job["status"], job["started"] = "generating", int(time.time())
        body = job["_body"]
        sp = body.get("sample_params") or {}
        steps = int(sp.get("sample_steps") or 20)
        if body.get("init_image"):
            steps = max(1, int(steps * float(body.get("strength", 0.75))))
        seed = int(body.get("seed", 42))
        if seed < 0:
            seed = random.randint(0, 2**31 - 1)
        images = []
        try:
            for b in range(int(body.get("batch_count", 1))):
                final = await asyncio.to_thread(render, body, seed + b)
                small = final.resize((max(16, final.width // 8), max(16, final.height // 8)))
                rnd = random.Random(seed + b)
                noise = Image.effect_noise(small.size, 90).convert("L")
                noise = Image.merge("RGB", [noise.point(lambda v, o=rnd.randint(0, 80): (v + o) % 256)
                                            for _ in range(3)])
                for s in range(1, steps + 1):
                    if job["status"] == "cancelled":
                        raise asyncio.CancelledError
                    await asyncio.sleep(ARGS.step_delay)
                    if body.get("preview", "none") != "none":
                        frame = Image.blend(noise, small, s / steps)
                        job["preview"] = {"pass": b + 1, "step": s, "total_steps": steps,
                                          "b64_json": _b64png(frame)}
                images.append({"index": b, "b64_json": _b64png(final)})
            job.update(status="completed", completed=int(time.time()),
                       result={"output_format": "png", "images": images})
        except asyncio.CancelledError:
            job.update(status="cancelled", completed=int(time.time()),
                       error={"code": "cancelled", "message": "job cancelled by client"})
        except Exception as e:  # noqa: BLE001
            job.update(status="failed", completed=int(time.time()),
                       error={"code": "generation_failed", "message": str(e)})
        job.pop("preview", None)


def public(job: dict) -> dict:
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    if job["status"] == "queued":
        queued = [j for j in JOBS.values() if j["status"] == "queued"]
        out["queue_position"] = sorted(queued, key=lambda j: j["created"]).index(job) + 1
    else:
        out["queue_position"] = 0
    return out


async def capabilities(_: Request) -> JSONResponse:
    lora_dir = Path(ARGS.lora_dir)
    loras = []
    if lora_dir.exists():
        for p in sorted(lora_dir.rglob("*")):
            if p.suffix.lower() in (".gguf", ".safetensors", ".pt", ".pth"):
                loras.append({"name": p.stem, "path": p.relative_to(lora_dir).as_posix()})
    return JSONResponse({
        "model": {"name": ARGS.model_name, "stem": Path(ARGS.model_name).stem, "path": ARGS.model_name},
        "current_mode": "img_gen",
        "supported_modes": ["img_gen"],
        "samplers": ["euler", "euler_a", "heun", "dpm2", "dpm++2m", "lcm"],
        "schedulers": ["discrete", "karras", "exponential", "sgm_uniform", "simple"],
        "loras": loras,
        "preview_modes": ["none", "proj", "tae", "vae"],
        "features_by_mode": {"img_gen": {"init_image": True, "mask_image": True, "lora": True,
                                         "preview": True, "cancel_queued": True, "cancel_generating": True}},
        "limits": {"min_width": 64, "max_width": 4096, "min_height": 64, "max_height": 4096,
                   "max_batch_count": 8, "max_queue_size": 32},
        "mock": True,
    })


async def img_gen(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    w, h = body.get("width", 1024), body.get("height", 1024)
    if not body.get("prompt") or w % 16 or h % 16:
        return JSONResponse({"error": "invalid generation parameters"}, status_code=400)
    jid = "job_" + uuid.uuid4().hex[:12]
    JOBS[jid] = {"id": jid, "kind": "img_gen", "status": "queued", "created": int(time.time()),
                 "started": None, "completed": None, "result": None, "error": None, "_body": body}
    assert QUEUE is not None
    await QUEUE.put(jid)
    print(f"[mock] queued {jid}: {w}x{h} '{body['prompt'][:60]}'", flush=True)
    return JSONResponse({"id": jid, "kind": "img_gen", "status": "queued",
                         "created": JOBS[jid]["created"], "poll_url": f"/sdcpp/v1/jobs/{jid}"}, status_code=202)


async def job_status(request: Request) -> JSONResponse:
    job = JOBS.get(request.path_params["jid"])
    if not job:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(public(job))


async def job_cancel(request: Request) -> JSONResponse:
    job = JOBS.get(request.path_params["jid"])
    if not job:
        return JSONResponse({"error": "not found"}, status_code=404)
    if job["status"] in ("completed", "failed", "cancelled"):
        return JSONResponse({"error": "already finished"}, status_code=409)
    if job["status"] == "queued":
        job.update(status="cancelled", completed=int(time.time()),
                   error={"code": "cancelled", "message": "job cancelled by client"})
    else:
        job["status"] = "cancelled"
    return JSONResponse(public(job))


@contextlib.asynccontextmanager
async def lifespan(_app):
    global QUEUE
    QUEUE = asyncio.Queue()
    print(f"[mock] loading '{ARGS.model_name}' (simulated)…", flush=True)
    await asyncio.sleep(ARGS.load_delay)
    task = asyncio.create_task(worker())
    print("[mock] ready", flush=True)
    yield
    task.cancel()


def main() -> None:
    global ARGS
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=7861)
    p.add_argument("--lora-dir", default="models/loras")
    p.add_argument("--model-name", default="mock-moss")
    p.add_argument("--step-delay", type=float, default=0.05)
    p.add_argument("--load-delay", type=float, default=1.5)
    ARGS = p.parse_args()
    app = Starlette(routes=[
        Route("/sdcpp/v1/capabilities", capabilities),
        Route("/sdcpp/v1/img_gen", img_gen, methods=["POST"]),
        Route("/sdcpp/v1/jobs/{jid}", job_status),
        Route("/sdcpp/v1/jobs/{jid}/cancel", job_cancel, methods=["POST"]),
    ], lifespan=lifespan)
    uvicorn.run(app, host="127.0.0.1", port=ARGS.port, log_level="warning")


if __name__ == "__main__":
    main()
