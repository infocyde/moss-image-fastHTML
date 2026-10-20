"""Engine = a stable-diffusion.cpp `sd-server` (managed subprocess, remote URL, or the mock).

The app only ever talks to the native async API (/sdcpp/v1/...), so all three modes share
one client. Switching quant / text encoder in managed mode restarts the subprocess.
"""
from __future__ import annotations

import asyncio
import shlex
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import httpx

from . import config as C


class EngineError(RuntimeError):
    pass


class Engine:
    def __init__(self) -> None:
        self.settings = C.EngineSettings.load()
        self.proc: subprocess.Popen | None = None
        self.state = "stopped"          # stopped | starting | ready | error
        self.message = ""
        self.log: deque[str] = deque(maxlen=600)
        self.caps: dict = {}
        self.started_at = 0.0
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))

    # ---------- addressing ----------
    @property
    def base_url(self) -> str:
        if self.settings.mode == "remote":
            return (self.settings.remote_url or C.SD_SERVER_URL or "http://127.0.0.1:7861").rstrip("/")
        return f"http://127.0.0.1:{C.SD_SERVER_PORT}"

    @property
    def managed(self) -> bool:
        return self.settings.mode in ("managed", "mock")

    # ---------- process control ----------
    def build_command(self) -> list[str]:
        s = self.settings
        port = str(C.SD_SERVER_PORT)
        if s.mode == "mock":
            return [sys.executable, "-u", "-m", "moss.mock_server", "--port", port,
                    "--lora-dir", str(C.DIRS["lora"]), "--model-name", s.diffusion_model or "mock-moss"]
        missing = []
        if not Path(C.SD_SERVER_BIN).exists():
            missing.append(f"sd-server binary ({C.SD_SERVER_BIN})")
        for kind, val in (("diffusion", s.diffusion_model), ("text_encoder", s.text_encoder), ("vae", s.vae)):
            if not val or not (C.DIRS[kind] / val).exists():
                missing.append(f"{kind.replace('_', ' ')} in {C.DIRS[kind]}")
        if missing:
            raise EngineError("Missing: " + "; ".join(missing) + ". Run scripts/download_models.py or switch to Mock.")
        cmd = [
            C.SD_SERVER_BIN,
            "--diffusion-model", str(C.DIRS["diffusion"] / s.diffusion_model),
            "--llm", str(C.DIRS["text_encoder"] / s.text_encoder),
            "--vae", str(C.DIRS["vae"] / s.vae),
            "--lora-model-dir", str(C.DIRS["lora"]),
            "--listen-ip", "127.0.0.1", "--listen-port", port,
            # MOSS defaults (the request overrides these per job anyway)
            "--cfg-scale", "3", "--steps", "50", "--sampling-method", "euler",
            "--scheduler", "discrete", "--flow-shift", "5",
        ]
        if s.tokenizer and (C.DIRS["tokenizer"] / s.tokenizer).exists():
            cmd += ["--tokenizer", str(C.DIRS["tokenizer"] / s.tokenizer)]
        if s.offload_to_cpu:
            cmd.append("--offload-to-cpu")
        if s.diffusion_fa:
            cmd.append("--diffusion-fa")
        if s.vae_tiling:
            cmd.append("--vae-tiling")
        if s.rng_cpu:
            cmd += ["--rng", "cpu", "--sampler-rng", "cpu"]
        if s.extra_args.strip():
            cmd += shlex.split(s.extra_args, posix=not C.IS_WINDOWS)
        return cmd

    def _reader(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self.log.append(line)
        code = proc.wait()
        self.log.append(f"[engine exited with code {code}]")
        if self.proc is proc:
            self.state = "error" if code else "stopped"
            self.message = f"engine exited ({code})" if code else "stopped"

    async def start(self) -> None:
        async with self._lock:
            await self._stop_locked()
            self.caps = {}
            if self.settings.mode == "remote":
                self.state, self.message = "starting", f"connecting to {self.base_url}"
                asyncio.create_task(self._wait_ready(timeout=30))
                return
            try:
                cmd = self.build_command()
            except EngineError as e:
                self.state, self.message = "error", str(e)
                self.log.append(f"[error] {e}")
                return
            self.log.append("$ " + " ".join(shlex.quote(c) for c in cmd))
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if C.IS_WINDOWS else 0
            try:
                self.proc = subprocess.Popen(cmd, cwd=str(C.ROOT), stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, creationflags=flags)
            except OSError as e:
                self.state, self.message = "error", f"failed to launch: {e}"
                self.log.append(f"[error] {e}")
                return
            self.state, self.message, self.started_at = "starting", "loading models…", time.time()
            threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
            asyncio.create_task(self._wait_ready(timeout=900))

    async def _wait_ready(self, timeout: float) -> None:
        deadline = time.time() + timeout
        proc = self.proc
        while time.time() < deadline:
            if self.managed and (proc is None or proc.poll() is not None):
                return  # reader thread already set the error state
            try:
                r = await self._client.get(self.base_url + "/sdcpp/v1/capabilities", timeout=5)
                if r.status_code == 200:
                    self.caps = r.json()
                    self.state, self.message = "ready", ""
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1.0)
        self.state, self.message = "error", "engine did not become ready (see log)"

    async def _stop_locked(self) -> None:
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            for _ in range(50):
                if proc.poll() is not None:
                    break
                await asyncio.sleep(0.1)
            if proc.poll() is None:
                proc.kill()
        self.state, self.message = "stopped", ""

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    def shutdown(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    # ---------- API ----------
    async def _req(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            return await self._client.request(method, self.base_url + path, **kw)
        except httpx.HTTPError as e:
            raise EngineError(f"engine unreachable: {e.__class__.__name__}") from e

    async def refresh_caps(self) -> dict:
        r = await self._req("GET", "/sdcpp/v1/capabilities")
        if r.status_code == 200:
            self.caps = r.json()
            if self.state != "ready":
                self.state, self.message = "ready", ""
        return self.caps

    async def submit(self, body: dict) -> dict:
        r = await self._req("POST", "/sdcpp/v1/img_gen", json=body, timeout=120)
        if r.status_code not in (200, 202):
            raise EngineError(f"submit failed ({r.status_code}): {r.text[:300]}")
        return r.json()

    async def job(self, server_id: str) -> dict:
        r = await self._req("GET", f"/sdcpp/v1/jobs/{server_id}", timeout=60)
        if r.status_code in (404, 410):
            return {"status": "failed", "error": {"message": f"job {r.status_code}"}}
        r.raise_for_status()
        return r.json()

    async def cancel(self, server_id: str) -> None:
        await self._req("POST", f"/sdcpp/v1/jobs/{server_id}/cancel")

    # ---------- discovery helpers ----------
    def loras(self) -> list[dict]:
        if self.caps.get("loras"):
            return self.caps["loras"]
        return [{"name": Path(p).stem, "path": p} for p in C.list_models("lora")]

    def samplers(self) -> list[str]:
        return self.caps.get("samplers") or ["euler", "euler_a", "heun", "dpm2", "dpm++2m", "lcm"]

    def schedulers(self) -> list[str]:
        return self.caps.get("schedulers") or ["discrete", "karras", "exponential", "sgm_uniform", "simple"]

    def preview_modes(self) -> list[str]:
        return self.caps.get("preview_modes") or ["none", "proj", "tae", "vae"]

    def model_name(self) -> str:
        m = self.caps.get("model") or {}
        return m.get("name") or m.get("stem") or self.settings.diffusion_model or "—"
