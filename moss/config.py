"""Settings: env vars for paths/ports, plus a small JSON file for engine choices made in the UI."""
from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines) so we don't need python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _path(env: str, default: Path) -> Path:
    value = os.environ.get(env)
    p = Path(value).expanduser() if value else default
    return p if p.is_absolute() else (ROOT / p)


IS_WINDOWS = platform.system() == "Windows"
EXE = ".exe" if IS_WINDOWS else ""

MODELS_DIR = _path("MODELS_DIR", ROOT / "models")
OUTPUTS_DIR = _path("OUTPUTS_DIR", ROOT / "outputs")
DATA_DIR = _path("DATA_DIR", ROOT / "data")

DIRS = {
    "diffusion": MODELS_DIR / "diffusion_models",
    "text_encoder": MODELS_DIR / "text_encoders",
    "vae": MODELS_DIR / "vae",
    "tokenizer": MODELS_DIR / "tokenizers",
    "lora": MODELS_DIR / "loras",
}


def _default_server_bin() -> str:
    candidates = [ROOT / "sdcpp" / f"sd-server{EXE}", ROOT / "sdcpp" / "bin" / f"sd-server{EXE}"]
    for c in candidates:
        if c.exists():
            return str(c)
    found = shutil.which("sd-server")
    return found or str(candidates[0])


SD_SERVER_BIN = os.environ.get("SD_SERVER_BIN") or _default_server_bin()
SD_SERVER_PORT = int(os.environ.get("SD_SERVER_PORT", "7861"))  # LM Studio already owns 1234
SD_SERVER_URL = os.environ.get("SD_SERVER_URL", "").rstrip("/")  # set => remote mode default

APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("APP_PORT", "5001"))

# OpenAI-compatible LLM for the prompt / layout enhancer (LM Studio default)
ENHANCER_URL = os.environ.get("ENHANCER_URL", "http://127.0.0.1:1234/v1").rstrip("/")
ENHANCER_MODEL = os.environ.get("ENHANCER_MODEL", "")
ENHANCER_API_KEY = os.environ.get("ENHANCER_API_KEY", "lm-studio")

ENGINE_FILE = DATA_DIR / "engine.json"
MODEL_EXTS = {".gguf", ".safetensors", ".sft", ".ckpt", ".pt", ".pth"}


@dataclass
class EngineSettings:
    mode: str = "managed"          # managed | remote | mock
    remote_url: str = ""
    diffusion_model: str = ""      # filenames relative to their models/ subfolder
    text_encoder: str = ""
    vae: str = ""
    tokenizer: str = ""
    offload_to_cpu: bool = True    # needed on 12 GB cards with the 9B text encoder
    diffusion_fa: bool = True
    vae_tiling: bool = False
    rng_cpu: bool = True           # matches upstream diffusers seeds
    extra_args: str = ""
    extra: dict = field(default_factory=dict)

    def save(self) -> None:
        ENGINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ENGINE_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "EngineSettings":
        s = cls()
        if ENGINE_FILE.exists():
            try:
                data = json.loads(ENGINE_FILE.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
            except (OSError, ValueError):
                pass
        else:
            env_mode = os.environ.get("MOSS_ENGINE", "").lower()
            if env_mode in ("managed", "remote", "mock"):
                s.mode = env_mode
            elif SD_SERVER_URL:
                s.mode = "remote"
            elif not Path(SD_SERVER_BIN).exists():
                s.mode = "mock"
            s.remote_url = SD_SERVER_URL
        s.fill_defaults()
        return s

    def fill_defaults(self) -> None:
        """Pick sensible files when nothing is chosen yet (prefer Q4 on first run)."""
        def pick(kind: str, prefs: list[str]) -> str:
            files = list_models(kind)
            for pref in prefs:
                for f in files:
                    if pref.lower() in f.lower():
                        return f
            return files[0] if files else ""

        if not self.diffusion_model or not (DIRS["diffusion"] / self.diffusion_model).exists():
            self.diffusion_model = pick("diffusion", ["sft-q4_k_s", "sft-q8_0", "sft", ""])
        if not self.text_encoder or not (DIRS["text_encoder"] / self.text_encoder).exists():
            self.text_encoder = pick("text_encoder", ["q4_k_m", "qwen3.5", ""])
        if not self.vae or not (DIRS["vae"] / self.vae).exists():
            self.vae = pick("vae", ["flux2", "diffusion_pytorch_model", ""])
        if not self.tokenizer or not (DIRS["tokenizer"] / self.tokenizer).exists():
            self.tokenizer = pick("tokenizer", ["qwen3.5", "tokenizer", ""])


def ensure_dirs() -> None:
    for d in (*DIRS.values(), OUTPUTS_DIR, DATA_DIR, DATA_DIR / "uploads"):
        d.mkdir(parents=True, exist_ok=True)


def list_models(kind: str) -> list[str]:
    base = DIRS[kind]
    if not base.exists():
        return []
    exts = {".json"} if kind == "tokenizer" else MODEL_EXTS
    out = [p.relative_to(base).as_posix() for p in base.rglob("*")
           if p.is_file() and p.suffix.lower() in exts and p.name != "loras.json"
           and not any(part.startswith(".") for part in p.relative_to(base).parts)]
    return sorted(out, key=str.lower)


def human_size(path: Path) -> str:
    try:
        n = path.stat().st_size
    except OSError:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit == "GB" else f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def quant_label(filename: str) -> str:
    """Short label for a diffusion model file: Q4_K_S, Q8_0, BF16, INT8 ..."""
    name = filename.upper()
    for q in ("Q2_K", "Q3_K_M", "Q3_K_S", "Q4_0", "Q4_1", "Q4_K_M", "Q4_K_S", "Q5_0", "Q5_1",
              "Q5_K_M", "Q5_K_S", "Q6_K", "Q8_0", "F16", "BF16", "INT8", "FP8"):
        if q in name.replace("-", "_"):
            return q
    return Path(filename).suffix.lstrip(".").upper()


def lora_meta() -> dict:
    """Optional models/loras/loras.json: {"stem": {"trigger": "...", "weight": 0.7, "note": "..."}}"""
    f = DIRS["lora"] / "loras.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}
