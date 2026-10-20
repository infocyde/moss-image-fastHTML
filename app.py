"""MOSS Studio — a FastHTML front end for MOSS-Image (OpenMOSS-Team/MOSS-Image-SFT) on stable-diffusion.cpp.

    python app.py            → http://127.0.0.1:5001
"""
from __future__ import annotations

import contextlib
import io
import json
import random
import uuid

import uvicorn
from fasthtml.common import (H3, Button, Div, FileResponse, Form, HttpHeader, JSONResponse, Link, Meta, Pre,
                             Response, Script, Span, Title, UploadFile, fast_app)
from PIL import Image

from moss import config as C
from moss import ui
from moss.engine import Engine
from moss.enhancer import EnhancerError, enhance_caption, enhance_layout
from moss.imaging import decode_data_url, prepare_edit, to_data_url
from moss.jobs import JobManager, delete_image, list_gallery, safe_path
from moss.layout import LayoutError, compile_layout, snap16

C.ensure_dirs()
engine = Engine()
jobs = JobManager(engine)
announced: set[str] = set()


async def lifespan(_app):  # FastHTML takes a bare async generator
    await engine.start()
    yield
    engine.shutdown()


app, rt = fast_app(
    title="MOSS Studio", default_hdrs=False, pico=False, surreal=False, static_path=str(C.ROOT / "static"),
    lifespan=lifespan, canonical=False,
    hdrs=(Meta(charset="utf-8"), Meta(name="viewport", content="width=device-width, initial-scale=1"),
          Meta(name="color-scheme", content="dark"),
          Script(src="/htmx.min.js"),  # vendored so the app works offline
          Link(rel="stylesheet", href="/app.css"),
          Script(src="/app.js", defer=True), Script(src="/layout.js", defer=True)),
)

NO_SWAP = HttpHeader("HX-Reswap", "none")


def fail(msg: str):
    return ui.toast(msg, "error"), NO_SWAP


def trigger(_after: bool = False, **events):
    """Fire client events via HX-Trigger (works even with hx-swap="none"); ASCII-safe JSON.
    _after=True fires after the swap — needed when the handler removes the element that made the request."""
    name = "HX-Trigger-After-Settle" if _after else "HX-Trigger"
    return HttpHeader(name, json.dumps({f"moss:{k}": v for k, v in events.items()}))


# ---------------------------------------------------------------- page

@app.get("/")
def index():
    queue = [ui.job_card(j) for j in jobs.recent()]
    latest = jobs.recent(1)
    gal = list_gallery(60)
    return (
        Title("MOSS Studio"),
        Div(
            ui.header(engine),
            Div(
                Form(
                    Div(ui.controls(engine), ui.generate_bar(), cls="controls"),
                    Div(ui.tabs(), ui.pane_generate() if not latest else
                        Div(Div(ui.job_viewer(latest[0]), id="viewer"), cls="pane", id="pane-generate"),
                        ui.pane_edit(), ui.pane_layout(), cls="stage"),
                    id="gen", cls="gen-form", onsubmit="return false"),
                Div(
                    Div(H3("Queue"), Div(*queue, id="queue-list", cls="queue-list"), cls="panel"),
                    Div(Div(H3("Gallery"), cls="panel-head"),
                        Div(*[ui.gallery_thumb(g) for g in gal], id="gallery-grid", cls="gallery-grid"),
                        more_button(60) if len(gal) == 60 else "", cls="panel grow"),
                    cls="side"),
                cls="workspace"),
            Div(id="modal"), Div(id="toasts"),
            cls="app"),
    )


def more_button(offset: int):
    return Button("Load more", type="button", cls="btn xs ghost more", hx_get=f"/gallery/more?offset={offset}",
                  hx_swap="outerHTML")


@app.get("/gallery/more")
def gallery_more(offset: int = 0):
    gal = list_gallery(60, offset)
    return (Div(*[ui.gallery_thumb(g) for g in gal], id="gallery-grid", hx_swap_oob="beforeend"),
            more_button(offset + 60) if len(gal) == 60 else "")


# ---------------------------------------------------------------- engine

@app.get("/engine/status")
def engine_status():
    return ui.engine_pill(engine)


@app.get("/engine/modal")
def engine_modal():
    return ui.engine_modal(engine)


@app.get("/engine/log")
def engine_log():
    lines = list(engine.log)[-250:]
    return Pre("\n".join(lines) or "(no output yet)")


@app.post("/engine/model")
async def engine_model(diffusion_model: str = ""):
    if not diffusion_model or not (C.DIRS["diffusion"] / diffusion_model).exists():
        return fail("Model file not found")
    engine.settings.diffusion_model = diffusion_model
    engine.settings.save()
    await engine.start()
    return ui.toast(f"Switching to {C.quant_label(diffusion_model)} — reloading engine…")


@app.post("/engine/apply")
async def engine_apply(req):
    f = await req.form()
    s = engine.settings
    s.mode = f.get("mode", s.mode) if f.get("mode") in ("managed", "remote", "mock") else s.mode
    s.remote_url = (f.get("remote_url") or "").strip().rstrip("/")
    for key in ("diffusion_model", "text_encoder", "vae", "tokenizer"):
        if key in f:
            setattr(s, key, f.get(key) or "")
    for key in ("offload_to_cpu", "diffusion_fa", "vae_tiling", "rng_cpu"):
        setattr(s, key, key in f)
    s.extra_args = f.get("extra_args", "")
    s.save()
    await engine.start()
    quant = ui.quant_select(engine)
    quant.attrs["hx-swap-oob"] = "true"
    return ui.toast(f"Engine restarting ({s.mode})…"), quant, trigger(True, close={})


@app.post("/engine/stop")
async def engine_stop():
    await engine.stop()
    return ui.toast("Engine stopped")


# ---------------------------------------------------------------- loras

@app.get("/lora/row")
async def lora_row():
    if engine.state == "ready":
        with contextlib.suppress(Exception):
            await engine.refresh_caps()
    return ui.lora_row(engine.loras())


@app.post("/lora/rows")
def lora_rows(items: str = "[]"):
    try:
        items = json.loads(items)
    except ValueError:
        items = []
    return tuple(ui.lora_row(engine.loras(), l.get("path", ""), l.get("multiplier", 1.0)) for l in items) or ""


# ---------------------------------------------------------------- generate

def _num(f, key, default, lo, hi, cast=float):
    try:
        v = cast(f.get(key, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _load_init(init_id: str) -> Image.Image:
    kind, _, ref = init_id.partition(":")
    if kind == "gallery":
        p = safe_path(ref, ".png")
    elif kind == "upload":
        p = next(((C.DATA_DIR / "uploads").glob(f"{ref}.*")), None) if ref.isalnum() else None
    else:
        p = None
    if not p:
        raise ValueError("source image not found — upload it again")
    img = Image.open(p)
    img.load()
    return img


@app.post("/generate")
async def generate(req):
    f = await req.form()
    mode = f.get("mode", "generate")
    if engine.state != "ready":
        return fail(f"Engine is {engine.state}" + (f": {engine.message}" if engine.message else "") + " — open ⚙ Engine.")

    width = snap16(_num(f, "width", 1024, 256, 4096, int))
    height = snap16(_num(f, "height", 1024, 256, 4096, int))
    steps = _num(f, "steps", 50, 1, 150, int)
    cfg = round(_num(f, "cfg", 3.0, 0.0, 30.0), 3)
    shift = round(_num(f, "shift", 5.0, 0.1, 20.0), 3)
    batch = _num(f, "batch_count", 1, 1, 8, int)
    seed = _num(f, "seed", -1, -1, 2**31 - 1, int)
    if seed < 0:
        seed = random.randint(0, 2**31 - 1)
    sampler, scheduler = f.get("sampler") or "euler", f.get("scheduler") or "discrete"
    negative = (f.get("negative_prompt") or "").strip()
    user_prompt = (f.get("prompt") or "").strip()

    loras = []
    for path, w in zip(f.getlist("lora_path"), f.getlist("lora_weight")):
        if path:
            try:
                loras.append({"path": path, "multiplier": round(float(w), 3)})
            except ValueError:
                pass

    prompt, display, layout_draft, edit_info = user_prompt, user_prompt, None, None
    if mode == "layout":
        try:
            layout_draft = json.loads(f.get("layout_draft") or "{}")
            layout_draft["width"], layout_draft["height"] = width, height
            prompt = compile_layout(layout_draft)
        except (ValueError, LayoutError) as e:
            return fail(f"Layout: {e}")
        display = "[layout] " + layout_draft.get("summary", {}).get("caption", "")
    elif not prompt:
        return fail("Write a prompt first")

    # LoRA trigger words
    if "auto_trigger" in f and loras:
        meta = C.lora_meta()
        names = {l["path"]: l["name"] for l in engine.loras()}
        triggers = []
        for l in loras:
            m = meta.get(names.get(l["path"], "")) or meta.get(l["path"]) or {}
            t = (m.get("trigger") or "").strip()
            if t and t.lower() not in prompt.lower():
                triggers.append(t)
        if triggers:
            prompt = ", ".join(triggers) + (", " if mode != "layout" else " ") + prompt

    body = {
        "prompt": prompt, "negative_prompt": negative, "width": width, "height": height, "seed": seed,
        "batch_count": batch, "clip_skip": -1, "lora": loras,
        "sample_params": {"sample_method": sampler, "scheduler": scheduler, "sample_steps": steps,
                          "flow_shift": shift, "guidance": {"txt_cfg": cfg}},
        "preview": f.get("preview") or "proj",
        "preview_interval": _num(f, "preview_interval", 1, 1, 50, int),
        "output_format": "png", "embed_image_metadata": True,
    }
    slg = _num(f, "slg_scale", 0.0, 0.0, 20.0)
    if slg > 0:
        try:
            layers = [int(x) for x in (f.get("slg_layers") or "22").replace(" ", "").split(",") if x]
        except ValueError:
            return fail("SLG layers must be comma-separated integers")
        body["sample_params"]["guidance"]["slg"] = {
            "layers": layers, "scale": slg,
            "layer_start": _num(f, "slg_start", 0.01, 0, 1), "layer_end": _num(f, "slg_end", 0.2, 0, 1)}
    if "vae_tiling_req" in f:
        body["vae_tiling_params"] = {"enabled": True}

    if mode == "edit":
        init_id = f.get("init_id") or ""
        if not init_id:
            return fail("Load an image to edit first")
        try:
            init = _load_init(init_id)
            mask = decode_data_url(f.get("mask_image")) if f.get("mask_image") else None
            pads = tuple(_num(f, f"pad_{k}", 0, 0, 4096, int) for k in "ltrb")
            init, mask, width, height = prepare_edit(init, mask, f.get("edit_budget") or "1048576", pads)
        except (ValueError, OSError) as e:
            return fail(f"Edit: {e}")
        strength = round(_num(f, "strength", 0.6, 0.01, 1.0), 3)
        body.update(width=width, height=height, strength=strength, init_image=to_data_url(init),
                    mask_image=to_data_url(mask) if mask is not None else None)
        edit_info = {"source": init_id, "masked": mask is not None, "pad": list(pads)}

    params = {
        "mode": mode, "prompt": user_prompt, "prompt_sent": prompt, "prompt_display": display,
        "negative_prompt": negative, "width": width, "height": height, "steps": steps, "cfg": cfg, "shift": shift,
        "seed": seed, "batch_count": batch, "sampler": sampler, "scheduler": scheduler, "loras": loras,
        "model": engine.model_name(), "text_encoder": engine.settings.text_encoder, "engine": engine.settings.mode,
    }
    if body.get("strength") is not None and mode == "edit":
        params["strength"] = body["strength"]
        params["edit"] = edit_info
    if layout_draft:
        params["layout_draft"] = layout_draft

    job = await jobs.submit(body, params)
    out = [ui.job_card(job)]
    if job.status == "failed":
        out.append(ui.toast(job.error, "error"))
    out.append(Div(ui.job_viewer(job), id="viewer", hx_swap_oob="innerHTML"))
    return tuple(out)


# ---------------------------------------------------------------- jobs

def _gallery_oob(job):
    if job.status == "completed" and job.images and job.id not in announced:
        announced.add(job.id)
        return [Div(*[ui.gallery_thumb(g) for g in reversed(job.images)], id="gallery-grid", hx_swap_oob="afterbegin")]
    return None


@app.get("/jobs/{jid}/card")
def job_card(jid: str):
    job = jobs.get(jid)
    if not job:
        return ""
    return ui.job_card(job, _gallery_oob(job))


@app.get("/jobs/{jid}/viewer")
def job_viewer(jid: str):
    job = jobs.get(jid)
    if not job:
        return ui.empty_viewer()
    extra = _gallery_oob(job)
    return (ui.job_viewer(job), *extra) if extra else ui.job_viewer(job)


@app.get("/jobs/{jid}/preview")
def job_preview(jid: str):
    job = jobs.get(jid)
    if not job or not job.preview:
        return Response(status_code=404)
    return Response(job.preview, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.post("/jobs/{jid}/cancel")
async def job_cancel(jid: str):
    job = jobs.get(jid)
    if job:
        await jobs.cancel(job)
    return ui.toast("Cancel requested")


# ---------------------------------------------------------------- images / gallery

@app.get("/img/{gid:path}")
def img(gid: str, dl: str = ""):
    p = safe_path(gid, ".png")
    if not p:
        return Response("not found", status_code=404)
    return FileResponse(p, media_type="image/png", filename=p.name if dl else None)


@app.get("/thumb/{gid:path}")
def thumb(gid: str):
    p = safe_path(gid, ".thumb.jpg") or safe_path(gid, ".png")
    if not p:
        return Response("not found", status_code=404)
    return FileResponse(p, headers={"Cache-Control": "max-age=86400"})


@app.get("/gallery/view")
def gallery_view(gid: str):
    if not safe_path(gid, ".png"):
        return ui.toast("Image not found", "error")
    return ui.gallery_modal(gid)


@app.delete("/gallery/item")
def gallery_delete(gid: str):
    delete_image(gid)
    gone = Div(id=f"g-{gid.replace('/', '_')}", hx_swap_oob="delete")
    return gone, ui.toast("Deleted"), trigger(True, close={})


@app.post("/upload")
async def upload(file: UploadFile):
    data = await file.read()
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "not an image"}, status_code=400)
    uid = uuid.uuid4().hex
    img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
    img.save(C.DATA_DIR / "uploads" / f"{uid}.png")
    return JSONResponse({"id": f"upload:{uid}", "url": f"/uploads/{uid}", "w": img.width, "h": img.height})


@app.get("/uploads/{uid}")
def uploaded(uid: str):
    p = C.DATA_DIR / "uploads" / f"{uid}.png"
    if not uid.isalnum() or not p.exists():
        return Response("not found", status_code=404)
    return FileResponse(p)


# ---------------------------------------------------------------- enhancer

@app.post("/enhance")
async def enhance(kind: str = "caption", prompt: str = "", width: int = 1024, height: int = 1024):
    try:
        if kind == "layout":
            draft = await enhance_layout(prompt, snap16(width), snap16(height))
            return ui.toast(f"Layout: {len(draft['items'])} boxes — edit them on the canvas"), trigger(layout={"draft": draft})
        caption = await enhance_caption(prompt)
        return ui.toast("Prompt enhanced — Ctrl+Z in the box to undo"), trigger(prompt={"text": caption})
    except (EnhancerError, LayoutError) as e:
        return ui.toast(f"Enhancer: {e}", "error")


if __name__ == "__main__":
    print(f"MOSS Studio → http://{C.APP_HOST}:{C.APP_PORT}  (engine: {engine.settings.mode})")
    uvicorn.run(app, host=C.APP_HOST, port=C.APP_PORT, log_level="warning")
