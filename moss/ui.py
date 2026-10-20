"""FastHTML components."""
from __future__ import annotations

import json
from pathlib import Path

from fasthtml.common import (A, Button, Details, Div, Form, H2, H3, Img, Input, Label, NotStr, Option,
                             P, Select, Small, Span, Summary, Textarea)

from . import config as C
from .engine import Engine
from .jobs import Job, read_meta
from .layout import PIXELS, RATIOS

NEG_SUGGEST = "worst quality, bad anatomy, watermark, jpeg artifact"


def icon(name: str) -> NotStr:
    paths = {
        "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"/>',
        "dice": '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="9" cy="9" r="1.2" fill="currentColor"/><circle cx="15" cy="15" r="1.2" fill="currentColor"/><circle cx="15" cy="9" r="1.2" fill="currentColor"/><circle cx="9" cy="15" r="1.2" fill="currentColor"/>',
        "recycle": '<path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3"/><path d="M18 3v4h-4M6 21v-4h4"/>',
        "swap": '<path d="M7 4v16M7 20l-3-3M7 20l3-3M17 20V4M17 4l-3 3M17 4l3 3"/>',
        "x": '<path d="M6 6l12 12M18 6L6 18"/>',
        "gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
        "upload": '<path d="M12 16V4M12 4l-4 4M12 4l4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
        "brush": '<path d="M18.4 2.6a2 2 0 0 1 2.9 2.9L11 15.8 8.2 13z"/><path d="M8 14c-2 0-3.5 1.5-3.5 3.5 0 1.2-.8 2-2 2.5 1 .7 2.3 1 3.5 1C8.5 21 10 19 10 17z"/>',
        "eraser": '<path d="M20 20H8l-4.3-4.3a1.5 1.5 0 0 1 0-2.1L13.6 3.7a1.5 1.5 0 0 1 2.1 0l4.6 4.6a1.5 1.5 0 0 1 0 2.1L11 20"/>',
        "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
        "plus": '<path d="M12 5v14M5 12h14"/>',
        "download": '<path d="M12 4v12M12 16l-4-4M12 16l4-4M4 20h16"/>',
        "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
        "layout": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12"/>',
        "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 17l-5-5-9 8"/>',
    }
    return NotStr(f'<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                  f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths[name]}</svg>')


# ---------------- header / engine ----------------

def engine_pill(engine: Engine):
    labels = {"ready": "Ready", "starting": "Loading", "error": "Error", "stopped": "Stopped"}
    mode = {"managed": "local", "remote": "remote", "mock": "mock"}[engine.settings.mode]
    title = engine.message or engine.model_name()
    return Button(Span(cls=f"dot {engine.state}"), Span(labels.get(engine.state, engine.state)),
                  Small(mode, cls="mode-tag"), id="engine-pill", type="button", cls="pill",
                  title=title, onclick="openEngine()",
                  hx_get="/engine/status", hx_trigger="every 2s", hx_swap="outerHTML")


def quant_select(engine: Engine):
    s = engine.settings
    files = C.list_models("diffusion")
    if s.mode == "remote":
        return Select(Option(engine.model_name(), selected=True), id="quant-select", disabled=True,
                      title="Remote engine: the model is chosen on the remote server")
    if not files:
        label = "Mock engine (no model files yet)" if s.mode == "mock" else "No models in models/diffusion_models — see ⚙"
        return Select(Option(label, selected=True), id="quant-select", disabled=True)
    opts = [Option(f"{C.quant_label(f)} · {C.human_size(C.DIRS['diffusion'] / f)} — {f}", value=f,
                   selected=(f == s.diffusion_model)) for f in files]
    return Select(*opts, name="diffusion_model", id="quant-select", title="Diffusion model / quant (restarts engine)",
                  hx_post="/engine/model", hx_trigger="change", hx_swap="none")


def header(engine: Engine):
    return Div(
        Div(Span("MOSS", cls="brand-a"), Span("Studio", cls="brand-b"), cls="brand"),
        Div(Label("Model", fr="quant-select", cls="hdr-label"), quant_select(engine), cls="hdr-model"),
        Div(engine_pill(engine),
            Button(icon("gear"), type="button", cls="icon-btn", title="Engine settings", onclick="openEngine()"),
            cls="hdr-right"),
        cls="topbar")


def file_select(kind: str, current: str, name: str, allow_none: bool = False):
    files = C.list_models(kind)
    opts = [Option("— none —", value="")] if allow_none else []
    opts += [Option(f"{f}  ({C.human_size(C.DIRS[kind] / f)})", value=f, selected=(f == current)) for f in files]
    if not opts:
        opts = [Option(f"(nothing in models/{C.DIRS[kind].name})", value="")]
    return Select(*opts, name=name)


def engine_modal(engine: Engine):
    s = engine.settings

    def radio(val, label, hint):
        return Label(Input(type="radio", name="mode", value=val, checked=(s.mode == val)),
                     Span(Span(label, cls="r-title"), Small(hint)), cls="radio-card")

    missing_bin = not Path(C.SD_SERVER_BIN).exists()
    return Div(
        Div(
            Div(H2("Engine"), Button(icon("x"), type="button", cls="icon-btn", onclick="closeModal()"), cls="modal-head"),
            Form(
                Div(radio("managed", "Local sd-server", "Runs stable-diffusion.cpp on this PC (GGUF / safetensors)"),
                    radio("remote", "Remote sd-server", "A RunPod / LAN box already running sd-server"),
                    radio("mock", "Mock", "No GPU — fake images to try the UI"), cls="radio-row"),
                Div(Label("Remote URL", Input(name="remote_url", value=s.remote_url, placeholder="http://pod-ip:7861")),
                    cls="field"),
                Div(Label("Diffusion model (quant)", file_select("diffusion", s.diffusion_model, "diffusion_model")),
                    Label("Text encoder (Qwen3.5-9B)", file_select("text_encoder", s.text_encoder, "text_encoder")),
                    Label("VAE", file_select("vae", s.vae, "vae")),
                    Label("Tokenizer", file_select("tokenizer", s.tokenizer, "tokenizer", allow_none=True)),
                    cls="grid2"),
                Div(Label(Input(type="checkbox", name="offload_to_cpu", checked=s.offload_to_cpu), " Offload to CPU",
                          Small("keep weights in RAM; needed on 12 GB")),
                    Label(Input(type="checkbox", name="diffusion_fa", checked=s.diffusion_fa), " Flash attention"),
                    Label(Input(type="checkbox", name="vae_tiling", checked=s.vae_tiling), " VAE tiling",
                          Small("lower VRAM at 2M+ px")),
                    Label(Input(type="checkbox", name="rng_cpu", checked=s.rng_cpu), " CPU RNG",
                          Small("seeds match diffusers")),
                    cls="checks"),
                Label("Extra sd-server args", Input(name="extra_args", value=s.extra_args,
                                                    placeholder="--lora-apply-mode at_runtime")),
                P(Small(f"sd-server: {C.SD_SERVER_BIN}" + ("  (not found — see README)" if missing_bin else "")),
                  cls="muted"),
                Div(Button("Apply & restart", cls="btn primary"),
                    Button("Stop", type="button", cls="btn", hx_post="/engine/stop", hx_swap="none"),
                    cls="row-end"),
                hx_post="/engine/apply", hx_swap="none"),
            H3("Log"),
            Div(id="engine-log", cls="log", hx_get="/engine/log", hx_trigger="load, every 1.5s", hx_swap="innerHTML"),
            cls="modal-card wide"),
        cls="modal-backdrop", onclick="if(event.target===this)closeModal()")


# ---------------- left controls ----------------

def slider(name: str, label: str, value, lo, hi, step, hint: str = ""):
    return Div(
        Div(Label(label, fr=f"in-{name}"), Input(type="number", name=name, id=f"in-{name}", value=value,
                                                    min=lo, max=hi, step=step, cls="num"), cls="slider-head"),
        Input(type="range", min=lo, max=hi, step=step, value=value, data_sync=f"in-{name}", aria_label=label),
        Small(hint, cls="hint") if hint else "",
        cls="slider")


def size_block():
    mp_opts = [Option(lbl, value=str(px), selected=(px == 1048576)) for px, lbl in zip(
        PIXELS, ("0.25M · 512²", "1M · 1024²", "1.5M", "2M", "4M · ~2K"))]
    r_opts = [Option(r, value=r, selected=(r == "1:1")) for r in RATIOS]
    return Div(
        Div(Label("Size", cls="sec-label"), Small(id="size-readout", cls="hint"), cls="sec-head"),
        Div(Select(*mp_opts, name="mp", id="in-mp", aria_label="Pixel budget"),
            Select(*r_opts, name="ratio", id="in-ratio", aria_label="Aspect ratio"),
            cls="grid2 tight"),
        Div(Input(type="number", name="width", id="in-width", value=1024, step=16, min=256, max=4096, aria_label="Width"),
            Button(icon("swap"), type="button", cls="icon-btn", title="Swap width/height", onclick="swapWH()"),
            Input(type="number", name="height", id="in-height", value=1024, step=16, min=256, max=4096, aria_label="Height"),
            cls="wh"),
        cls="section")


def lora_row(loras: list[dict], path: str = "", weight: float = 1.0):
    meta = C.lora_meta()
    opts = [Option("— choose LoRA —", value="")]
    for l in loras:
        m = meta.get(l["name"]) or meta.get(l["path"]) or {}
        opts.append(Option(l["name"], value=l["path"], selected=(l["path"] == path),
                           data_trigger=m.get("trigger", ""), data_weight=str(m.get("weight", ""))))
    return Div(
        Div(Select(*opts, name="lora_path", onchange="loraPicked(this)", aria_label="LoRA"),
            Button(icon("x"), type="button", cls="icon-btn sm", title="Remove", onclick="this.closest('.lora-row').remove()"),
            cls="lora-top"),
        Div(Input(type="range", min=-1, max=2, step=0.05, value=weight, data_sync="", oninput="this.nextElementSibling.value=this.value"),
            Input(type="number", name="lora_weight", value=weight, step=0.05, min=-2, max=3, cls="num sm",
                  oninput="this.previousElementSibling.value=this.value", aria_label="LoRA weight"),
            cls="lora-w"),
        Small(cls="hint trig"),
        cls="lora-row")


def controls(engine: Engine):
    samplers = [Option(s, selected=(s == "euler")) for s in engine.samplers()]
    scheds = [Option(s, selected=(s == "discrete")) for s in engine.schedulers()]
    previews = [Option(p, selected=(p == "proj")) for p in engine.preview_modes()]
    return Div(
        Div(
            Div(Label("Prompt", fr="prompt", cls="sec-label", id="prompt-label"),
                Div(Button(icon("spark"), " Enhance", type="button", cls="btn xs ghost", title="Expand with your local LLM (LM Studio)",
                           hx_post="/enhance", hx_vals='{"kind":"caption"}', hx_include="#prompt,#in-width,#in-height",
                           hx_swap="none", hx_indicator="#enh-ind"),
                    Span(cls="spinner htmx-indicator", id="enh-ind"), cls="row-gap"),
                cls="sec-head"),
            Textarea(name="prompt", id="prompt", rows=6, placeholder="Describe the image… (Ctrl+Enter to generate)\nUse real line breaks for multi-line text you want rendered."),
            Details(Summary("Negative prompt"),
                    Textarea(name="negative_prompt", id="negative", rows=2, placeholder="optional"),
                    Button("Insert suggested", type="button", cls="btn xs ghost",
                           onclick=f"document.getElementById('negative').value={json.dumps(NEG_SUGGEST)}"),
                    cls="sub"),
            cls="section"),
        size_block(),
        Div(Label("Sampling", cls="sec-label"),
            slider("steps", "Steps", 50, 1, 100, 1, "50+ recommended"),
            slider("cfg", "CFG", 3.0, 1, 10, 0.1, "3–6; raise for short prompts"),
            slider("shift", "Shift", 5.0, 1, 10, 0.1),
            Div(Label("Seed", fr="in-seed"),
                Div(Input(type="number", name="seed", id="in-seed", value=-1, step=1, cls="num"),
                    Button(icon("dice"), type="button", cls="icon-btn", title="Random (-1)", onclick="setSeed(-1)"),
                    Button(icon("recycle"), type="button", cls="icon-btn", title="Reuse last seed", onclick="reuseSeed()"),
                    cls="seed-row"), cls="field"),
            Div(Label("Batch", Input(type="number", name="batch_count", value=1, min=1, max=8, cls="num")),
                Label("Sampler", Select(*samplers, name="sampler")),
                Label("Scheduler", Select(*scheds, name="scheduler")),
                cls="grid3"),
            cls="section"),
        Div(Div(Label("LoRAs", cls="sec-label"),
                Button(icon("plus"), " Add", type="button", cls="btn xs ghost", hx_get="/lora/row",
                       hx_target="#lora-list", hx_swap="beforeend"),
                cls="sec-head"),
            Div(id="lora-list"),
            Label(Input(type="checkbox", name="auto_trigger", checked=True), " Auto-add trigger words",
                  cls="check-inline", title="From models/loras/loras.json"),
            cls="section"),
        Details(Summary("Advanced"),
                Div(Label("Preview", Select(*previews, name="preview")),
                    Label("Every N steps", Input(type="number", name="preview_interval", value=1, min=1, max=20, cls="num")),
                    cls="grid2"),
                Div(Label("SLG scale", Input(type="number", name="slg_scale", value=0, step=0.1, min=0, max=10, cls="num")),
                    Label("SLG layers", Input(name="slg_layers", value="22")),
                    cls="grid2"),
                Div(Label("SLG start", Input(type="number", name="slg_start", value=0.01, step=0.01, min=0, max=1, cls="num")),
                    Label("SLG end", Input(type="number", name="slg_end", value=0.2, step=0.01, min=0, max=1, cls="num")),
                    cls="grid2"),
                Label(Input(type="checkbox", name="vae_tiling_req"), " VAE tiling for this job", cls="check-inline"),
                Small("The negative-branch skip of layer 22 (MOSS default) is built into sd.cpp. "
                      "SLG here is the optional extra skip-layer guidance pass (scale 0 = off).", cls="hint"),
                cls="section sub"),
        cls="controls-scroll")


def generate_bar():
    return Div(
        Button(Span("Generate", id="go-label"), Small("Ctrl+Enter", cls="kbd"), id="go", cls="btn primary big",
               type="button", hx_post="/generate", hx_target="#queue-list", hx_swap="afterbegin",
               hx_disabled_elt="this"),
        cls="go-bar")


# ---------------- stage panes ----------------

def tabs():
    def t(key, label, ic, active=False):
        return Button(icon(ic), Span(label), type="button", cls="tab" + (" active" if active else ""),
                      data_mode=key, onclick=f"setMode('{key}')", role="tab")
    return Div(t("generate", "Generate", "image", True), t("edit", "Edit", "brush"), t("layout", "Layout", "layout"),
               Input(type="hidden", name="mode", id="in-mode", value="generate"), cls="tabs", role="tablist")


def pane_generate():
    return Div(Div(empty_viewer(), id="viewer"), cls="pane", id="pane-generate")


def empty_viewer():
    return Div(Div(icon("image"), cls="empty-ic"), H3("Nothing yet"),
               P("Write a prompt and hit Generate. MOSS-Image likes long, specific descriptions; put text you want "
                 "rendered in quotes, with real line breaks."),
               cls="empty")


def pane_edit():
    return Div(
        Div(
            Label(icon("upload"), " Image", Input(type="file", accept="image/*", id="edit-file", onchange="editUpload(this)",
                                                  hidden=True), cls="btn sm", fr="edit-file"),
            Div(Button(icon("brush"), type="button", cls="icon-btn tool active", id="tool-brush", title="Brush (B)", onclick="maskTool('brush')"),
                Button(icon("eraser"), type="button", cls="icon-btn tool", id="tool-eraser", title="Eraser (E)", onclick="maskTool('eraser')"),
                Input(type="range", id="brush-size", min=4, max=300, value=60, title="Brush size", aria_label="Brush size"),
                Button("Invert", type="button", cls="btn xs ghost", onclick="maskInvert()"),
                Button("Clear", type="button", cls="btn xs ghost", onclick="maskClear()"),
                cls="tool-group"),
            cls="pane-toolbar"),
        Div(Div(Div(icon("upload"), cls="empty-ic"), H3("Drop an image here"),
                P("or upload one, or use “Edit” on any gallery image."), id="edit-empty", cls="empty"),
            Div(Div(id="pad-frame"), NotStr('<canvas id="edit-img"></canvas><canvas id="edit-mask"></canvas>'),
                id="edit-stack", cls="edit-stack", hidden=True),
            id="edit-drop", cls="edit-area"),
        Div(
            slider("strength", "Strength", 0.6, 0.05, 1, 0.01, "How much to change. Masked inpaint/outpaint: 0.85–1.0"),
            Div(Label("Work size", Select(Option("0.25M", value="262144"), Option("1M", value="1048576", selected=True),
                                         Option("1.5M", value="1572864"), Option("2M", value="2097152"),
                                         Option("Original (snap 16)", value="original"), name="edit_budget")),
                Div(Label("Outpaint px (L · T · R · B)"),
                    Div(*[Input(type="number", name=f"pad_{k}", value=0, min=0, max=2048, step=16, cls="num sm",
                                oninput="padPreview()", aria_label=f"pad {k}") for k in ("l", "t", "r", "b")],
                        Button("+25%", type="button", cls="btn xs ghost", onclick="padAll(0.25)"),
                        cls="pads"), cls="field"),
                cls="edit-opts"),
            Small(id="edit-status", cls="hint"),
            cls="edit-footer"),
        Input(type="hidden", name="init_id", id="in-init"),
        Input(type="hidden", name="mask_image", id="in-mask"),
        cls="pane", id="pane-edit", hidden=True)


def pane_layout():
    return Div(
        Div(
            Div(Button(icon("spark"), " Auto-layout", type="button", cls="btn sm",
                       title="Ask your local LLM to lay out the prompt as boxes",
                       hx_post="/enhance", hx_vals='{"kind":"layout"}', hx_include="#prompt,#in-width,#in-height",
                       hx_swap="none", hx_indicator="#lay-ind"),
                Span(cls="spinner htmx-indicator", id="lay-ind"),
                Div(*[Button(lbl, type="button", cls="chip", data_label=lbl.lower(), onclick=f"L.setDrawLabel('{lbl.lower()}')")
                      for lbl in ("Object", "Character", "Text")], cls="chips", id="draw-label"),
                cls="row-gap"),
            Div(Button("Import", type="button", cls="btn xs ghost", onclick="L.importJSON()"),
                Button("Export", type="button", cls="btn xs ghost", onclick="L.exportJSON()"),
                Button("Clear", type="button", cls="btn xs ghost", onclick="L.clear()"),
                cls="row-gap"),
            cls="pane-toolbar"),
        Div(
            Div(Div(id="lay-canvas", cls="lay-canvas"), cls="lay-wrap", id="lay-wrap"),
            Div(
                Label("Scene caption", Textarea(id="lay-caption", rows=4, placeholder="Overall scene, medium, palette, mood…",
                                                oninput="L.sync()")),
                Div(Label("Meta tags", Input(id="lay-meta", placeholder="poster, flat illustration", oninput="L.sync()")),
                    Label("Canvas", Select(Option("single"), Option("multi_panel"), Option("collage"), id="lay-canvas-kind",
                                           onchange="L.sync()")), cls="grid2"),
                Div(id="lay-items", cls="lay-items"),
                Details(Summary("Compiled prompt"), Div(id="lay-compiled", cls="code"), cls="sub"),
                cls="lay-side"),
            cls="lay-body"),
        Small("Drag on the canvas to draw a box. Drag to move, corner to resize, Del to delete. "
              "Boxes scale with the size controls.", cls="hint"),
        Input(type="hidden", name="layout_draft", id="in-layout"),
        cls="pane", id="pane-layout", hidden=True)


# ---------------- jobs ----------------

def _status_text(job: Job) -> str:
    if job.status == "queued":
        return f"Queued #{job.queue_position}" if job.queue_position else "Queued"
    if job.status == "generating":
        n = int(job.params.get("batch_count", 1))
        b = f" · img {job.pass_no}/{n}" if n > 1 else ""
        return f"Step {job.step}/{job.total}{b}" if job.total else "Encoding prompt…"
    if job.status == "completed":
        return f"Done in {job.elapsed:.1f}s"
    return job.status.capitalize()


def job_card(job: Job, oob_gallery: list | None = None):
    live = not job.done
    if job.images:
        thumbs = [Img(src=f"/thumb/{g}", cls="jc-thumb", loading="lazy", hx_get=f"/gallery/view?gid={g}",
                      hx_target="#modal", hx_swap="innerHTML") for g in job.images]
    elif job.preview:
        thumbs = [Img(src=f"/jobs/{job.id}/preview?v={job.preview_ver}", cls="jc-thumb preview")]
    else:
        thumbs = [Div(cls="jc-thumb ph" + (" err" if job.status == "failed" else ""))]
    p = job.params
    mode_tag = {"generate": "T2I", "edit": "EDIT", "layout": "LAYOUT"}.get(p.get("mode"), "")
    body = Div(
        Div(Span(mode_tag, cls="tag"), Span(_status_text(job), cls="jc-status"),
            Button(icon("x"), type="button", cls="icon-btn sm", title="Cancel", hx_post=f"/jobs/{job.id}/cancel",
                   hx_swap="none") if live else "",
            Button(icon("edit"), type="button", cls="icon-btn sm", title="Edit this result",
                   onclick=f"sendToEdit('gallery:{job.images[0]}', '/img/{job.images[0]}')") if job.images else "",
            cls="jc-head"),
        Div(p.get("prompt_display", "")[:120], cls="jc-prompt"),
        Div(Div(cls="bar", style=f"width:{job.progress * 100:.1f}%"), cls="progress" + (" live" if live else "")),
        Small(job.error, cls="err-text") if job.error and job.status == "failed" else "",
        cls="jc-body")
    attrs = dict(id=f"job-{job.id}", cls=f"job-card {job.status}", data_seed=str(p.get("seed", "")))
    if live:
        attrs.update(hx_get=f"/jobs/{job.id}/card", hx_trigger="every 700ms", hx_swap="outerHTML")
    card = Div(Div(*thumbs, cls="jc-thumbs"), body, **attrs)
    return (card, *oob_gallery) if oob_gallery else card


def job_viewer(job: Job):
    live = not job.done
    p = job.params
    if job.images:
        main = Div(*[Img(src=f"/img/{g}", cls="v-img", hx_get=f"/gallery/view?gid={g}", hx_target="#modal",
                         hx_swap="innerHTML", title="Details") for g in job.images],
                   cls=f"v-grid n{min(len(job.images), 4)}")
    elif job.preview:
        main = Img(src=f"/jobs/{job.id}/preview?v={job.preview_ver}", cls="v-img preview",
                   style=f"aspect-ratio:{p.get('width', 1)}/{p.get('height', 1)}")
    else:
        main = Div(Div(cls="pulse"), Span(_status_text(job) if not job.error else job.error),
                   cls="v-wait" + (" err" if job.status == "failed" else ""),
                   style=f"aspect-ratio:{p.get('width', 1)}/{p.get('height', 1)}")
    info = f"{p.get('width')}×{p.get('height')} · {p.get('steps')} steps · CFG {p.get('cfg')} · seed {p.get('seed')}"
    attrs = dict(id="viewer-job", cls="viewer", data_job=job.id)
    if live:
        attrs.update(hx_get=f"/jobs/{job.id}/viewer", hx_trigger="every 700ms", hx_swap="outerHTML")
    return Div(
        Div(main, cls="v-main"),
        Div(Div(Div(cls="bar", style=f"width:{job.progress * 100:.1f}%"), cls="progress" + (" live" if live else "")),
            Div(Span(_status_text(job)), Span(info, cls="muted"), cls="v-meta"),
            Small(job.error, cls="err-text") if job.status == "failed" and job.error else "",
            cls="v-foot"),
        **attrs)


# ---------------- gallery ----------------

def gallery_thumb(gid: str, oob: bool = False):
    return Button(Img(src=f"/thumb/{gid}", loading="lazy", alt=""), type="button", cls="g-item", id=f"g-{gid.replace('/', '_')}",
                  hx_get=f"/gallery/view?gid={gid}", hx_target="#modal", hx_swap="innerHTML")


def gallery_modal(gid: str):
    m = read_meta(gid)
    rows = []
    for key, label in (("mode", "Mode"), ("model", "Model"), ("width", "Width"), ("height", "Height"),
                       ("steps", "Steps"), ("cfg", "CFG"), ("shift", "Shift"), ("seed_used", "Seed"),
                       ("sampler", "Sampler"), ("scheduler", "Scheduler"), ("strength", "Strength"),
                       ("created", "Created")):
        if m.get(key) not in (None, ""):
            rows.append(Div(Span(label, cls="k"), Span(str(m[key]), cls="v"), cls="kv"))
    for l in m.get("loras") or []:
        rows.append(Div(Span("LoRA", cls="k"), Span(f"{Path(l['path']).stem} × {l['multiplier']}", cls="v"), cls="kv"))
    meta_json = json.dumps(m, ensure_ascii=False).replace("</", "<\\/")
    return Div(
        Div(
            Div(H2(gid.split("/")[-1]), Button(icon("x"), type="button", cls="icon-btn", onclick="closeModal()"),
                cls="modal-head"),
            Div(
                Div(A(Img(src=f"/img/{gid}", cls="m-img"), href=f"/img/{gid}", target="_blank"), cls="m-imgwrap"),
                Div(
                    Div(m.get("prompt_display", ""), cls="m-prompt"),
                    Div(*rows, cls="kvs"),
                    Div(Button(icon("recycle"), " Reuse settings", type="button", cls="btn sm",
                               onclick=f"applySettings(JSON.parse(document.getElementById('m-meta').textContent));closeModal()"),
                        Button(icon("edit"), " Edit image", type="button", cls="btn sm",
                               onclick=f"sendToEdit('gallery:{gid}', '/img/{gid}');closeModal()"),
                        Button(icon("layout"), " Open layout", type="button", cls="btn sm",
                               onclick="L.load(JSON.parse(document.getElementById('m-meta').textContent).layout_draft);setMode('layout');closeModal()")
                        if m.get("layout_draft") else "",
                        A(icon("download"), " Download", href=f"/img/{gid}?dl=1", cls="btn sm"),
                        Button(icon("trash"), " Delete", type="button", cls="btn sm danger",
                               hx_delete=f"/gallery/item?gid={gid}", hx_confirm="Delete this image?", hx_swap="none"),
                        cls="m-actions"),
                    cls="m-side"),
                cls="m-body"),
            NotStr(f'<script type="application/json" id="m-meta">{meta_json}</script>'),
            cls="modal-card xl"),
        cls="modal-backdrop", onclick="if(event.target===this)closeModal()")


def toast(msg: str, kind: str = "info"):
    return Div(Div(msg, cls=f"toast {kind}"), id="toasts", hx_swap_oob="beforeend")
