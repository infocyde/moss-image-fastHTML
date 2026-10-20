/* MOSS Studio — general UI glue + edit (img2img / inpaint / outpaint) canvas */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  window.$ = $; window.$$ = $$;

  // ---------------------------------------------------------------- modes
  const GO_LABEL = { generate: "Generate", edit: "Run edit", layout: "Generate from layout" };
  window.setMode = (mode) => {
    $("#in-mode").value = mode;
    $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.mode === mode));
    ["generate", "edit", "layout"].forEach(m => { const p = $("#pane-" + m); if (p) p.hidden = m !== mode; });
    $("#go-label").textContent = GO_LABEL[mode];
    $("#prompt-label").textContent = mode === "layout" ? "Idea (for Auto-layout)" : "Prompt";
    document.body.dataset.mode = mode;
    if (mode === "edit") Edit.fit();
    if (mode === "layout" && window.L) L.render();
  };

  // ---------------------------------------------------------------- sliders
  document.addEventListener("input", (e) => {
    const el = e.target;
    if (el.matches("input[type=range][data-sync]") && el.dataset.sync) {
      const num = document.getElementById(el.dataset.sync); if (num) num.value = el.value;
    } else if (el.matches("input[type=number][id]")) {
      const rng = $(`input[type=range][data-sync="${el.id}"]`); if (rng) rng.value = el.value;
    }
  });

  // ---------------------------------------------------------------- size
  const fitSize = (pixels, ratio) => {
    const [a, b] = ratio.split(":").map(Number), r = a / b;
    const snap = v => Math.max(16, Math.floor(v / 16 + 0.5) * 16);
    return [snap(Math.sqrt(pixels * r)), snap(Math.sqrt(pixels / r))];
  };
  const sizeReadout = () => {
    const w = +$("#in-width").value, h = +$("#in-height").value;
    const mp = (w * h / 1048576).toFixed(2);
    const bad = (w % 16 || h % 16) ? " · will snap to ×16" : "";
    $("#size-readout").textContent = `${w}×${h} · ${mp} MP${bad}`;
    document.dispatchEvent(new CustomEvent("sizechange", { detail: { w, h } }));
  };
  window.getWH = () => [Math.max(16, Math.round(+$("#in-width").value / 16) * 16), Math.max(16, Math.round(+$("#in-height").value / 16) * 16)];
  window.setWH = (w, h) => { $("#in-width").value = w; $("#in-height").value = h; sizeReadout(); };
  window.swapWH = () => setWH($("#in-height").value, $("#in-width").value);
  const presetChanged = () => { const [w, h] = fitSize(+$("#in-mp").value, $("#in-ratio").value); setWH(w, h); };

  // ---------------------------------------------------------------- seed / prompt
  window.setSeed = v => { $("#in-seed").value = v; };
  window.reuseSeed = () => { const c = $(".job-card[data-seed]"); if (c) setSeed(c.dataset.seed); };
  window.setPrompt = (text) => {
    const ta = $("#prompt"); ta.focus(); ta.select();
    if (!document.execCommand || !document.execCommand("insertText", false, text)) ta.value = text;
  };

  // ---------------------------------------------------------------- modal / toasts
  window.openEngine = () => htmx.ajax("GET", "/engine/modal", { target: "#modal", swap: "innerHTML" });
  window.closeModal = () => { $("#modal").innerHTML = ""; };
  const toastObserver = new MutationObserver(muts => muts.forEach(m => m.addedNodes.forEach(n => {
    if (n.nodeType === 1) setTimeout(() => { n.classList.add("out"); setTimeout(() => n.remove(), 400); }, n.classList.contains("error") ? 7000 : 3500);
  })));

  // ---------------------------------------------------------------- LoRA
  window.loraPicked = (sel) => {
    const opt = sel.selectedOptions[0], row = sel.closest(".lora-row");
    const trig = opt?.dataset.trigger || "", w = opt?.dataset.weight;
    row.querySelector(".trig").textContent = trig ? `trigger: ${trig}` : "";
    if (w) { row.querySelector("input[type=number]").value = w; row.querySelector("input[type=range]").value = w; }
  };

  // ---------------------------------------------------------------- reuse settings
  window.applySettings = (m) => {
    if (!m) return;
    const set = (sel, v) => { const el = $(sel); if (el && v !== undefined && v !== null) { el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); } };
    if (m.mode !== "layout") set("#prompt", m.prompt);
    set("#negative", m.negative_prompt);
    set("#in-steps", m.steps); set("#in-cfg", m.cfg); set("#in-shift", m.shift);
    set("#in-seed", m.seed_used ?? m.seed);
    set("[name=sampler]", m.sampler); set("[name=scheduler]", m.scheduler);
    if (m.mode !== "edit") setWH(m.width, m.height);
    htmx.ajax("POST", "/lora/rows", { target: "#lora-list", swap: "innerHTML", values: { items: JSON.stringify(m.loras || []) } });
    if (m.mode === "layout" && m.layout_draft) { L.load(m.layout_draft); setMode("layout"); }
    else if (m.mode !== "edit") setMode("generate");
  };

  // ---------------------------------------------------------------- edit canvas
  const Edit = window.Edit = {
    img: null, initId: "", tool: "brush", painted: false, drawing: false, last: null, scale: 1,
    cImg: null, cMask: null,

    init() {
      this.cImg = $("#edit-img"); this.cMask = $("#edit-mask");
      if (!this.cMask) return;
      const m = this.cMask;
      m.addEventListener("pointerdown", e => { m.setPointerCapture(e.pointerId); this.drawing = true; this.last = null; this.stroke(e); });
      m.addEventListener("pointermove", e => { this.cursor(e); if (this.drawing) this.stroke(e); });
      const end = () => { if (this.drawing) { this.drawing = false; this.export(); } };
      m.addEventListener("pointerup", end); m.addEventListener("pointercancel", end);
      m.addEventListener("pointerleave", () => { const c = $("#brush-cursor"); if (c) c.style.display = "none"; });
      const drop = $("#edit-drop");
      drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("drag"); });
      drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
      drop.addEventListener("drop", e => {
        e.preventDefault(); drop.classList.remove("drag");
        const f = e.dataTransfer.files?.[0]; if (f) this.upload(f);
        else { const u = e.dataTransfer.getData("text/uri-list"); const g = u && u.match(/\/(?:img|thumb)\/(.+)$/); if (g) sendToEdit("gallery:" + g[1], "/img/" + g[1]); }
      });
      const cur = document.createElement("div"); cur.id = "brush-cursor"; $("#edit-stack").appendChild(cur);
      new ResizeObserver(() => this.fit()).observe(drop);
    },

    async upload(file) {
      const fd = new FormData(); fd.append("file", file);
      $("#edit-status").textContent = "Uploading…";
      const r = await fetch("/upload", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) { $("#edit-status").textContent = j.error || "Upload failed"; return; }
      this.load(j.id, j.url);
    },

    load(initId, url) {
      const im = new Image();
      im.onload = () => {
        this.img = im; this.initId = initId; $("#in-init").value = initId;
        let w = im.naturalWidth, h = im.naturalHeight; const cap = 4096 / Math.max(w, h);
        if (cap < 1) { w = Math.round(w * cap); h = Math.round(h * cap); }
        for (const c of [this.cImg, this.cMask]) { c.width = w; c.height = h; }
        this.cImg.getContext("2d").drawImage(im, 0, 0, w, h);
        this.clear(true);
        $("#edit-empty").hidden = true; $("#edit-stack").hidden = false;
        this.fit(); this.status();
      };
      im.onerror = () => { $("#edit-status").textContent = "Couldn't load image"; };
      im.src = url;
    },

    pads() { return ["l", "t", "r", "b"].map(k => Math.max(0, +($(`[name=pad_${k}]`).value || 0))); },

    fit() {
      if (!this.img || $("#pane-edit").hidden) return;
      const area = $("#edit-drop"), [l, t, r, b] = this.pads();
      const W = this.cImg.width, H = this.cImg.height;
      const sx = W / this.img.naturalWidth; // canvas px per source px
      const tw = W + (l + r) * sx, th = H + (t + b) * sx;
      const s = Math.min((area.clientWidth - 24) / tw, (area.clientHeight - 24) / th, 4);
      this.scale = s;
      const stack = $("#edit-stack");
      stack.style.width = `${tw * s}px`; stack.style.height = `${th * s}px`;
      for (const c of [this.cImg, this.cMask]) {
        Object.assign(c.style, { width: `${W * s}px`, height: `${H * s}px`, left: `${l * sx * s}px`, top: `${t * sx * s}px` });
      }
      $("#pad-frame").classList.toggle("on", l + t + r + b > 0);
    },

    status() {
      if (!this.img) return;
      const [l, t, r, b] = this.pads(), out = l + t + r + b > 0;
      const kind = out ? "Outpaint" + (this.painted ? " + inpaint" : "") : this.painted ? "Inpaint (only painted area changes)" : "Img2img (whole image)";
      $("#edit-status").textContent = `${this.img.naturalWidth}×${this.img.naturalHeight} source · ${kind}`;
      if ((out || this.painted) && +$("#in-strength").value < 0.8) $("#edit-status").textContent += " · tip: strength 0.85–1.0";
    },

    pos(e) {
      const r = this.cMask.getBoundingClientRect();
      return [(e.clientX - r.left) * this.cMask.width / r.width, (e.clientY - r.top) * this.cMask.height / r.height];
    },
    cursor(e) {
      const c = $("#brush-cursor"), st = $("#edit-stack").getBoundingClientRect();
      const d = +$("#brush-size").value;
      Object.assign(c.style, { display: "block", width: `${d}px`, height: `${d}px`, left: `${e.clientX - st.left - d / 2}px`, top: `${e.clientY - st.top - d / 2}px` });
    },
    stroke(e) {
      const ctx = this.cMask.getContext("2d"), [x, y] = this.pos(e);
      const r = this.cMask.getBoundingClientRect();
      ctx.lineWidth = +$("#brush-size").value * this.cMask.width / r.width;
      ctx.lineCap = ctx.lineJoin = "round";
      ctx.strokeStyle = ctx.fillStyle = "rgb(255,64,96)";
      ctx.globalCompositeOperation = this.tool === "eraser" ? "destination-out" : "source-over";
      ctx.beginPath();
      if (this.last) { ctx.moveTo(...this.last); ctx.lineTo(x, y); ctx.stroke(); }
      else { ctx.arc(x, y, ctx.lineWidth / 2, 0, Math.PI * 2); ctx.fill(); }
      this.last = [x, y];
      if (this.tool === "brush") this.painted = true;
    },
    clear(silent) {
      if (!this.cMask) return;
      this.cMask.getContext("2d").clearRect(0, 0, this.cMask.width, this.cMask.height);
      this.painted = false; $("#in-mask").value = "";
      if (!silent) this.status();
    },
    invert() {
      const c = this.cMask, ctx = c.getContext("2d");
      const tmp = document.createElement("canvas"); tmp.width = c.width; tmp.height = c.height;
      const t = tmp.getContext("2d");
      t.fillStyle = "rgb(255,64,96)"; t.fillRect(0, 0, c.width, c.height);
      t.globalCompositeOperation = "destination-out"; t.drawImage(c, 0, 0);
      ctx.globalCompositeOperation = "source-over"; ctx.clearRect(0, 0, c.width, c.height); ctx.drawImage(tmp, 0, 0);
      this.painted = true; this.export();
    },
    export() {
      const c = this.cMask;
      const tmp = document.createElement("canvas"); tmp.width = c.width; tmp.height = c.height;
      const t = tmp.getContext("2d");
      t.drawImage(c, 0, 0);
      t.globalCompositeOperation = "source-in"; t.fillStyle = "#fff"; t.fillRect(0, 0, c.width, c.height);
      t.globalCompositeOperation = "destination-over"; t.fillStyle = "#000"; t.fillRect(0, 0, c.width, c.height);
      // quick emptiness check on a downscaled copy
      const s = document.createElement("canvas"); s.width = 64; s.height = 64;
      const sc = s.getContext("2d"); sc.drawImage(tmp, 0, 0, 64, 64);
      const px = sc.getImageData(0, 0, 64, 64).data; let any = false;
      for (let i = 0; i < px.length; i += 4) if (px[i] > 8) { any = true; break; }
      this.painted = any;
      $("#in-mask").value = any ? tmp.toDataURL("image/png") : "";
      this.status();
    },
  };
  window.editUpload = (input) => { const f = input.files?.[0]; if (f) Edit.upload(f); input.value = ""; };
  window.sendToEdit = (initId, url) => { setMode("edit"); Edit.load(initId, url); };
  window.maskTool = (t) => { Edit.tool = t; $$(".tool").forEach(b => b.classList.toggle("active", b.id === "tool-" + t)); };
  window.maskClear = () => Edit.clear();
  window.maskInvert = () => Edit.invert();
  window.padPreview = () => { Edit.fit(); Edit.status(); };
  window.padAll = (f) => {
    if (!Edit.img) return;
    const w = Edit.img.naturalWidth, h = Edit.img.naturalHeight, r16 = v => Math.round(v / 16) * 16;
    $("[name=pad_l]").value = $("[name=pad_r]").value = r16(w * f / 2);
    $("[name=pad_t]").value = $("[name=pad_b]").value = r16(h * f / 2);
    padPreview();
  };

  // ---------------------------------------------------------------- keyboard
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); $("#go").click(); return; }
    if (e.key === "Escape" && $("#modal").innerHTML) { closeModal(); return; }
    const typing = e.target.matches("input, textarea, select");
    if (typing) return;
    if (document.body.dataset.mode === "edit") {
      if (e.key === "b") maskTool("brush");
      if (e.key === "e") maskTool("eraser");
      if (e.key === "[") $("#brush-size").value = +$("#brush-size").value - 10;
      if (e.key === "]") $("#brush-size").value = +$("#brush-size").value + 10;
    }
  });

  // server-fired events (HX-Trigger)
  document.addEventListener("moss:prompt", e => setPrompt(e.detail.text));
  document.addEventListener("moss:layout", e => { L.load(e.detail.draft); setMode("layout"); });
  document.addEventListener("moss:close", () => closeModal());

  // ---------------------------------------------------------------- boot
  document.addEventListener("DOMContentLoaded", () => {
    $("#in-mp").addEventListener("change", presetChanged);
    $("#in-ratio").addEventListener("change", presetChanged);
    $("#in-width").addEventListener("change", sizeReadout);
    $("#in-height").addEventListener("change", sizeReadout);
    $("#in-strength").addEventListener("input", () => Edit.status());
    toastObserver.observe($("#toasts"), { childList: true });
    Edit.init();
    sizeReadout();
    setMode("generate");
  });
  document.body?.addEventListener?.("htmx:responseError", e => {
    const t = document.createElement("div"); t.className = "toast error";
    t.textContent = `Request failed (${e.detail.xhr.status})`; $("#toasts").appendChild(t);
  });
  document.addEventListener("htmx:sendError", () => {
    const t = document.createElement("div"); t.className = "toast error"; t.textContent = "Can't reach MOSS Studio server"; $("#toasts")?.appendChild(t);
  });
})();
