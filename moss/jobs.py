"""Job tracking (polls the engine in the background so results save even if the tab closes) + gallery."""
from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config as C
from .engine import Engine, EngineError
from .imaging import thumbnail

TERMINAL = {"completed", "failed", "cancelled"}


@dataclass
class Job:
    id: str
    params: dict
    server_id: str = ""
    status: str = "submitting"
    queue_position: int = 0
    step: int = 0
    total: int = 0
    pass_no: int = 1
    preview: bytes | None = None
    preview_ver: int = 0
    images: list[str] = field(default_factory=list)
    error: str = ""
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0

    @property
    def done(self) -> bool:
        return self.status in TERMINAL

    @property
    def progress(self) -> float:
        n = max(1, int(self.params.get("batch_count", 1)))
        if self.status == "completed":
            return 1.0
        if not self.total:
            return 0.0
        return min(1.0, ((self.pass_no - 1) + self.step / self.total) / n)

    @property
    def elapsed(self) -> float:
        if not self.started:
            return 0.0
        return (self.finished or time.time()) - self.started


class JobManager:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.jobs: dict[str, Job] = {}
        self.order: list[str] = []

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def recent(self, n: int = 12) -> list[Job]:
        return [self.jobs[j] for j in reversed(self.order[-n:]) if j in self.jobs]

    async def submit(self, body: dict, params: dict) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], params=params)
        self.jobs[job.id] = job
        self.order.append(job.id)
        if len(self.order) > 60:
            old = self.order.pop(0)
            self.jobs.pop(old, None)
        try:
            resp = await self.engine.submit(body)
            job.server_id = resp["id"]
            job.status = resp.get("status", "queued")
        except (EngineError, KeyError) as e:
            job.status, job.error, job.finished = "failed", str(e), time.time()
            return job
        asyncio.create_task(self._poll(job))
        return job

    async def cancel(self, job: Job) -> None:
        if job.server_id and not job.done:
            try:
                await self.engine.cancel(job.server_id)
            except EngineError:
                pass

    async def _poll(self, job: Job) -> None:
        misses = 0
        while not job.done:
            await asyncio.sleep(0.6)
            try:
                d = await self.engine.job(job.server_id)
                misses = 0
            except Exception as e:  # noqa: BLE001 — keep polling through hiccups
                misses += 1
                if misses > 40:
                    job.status, job.error, job.finished = "failed", f"lost contact with engine: {e}", time.time()
                continue
            status = d.get("status", job.status)
            job.queue_position = d.get("queue_position") or 0
            if status == "generating" and not job.started:
                job.started = time.time()
            pv = d.get("preview") or {}
            if pv.get("b64_json"):
                key = (pv.get("pass", 1), pv.get("step", 0))
                if key != (job.pass_no, job.step) or job.preview is None:
                    job.preview = base64.b64decode(pv["b64_json"])
                    job.preview_ver += 1
                job.pass_no, job.step, job.total = pv.get("pass", 1), pv.get("step", 0), pv.get("total_steps", 0)
            if status == "completed":
                imgs = (d.get("result") or {}).get("images") or []
                job.images = [save_image(base64.b64decode(im["b64_json"]), job.params, i)
                              for i, im in enumerate(imgs)]
                job.started = job.started or time.time()
            elif status in ("failed", "cancelled"):
                job.error = ((d.get("error") or {}).get("message")) or status
            if status in TERMINAL:
                job.finished = time.time()
            job.status = status


# ---------------- gallery ----------------

def save_image(png: bytes, params: dict, index: int) -> str:
    now = datetime.now()
    day = C.OUTPUTS_DIR / now.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    seed = params.get("seed", 0)
    stem = f"{now.strftime('%H%M%S')}_{seed}_{index}"
    n = 0
    while (day / f"{stem}.png").exists():
        n += 1
        stem = f"{now.strftime('%H%M%S')}_{seed}_{index}_{n}"
    (day / f"{stem}.png").write_bytes(png)
    try:
        (day / f"{stem}.thumb.jpg").write_bytes(thumbnail(png))
    except Exception:  # noqa: BLE001
        pass
    meta = {**params, "image_index": index, "seed_used": seed + index if isinstance(seed, int) else seed,
            "created": now.isoformat(timespec="seconds")}
    (day / f"{stem}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"{day.name}/{stem}"


def safe_path(gid: str, suffix: str) -> Path | None:
    p = (C.OUTPUTS_DIR / f"{gid}{suffix}").resolve()
    try:
        p.relative_to(C.OUTPUTS_DIR.resolve())
    except ValueError:
        return None
    return p if p.exists() else None


def list_gallery(limit: int = 80, offset: int = 0) -> list[str]:
    if not C.OUTPUTS_DIR.exists():
        return []
    files = sorted(C.OUTPUTS_DIR.glob("*/*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [f"{p.parent.name}/{p.stem}" for p in files[offset:offset + limit]]


def read_meta(gid: str) -> dict:
    p = safe_path(gid, ".json")
    if not p:
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def delete_image(gid: str) -> None:
    for suf in (".png", ".json", ".thumb.jpg"):
        p = safe_path(gid, suf)
        if p:
            p.unlink(missing_ok=True)
