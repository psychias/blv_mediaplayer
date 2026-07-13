# LectureAD — offline lecture audio description for blind & low-vision students

LectureAD takes a recorded slide-based lecture and produces an **enhanced audio track** with
**audio description (AD)** woven into the gaps in the lecturer's speech, plus **WebVTT captions**
(lecturer speech + AD text). It is **fully offline** and built for macOS / Apple Silicon. The
heavy work runs once per lecture (**prepare-then-cache**); every later open is instant.

> **Status: Phase 1 complete** — the Python core (`ladpipe`) runs end-to-end on mock backends.
> Real on-device models (Phase 2), the SwiftUI app (Phase 3) and the `.dmg` (Phase 4) follow.

## What works today (Phase 1)

The full pipeline — preprocess → redundancy pre-filter → VL decision → TTS → rung-ladder placement
→ length-matched mix → WebVTT captions → cache — runs against **mock backends** that need **no GPU,
no models, and no network**. This proves the plumbing and is what CI exercises.

## Requirements

- macOS, Apple Silicon (Phase 2+). The Phase 1 core is pure Python and cross-platform.
- Python 3.11+.

## Install (developer)

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # core + lint/type/test tooling (no heavy model deps)
```

Heavy real-backend deps live in the `real` extra and are **not** needed for Phase 1:
`pip install -e ".[real]"` (Phase 2).

## Run the mock demo (Phase 1 gate)

```bash
ladpipe run --mock --demo
```

This writes a length-matched `.wav`, a `.vtt` with lecturer **and** AD cues, and a `.json` manifest
into the cache dir (default `~/Library/Application Support/LectureAD/cache`), and prints the
per-rung spread. Re-running is an instant cache hit.

Sidecar mode (the macOS app, Phase 3, drives this) emits newline-delimited JSON events:

```bash
ladpipe run --mock --demo --json
# {"event":"progress","stage":"vl","pct":0.5,"label":"Describing moments"}
# {"event":"done","artifact":".../<hash>.wav","captions":".../<hash>.vtt","manifest":".../<hash>.json"}
```

## Run on a real lecture (Phase 2)

The real backends are implemented on a **single MLX runtime**: `RealPreprocessor` (ffmpeg + Whisper +
Silero VAD + ffmpeg scene-detection keyframes + optional Apple Vision OCR, Whisper running
concurrently with vision so preprocessing time is `max`, not `sum`), `MlxVlmBackend` (a 4-bit MLX VL
model via mlx-vlm — vision GPU-resident), and `VoxtralTTSBackend` (Voxtral-4B-TTS via mlx-audio). All
heavy libraries are lazy-imported inside the backends, so the core/mock path imports zero heavy deps.

```bash
# 1. install heavy deps (Apple Silicon) and build-time tooling
pip install -e ".[real]" ".[build]"

# 2. fetch + stage models once (needs internet once; the student never downloads anything)
scripts/fetch_models.sh                 # -> models/gemma4-e2b-it-4bit, models/voxtral, models/whisper

# 3. config/real.yaml already selects the real backends:
#    backends: {preprocess: local, vl: mlxvlm, tts: voxtral}
#    vl.model -> models/gemma4-e2b-it-4bit   (or a repo id, or your fine-tuned MLX weights)
#    tts.voxtral.model_path -> models/voxtral

# 4. run (fully offline once models are present)
scripts/make_sample_video.sh sample.mp4   # or use your own lecture
ladpipe run --video sample.mp4 --config config/real.yaml
ladpipe run --video sample.mp4 --config config/real.yaml   # second run = instant cache hit
```

Backend selection is **config-only**: set `backends.{preprocess,vl,tts}` to `local`/`mlxvlm`/`voxtral`.
The VL **model** is also config-only — `vl.model` points at any 4-bit MLX VL weights (Gemma or
Qwen3-VL; mlx-vlm auto-detects). Swapping in the fine-tuned model = convert it to MLX
(`mlx_vlm.convert`) and repoint `vl.model`; that re-keys the cache automatically (§6.1). The app
auto-selects by RAM via `vl.model_large` (used on `>= model_large_min_ram_gb`).

> **Requires:** `mlx-vlm` pinned **past the Gemma-4 PLE-quant fix (PR #893)** — early 4-bit Gemma-4
> quants emitted gibberish. Smoke-test 4-bit output on one slide; gibberish ⇒ bump mlx-vlm (the
> `-bf16` build is the higher-memory fallback). Use the **MLX** build of the model, not the `-gguf`
> or `-w4a16-ct` variants. OCR (`preprocess.ocr: auto|on|off`) uses macOS-native Apple Vision and is
> skipped when the VL model reads slides itself (Gemma).

### Verified on a real 49-min anatomy lecture (Apple Silicon, 8 GB)

The full real pipeline was validated end to end and **with Wi-Fi physically disabled** — Whisper
transcript, Silero VAD, VL slide descriptions, Voxtral synthesis, length-matched mix + both WebVTT
tracks + manifest, all offline. A second run is an instant cache hit; changing `vl.model` invalidates
the cache.

Operational notes:

- **One MLX runtime, vision GPU-resident.** The earlier llama.cpp/GGUF VL path fell back off the GPU
  on 8 GB (~40 s/call); 4-bit MLX via mlx-vlm keeps language **and** vision on the GPU (~4 s/call).
  VL and TTS are still loaded sequentially (VL over the moment loop, then TTS) to fit 8–16 GB.
- **Transcription on the GPU.** `preprocess.whisper_backend: mlx` runs Whisper-turbo via `mlx-whisper`
  at ~0.10× real-time (measured) vs ~0.35× for CPU `openai-whisper` — it cut first-open time roughly
  in half (a 90-min lecture ≈ 24 min on 8 GB, then instant from cache). `openai` is the CPU fallback.
- **Silero VAD** is fed the already-extracted 16 kHz samples directly (its `read_audio` now needs
  `torchcodec`, which we don't depend on).
- **Gap-fit / extended AD.** On a real lecture, gaps are tiny (median best-gap ~1.8 s, max ~4 s; see
  `analysis/gap_fit_report.md`), so gap-only placement drops most AD. The rung ladder therefore uses
  **rung 0 (pause-and-describe)** for high-value content that fits no gap — the played timeline grows
  by the total pause time; the audio track stays length-matched. The rules YAML is condensed to its
  operative `rule:` statements before prompting (32 KB → 9 KB).

## Develop

```bash
scripts/test.sh             # pytest (no GPU/network)
scripts/lint.sh             # ruff
scripts/type.sh             # mypy --strict
scripts/demo.sh             # ladpipe run --mock --demo
scripts/fetch_models.sh     # build-time: fetch + stage bundled models (Phase 2/4)
scripts/make_sample_video.sh  # tiny synthetic 2-slide lecture for testing the real path
```

## macOS app (Phase 3)

A native **SwiftUI** app (`app/LectureAD/`) drives the Python core as a sidecar over the JSON-events
protocol and plays the result. It builds **without Xcode** (CLT `swiftc` + the macOS SDK):

```bash
app/build_app.sh                     # -> app/build/LectureAD.app  (ad-hoc signed)

# run in development (real backends + the verified 8 GB model)
LADPIPE_CMD="$PWD/.venv/bin/ladpipe" LADPIPE_CONFIG="$PWD/config/real.yaml" \
  open app/build/LectureAD.app
# or a no-models UI demo: add LADPIPE_MOCK=1 LADPIPE_CONFIG="$PWD/config/default.yaml"
```

The app: pick a lecture → **accessible, VoiceOver-announced** preparation progress (driven by the
sidecar events) → a player that shows the **video frames + cached enhanced audio** (one
`AVMutableComposition`; the original audio track is dropped) with **caption overlays**. Two caption
tracks (lecturer + AD) toggle independently, AD cues are styled distinctly (yellow, "AD:"), and
font size / high-contrast / position / video zoom are adjustable and persisted. **Extended AD
(rung 0)** is realised by the player: it pauses the video at each `descriptions` cue, plays the
matching `.ext.wav` segment, then resumes. All controls have VoiceOver labels and keyboard shortcuts
(space play/pause, J/L skip ±15 s); the player only ever reads a finished cached artifact — pressing
play never triggers inference. The sidecar is the dev `ladpipe` now; Phase 4 swaps in the frozen
bundled binary (no code change).

> Interactive verification (VoiceOver speech, playback, screen-off operation) is a human step on a
> Mac with a display session; the build/bundle/launch are automated by `app/build_app.sh`.

## Streaming — start in under 5 minutes

`ladpipe stream` prepares the lecture in **windows** and emits a `window_ready` event after each, so
playback can begin after window 0 instead of after the whole lecture (§12):

```bash
ladpipe stream --video sample.mp4 --config config/real.yaml --window 90 --json
# {"event":"window_ready","index":0,"t_start":0,"t_end":90,"artifact":".../w000.wav", ...}
```

Measured on 8 GB: **first window ready ~3.3 min** (vs ~24 min to fully prepare a 90-min lecture) —
the player can start then while the rest streams in. On ≥14 GB RAM the VL and TTS models stay warm
across windows; on 8 GB they load sequentially per window (so three MLX models never sit in the GPU
together). Caveat: on 8 GB with the verbose *base* model, per-window prep can exceed a window's
playback length (possible stalls); concise fine-tuned AD and/or ≥16 GB remove that. Player-side
consumption (AVQueuePlayer over `window_ready`) is the remaining integration.

## Captions

Captions are **on by default** (`player.captions_default_on: true`). The WebVTT carries two
independently toggleable cue kinds — lecturer speech and audio description — with AD cues marked
distinctly (`<c.ad>` / `AD:` prefix) so description is never mistaken for the lecturer's words. The
Phase 3 player adds low-vision controls (font size, contrast, position) and slide zoom.

## Building the `.dmg` and bundled models (Phase 4 — not yet implemented)

The shipped app **bundles all models** (~5–7 GB: the 4-bit MLX VL model, the MLX Voxtral build,
Whisper); the student downloads nothing and runs fully offline from first launch. Models are fetched
**once at build time** by the developer (`scripts/fetch_models.sh`), then baked into the `.app`.

### Gatekeeper (unsigned build) — one-time first-open step

The app is **ad-hoc signed, not notarized** (no paid Apple Developer ID). On first open on another
Mac, macOS Gatekeeper will warn. To open it the first time, do **one** of:

- Right-click (or Control-click) the app in Applications, choose **Open**, then **Open** again; or
- Run: `xattr -dr com.apple.quarantine /Applications/LectureAD.app`

After this one-time step the app launches normally. This friction is inherent to unsigned
distribution; the build keeps signing/notarization as a config-only upgrade if a Developer ID is
ever added (`SIGNING_IDENTITY` in `scripts/build_dmg.sh`). The `$99/yr` Apple Developer Program is
the real fix for wider release.

## Licenses of bundled models

- **VL model (Gemma 4 / Qwen3-VL, MLX)** — permissive (Apache-2.0); bundle freely with attribution.
- **Voxtral-4B-TTS + reference voices** — **CC-BY-NC-4.0**: non-commercial, attribution required.
  Bundling it into the installer is redistribution, so this **blocks any commercial release** of a
  bundle containing Voxtral. Not legal advice — confirm against each model card and your institution
  before distributing.
- **Whisper** — MIT.

Full attributions are documented in the repo and shown in-app (Phase 3).
