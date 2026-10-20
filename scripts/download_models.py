"""Download MOSS-Image model files into ./models for the stable-diffusion.cpp engine.

    python scripts/download_models.py                    # Q4_K_S DiT + Qwen3.5-9B Q4_K_M + VAE + tokenizer
    python scripts/download_models.py --quant q4 q8      # both quants, switch in the UI
    python scripts/download_models.py --te Q6_K          # bigger text encoder
    python scripts/download_models.py --bf16             # full-precision DiT (Comfy-Org safetensors)
    python scripts/download_models.py --lora axiomofmind/Moss-image-nsfw-uncensored-lora-GGUF:MOSS-Image-NSFW-Uncensored-LoRA-F16.gguf
    python scripts/download_models.py --list             # just show what would be fetched

Needs: pip install huggingface_hub   (set HF_TOKEN if a repo is gated)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from moss.config import DIRS  # noqa: E402

GGUF_REPO = "axiomofmind/Moss-Image-SFT-GGUF"
QUANTS = {"q4": "MOSS-Image-SFT-Q4_K_S.gguf", "q8": "MOSS-Image-SFT-Q8_0.gguf"}
TE_REPO = "unsloth/Qwen3.5-9B-GGUF"
OFFICIAL = "OpenMOSS-Team/MOSS-Image-SFT"
COMFY = "Comfy-Org/MOSS-Image"


def plan(args) -> list[tuple[str, str, Path]]:
    items = []
    if not args.no_dit:
        for q in args.quant:
            items.append((GGUF_REPO, QUANTS[q], DIRS["diffusion"] / QUANTS[q]))
        if args.bf16:
            f = "diffusion_models/moss_image_sft_bf16.safetensors"
            items.append((COMFY, f, DIRS["diffusion"] / Path(f).name))
        if args.int8:
            f = "diffusion_models/moss_image_sft_int8_convrot.safetensors"
            items.append((COMFY, f, DIRS["diffusion"] / Path(f).name))
    if not args.no_te:
        f = f"Qwen3.5-9B-{args.te}.gguf"
        items.append((TE_REPO, f, DIRS["text_encoder"] / f))
    items.append((OFFICIAL, "vae/diffusion_pytorch_model.safetensors", DIRS["vae"] / "moss_flux2_vae.safetensors"))
    items.append((OFFICIAL, "tokenizer/tokenizer.json", DIRS["tokenizer"] / "qwen3.5_tokenizer.json"))
    for spec in args.lora or []:
        repo, _, fname = spec.partition(":")
        if not fname:
            sys.exit(f"--lora needs REPO:FILENAME, got {spec!r}")
        items.append((repo, fname, DIRS["lora"] / Path(fname).name))
    return items


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--quant", nargs="+", choices=list(QUANTS), default=["q4"], help="GGUF DiT quant(s) (default q4)")
    p.add_argument("--te", default="Q4_K_M", help="Qwen3.5-9B GGUF quant: Q4_K_M (default), Q5_K_M, Q6_K, Q8_0 …")
    p.add_argument("--bf16", action="store_true", help="also fetch the BF16 safetensors DiT (~10 GB)")
    p.add_argument("--int8", action="store_true", help="also fetch Comfy-Org's int8 safetensors DiT")
    p.add_argument("--lora", action="append", metavar="REPO:FILE", help="fetch a LoRA into models/loras (repeatable)")
    p.add_argument("--no-dit", action="store_true", help="skip diffusion model")
    p.add_argument("--no-te", action="store_true", help="skip text encoder")
    p.add_argument("--list", action="store_true", help="print the plan and exit")
    args = p.parse_args()

    items = plan(args)
    for repo, f, dest in items:
        print(f"  {'✓' if dest.exists() else '↓'} {repo}/{f}\n      → {dest.relative_to(ROOT)}")
    if args.list:
        return
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        sys.exit("pip install huggingface_hub   first")

    for repo, f, dest in items:
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"\nDownloading {repo}/{f} …")
        tmp_dir = dest.parent / ".hf_tmp"
        path = Path(hf_hub_download(repo_id=repo, filename=f, local_dir=tmp_dir))
        shutil.move(str(path), dest)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"  saved {dest.relative_to(ROOT)}")
    print("\nDone. Start the app and pick the model in the header (⚙ for text encoder / VAE).")


if __name__ == "__main__":
    main()
