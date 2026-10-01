"""Merge the AD4Edu LoRA adapter into its Qwen3-VL base and convert to 8-bit MLX.

Build-time only (needs torch + peft + mlx-vlm; run after scripts/fetch_models.sh):

    .venv/bin/python scripts/merge_adapter.py \
        --base models/qwen3vl-2b-base \
        --adapter models/ad4edu-qwen3vl-2b-mm-lora/seed0 \
        --out models/ad4edu-qwen3vl-2b-mm-8bit

The merged bf16 HF checkpoint is written next to --out with a "-merged" suffix and
then quantised with mlx_vlm.convert (group size 64). Default 8 bits: the multimodal
merge quantised to 4 bits loses the trained JSON contract and rambles corpus-like
text on real keyframes, while the 8-bit build answers like the bf16 checkpoint.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="HF Qwen3-VL base checkpoint dir")
    ap.add_argument("--adapter", required=True, help="PEFT LoRA adapter dir (adapter_config.json)")
    ap.add_argument("--out", required=True, help="output dir for the quantised MLX weights")
    ap.add_argument("--q-bits", type=int, default=8, help="quantisation bits (default 8)")
    args = ap.parse_args()

    out = Path(args.out)
    merged = out.with_name(out.name.replace(f"-{args.q_bits}bit", "") + "-merged")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForImageTextToText

    print(f">> loading base {args.base} (bf16, cpu)")
    model = AutoModelForImageTextToText.from_pretrained(args.base, dtype=torch.bfloat16)
    print(f">> applying adapter {args.adapter}")
    model = PeftModel.from_pretrained(model, args.adapter)
    model = model.merge_and_unload()
    print(f">> saving merged checkpoint -> {merged}")
    model.save_pretrained(merged, safe_serialization=True)
    # Copy the processor/tokenizer files verbatim (AutoProcessor would need torchvision
    # for the video processor, which this pipeline never uses).
    for f in Path(args.base).iterdir():
        if f.suffix in {".json", ".txt", ".jinja"}:
            shutil.copy(f, merged / f.name)
    # (config.json included: transformers>=5.14 writes rope_parameters instead of the
    # rope_theta/rope_scaling keys mlx-vlm 0.6.3's Qwen3-VL TextConfig requires.)
    # The adapter ships the chat template it was trained with; keep that one.
    template = Path(args.adapter) / "chat_template.jinja"
    if template.exists():
        shutil.copy(template, merged / "chat_template.jinja")

    print(f">> quantising -> {out}")
    if out.exists():
        shutil.rmtree(out)
    subprocess.run(
        [sys.executable, "-m", "mlx_vlm", "convert", "--hf-path", str(merged),
         "--mlx-path", str(out), "-q", "--q-bits", str(args.q_bits), "--q-group-size", "64"],
        check=True,
    )
    print(f"done: {out}  (merged bf16 kept at {merged}; delete it to free ~4.4 GB)")


if __name__ == "__main__":
    main()
