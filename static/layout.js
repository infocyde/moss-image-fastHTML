/* MOSS Studio — visual layout editor (boxes in top-left xyxy pixels; compiled to abs_centralized/yxyx). */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const MIN = 8;

  const L = window.L = {
    items: [], sel: -1, drawLabel: "object", W: 1024, H: 1024, drag: null,

    init() {
      const cv = $("#lay-canvas"); if (!cv) return;
      [this.W, this.H] = getWH();
      cv.addEventListener("pointerdown", e => this.down(e));
      window.addEventListener("pointermove", e => this.move(e));
      window.addEventListener("pointerup", () => this.up());
      document.addEventListener("sizechange", e => this.resize(e.detail.w, e.detail.h));
      document.addEventListener("keydown", e => {
        if (document.body.dataset.mode !== "layout" || e.target.matches("input, textarea, select")) return;
        if ((e.key === "Delete" || e.key === "Backspace") && this.sel >= 0) { e.preventDefault(); this.remove(this.sel); }
        const step = e.shiftKey ? 16 : 1, d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
        if (d && this.sel >= 0) { e.preventDefault(); this.nudge(d[0], d[1]); }
      });
      new ResizeObserver(() => this.layoutCanvas()).observe($("#lay-wrap"));
      this.setDrawLabel("object");
      this.renderSide(); this.render();
    },

    setDrawLabel(l) { this.drawLabel = l; document.querySelectorAll("#draw-label .chip").forEach(c => c.classList.toggle("active", c.dataset.label === l)); },

    // ---------- geometry
    layoutCanvas() {
      const wrap = $("#lay-wrap"), cv = $("#lay-canvas"); if (!wrap || !wrap.clientWidth) return;
      const s = Math.min((wrap.clientWidth - 8) / this.W, (wrap.clientHeight - 8) / this.H);
      cv.style.width = `${this.W * s}px`; cv.style.height = `${this.H * s}px`;
    },
    pt(e) {
      const r = $("#lay-canvas").getBoundingClientRect();
      return [Math.round(Math.max(0, Math.min(this.W, (e.clientX - r.left) / r.width * this.W))),
              Math.round(Math.max(0, Math.min(this.H, (e.clientY - r.top) / r.height * this.H)))];
    },
    resize(w, h) {
      w = Math.round(w / 16) * 16; h = Math.round(h / 16) * 16;
      if (!w || !h || (w === this.W && h === this.H)) return;
      const sx = w / this.W, sy = h / this.H;
      this.items.forEach(it => { const [a, b, c, d] = it.bbox; it.bbox = [a * sx, b * sy, c * sx, d * sy].map(Math.round); });
      this.W = w; this.H = h; this.render(); this.sync();
    },

    // ---------- pointer
    down(e) {
      if (e.button !== 0) return;
      const handle = e.target.closest(".lh"), box = e.target.closest(".lbox");
      const p = this.pt(e);
      if (handle && box) {
        this.sel = +box.dataset.i; this.drag = { kind: "resize", corner: handle.dataset.c, start: p, orig: [...this.items[this.sel].bbox] };
      } else if (box) {
        this.select(+box.dataset.i);
        this.drag = { kind: "move", start: p, orig: [...this.items[this.sel].bbox] };
      } else {
        this.items.push({ label: this.drawLabel, caption: "", text: this.drawLabel === "text" ? "" : undefined, bbox: [p[0], p[1], p[0], p[1]] });
        this.sel = this.items.length - 1;
        this.drag = { kind: "new", start: p };
        this.render();
      }
      e.preventDefault();
    },
    move(e) {
      if (!this.drag) return;
      const p = this.pt(e), d = this.drag, it = this.items[this.sel]; if (!it) return;
      const dx = p[0] - d.start[0], dy = p[1] - d.start[1];
      if (d.kind === "new") {
        it.bbox = [Math.min(d.start[0], p[0]), Math.min(d.start[1], p[1]), Math.max(d.start[0], p[0]), Math.max(d.start[1], p[1])];
      } else if (d.kind === "move") {
        const [a, b, c, dd] = d.orig, w = c - a, h = dd - b;
        const nx = Math.max(0, Math.min(this.W - w, a + dx)), ny = Math.max(0, Math.min(this.H - h, b + dy));
        it.bbox = [nx, ny, nx + w, ny + h];
      } else {
        let [a, b, c, dd] = d.orig;
        if (d.corner.includes("w")) a = Math.min(c - MIN, Math.max(0, a + dx));
        if (d.corner.includes("e")) c = Math.max(a + MIN, Math.min(this.W, c + dx));
        if (d.corner.includes("n")) b = Math.min(dd - MIN, Math.max(0, b + dy));
        if (d.corner.includes("s")) dd = Math.max(b + MIN, Math.min(this.H, dd + dy));
        it.bbox = [a, b, c, dd];
      }
      this.renderBoxes();
    },
    up() {
      if (!this.drag) return;
      const d = this.drag; this.drag = null;
      const it = this.items[this.sel];
      if (d.kind === "new" && it) {
        const [a, b, c, dd] = it.bbox;
        if (c - a < MIN * 2 || dd - b < MIN * 2) { this.items.splice(this.sel, 1); this.sel = -1; this.render(); return; }
        this.renderSide(); this.focusCaption(this.sel);
      }
      this.render(); this.sync();
    },
    nudge(dx, dy) {
      const it = this.items[this.sel], [a, b, c, d] = it.bbox, w = c - a, h = d - b;
      const nx = Math.max(0, Math.min(this.W - w, a + dx)), ny = Math.max(0, Math.min(this.H - h, b + dy));
      it.bbox = [nx, ny, nx + w, ny + h]; this.renderBoxes(); this.sync();
    },

    // ---------- items
    select(i) {
      this.sel = i; this.renderBoxes();
      document.querySelectorAll(".lay-item").forEach(el => el.classList.toggle("sel", +el.dataset.i === i));
      const el = document.querySelector(`.lay-item[data-i="${i}"]`); el?.scrollIntoView({ block: "nearest" });
    },
    remove(i) { this.items.splice(i, 1); this.sel = -1; this.render(); this.sync(); },
    dup(i) { const it = JSON.parse(JSON.stringify(this.items[i])); it.bbox = it.bbox.map((v, k) => v + 16); this.items.push(it); this.sel = this.items.length - 1; this.render(); this.sync(); },
    up_(i, k, v) { const it = this.items[i]; it[k] = v; if (k === "label") { if (v === "text" && it.text === undefined) it.text = ""; this.renderSide(); } this.renderBoxes(); this.sync(); },
    focusCaption(i) { setTimeout(() => document.querySelector(`.lay-item[data-i="${i}"] textarea`)?.focus(), 0); },
    clear() { if (this.items.length && !confirm("Remove all boxes?")) return; this.items = []; this.sel = -1; $("#lay-caption").value = ""; $("#lay-meta").value = ""; this.render(); this.sync(); },

    // ---------- render
    render() { this.layoutCanvas(); this.renderBoxes(); this.renderSide(); },
    renderBoxes() {
      const cv = $("#lay-canvas"); if (!cv) return;
      const pct = (v, t) => `${(v / t * 100).toFixed(3)}%`;
      cv.innerHTML = this.items.map((it, i) => {
        const [a, b, c, d] = it.bbox;
        const txt = it.label === "text" ? (it.text || "") : (it.caption || "");
        const handles = i === this.sel ? ["nw", "ne", "sw", "se"].map(k => `<span class="lh ${k}" data-c="${k}"></span>`).join("") : "";
        return `<div class="lbox ${it.label}${i === this.sel ? " sel" : ""}" data-i="${i}" style="left:${pct(a, this.W)};top:${pct(b, this.H)};width:${pct(c - a, this.W)};height:${pct(d - b, this.H)}">
          <span class="ltag">${i + 1} · ${it.label}</span><span class="ltxt">${esc(txt).slice(0, 140)}</span>${handles}</div>`;
      }).join("") + (this.items.length ? "" : `<div class="lay-hint">Drag to draw a ${this.drawLabel} box</div>`);
    },
    renderSide() {
      const host = $("#lay-items"); if (!host) return;
      host.innerHTML = this.items.map((it, i) => {
        const [a, b, c, d] = it.bbox.map(Math.round);
        return `<div class="lay-item ${it.label}${i === this.sel ? " sel" : ""}" data-i="${i}" onclick="L.select(${i})">
          <div class="li-head"><b>${i + 1}</b>
            <select onchange="L.up_(${i},'label',this.value)">${["object", "character", "text"].map(l => `<option${l === it.label ? " selected" : ""}>${l}</option>`).join("")}</select>
            <small class="muted">${c - a}×${d - b} @ ${a},${b}</small>
            <button type="button" class="icon-btn sm" title="Duplicate" onclick="event.stopPropagation();L.dup(${i})">⧉</button>
            <button type="button" class="icon-btn sm" title="Delete" onclick="event.stopPropagation();L.remove(${i})">✕</button></div>
          ${it.label === "text" ? `<textarea rows="2" placeholder="Exact text to render (line breaks kept)" oninput="L.up_(${i},'text',this.value)">${esc(it.text)}</textarea>` : ""}
          <textarea rows="2" placeholder="${it.label === "text" ? "Typography: font feel, colour, weight…" : "What it looks like…"}" oninput="L.up_(${i},'caption',this.value)">${esc(it.caption)}</textarea>
        </div>`;
      }).join("") || `<p class="muted small">No boxes yet. Pick Object / Character / Text above, then drag on the canvas — or try Auto-layout.</p>`;
    },

    // ---------- (de)serialise
    draft() {
      const meta = $("#lay-meta").value.split(",").map(s => s.trim()).filter(Boolean);
      const summary = { caption: $("#lay-caption").value.trim(), canvas: $("#lay-canvas-kind").value };
      if (meta.length) summary.meta = meta;
      return {
        width: this.W, height: this.H, bbox_coord_space: "abs", bbox_format: "xyxy", summary,
        items: this.items.map(it => {
          const o = { label: it.label, caption: (it.caption || "").trim(), bbox: it.bbox.map(Math.round) };
          if (it.label === "text" || (it.text && it.text.trim())) o.text = it.text || "";
          return o;
        }),
      };
    },
    compiled(d) {
      const hw = Math.floor(d.width / 2), hh = Math.floor(d.height / 2);
      return JSON.stringify({
        summary: d.summary,
        items: d.items.map(it => { const [x1, y1, x2, y2] = it.bbox; return { ...it, bbox: [Math.floor(y1) - hh, Math.floor(x1) - hw, Math.ceil(y2) - hh, Math.ceil(x2) - hw] }; }),
        bbox_coord_space: "abs_centralized", bbox_format: "yxyx",
      });
    },
    sync() {
      const d = this.draft();
      $("#in-layout").value = JSON.stringify(d);
      const out = $("#lay-compiled"); if (out) out.textContent = this.compiled(d);
    },
    load(d) {
      if (typeof d === "string") d = JSON.parse(d);
      if (!d) return;
      let items = d.items || [];
      if (d.bbox_coord_space === "abs_centralized") {   // compiled prompt pasted back in
        const W = d.width || this.W, H = d.height || this.H;
        items = items.map(it => { const [y1, x1, y2, x2] = it.bbox; return { ...it, bbox: [x1 + W / 2, y1 + H / 2, x2 + W / 2, y2 + H / 2] }; });
      }
      if (d.width && d.height && (d.width !== this.W || d.height !== this.H)) { this.W = d.width; this.H = d.height; setWH(d.width, d.height); }
      this.items = items.map(it => ({ label: it.label || "object", caption: it.caption || "", text: it.text, bbox: it.bbox.map(Number) }));
      const s = d.summary || {};
      $("#lay-caption").value = s.caption || ""; $("#lay-meta").value = (s.meta || []).join(", ");
      $("#lay-canvas-kind").value = s.canvas || "single";
      this.sel = -1; this.render(); this.sync();
    },
    importJSON() {
      const inp = document.createElement("input"); inp.type = "file"; inp.accept = ".json,application/json,text/plain";
      inp.onchange = async () => { try { this.load(JSON.parse(await inp.files[0].text())); } catch (e) { alert("Not a layout JSON: " + e.message); } };
      inp.click();
    },
    exportJSON() {
      const blob = new Blob([JSON.stringify(this.draft(), null, 2)], { type: "application/json" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "moss-layout.json"; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    },
  };
  document.addEventListener("DOMContentLoaded", () => { L.init(); L.sync(); });
})();
