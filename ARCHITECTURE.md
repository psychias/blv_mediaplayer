# Architecture

LectureAD is a clean / hexagonal design. The **core pipeline depends only on abstractions**;
concrete models, audio libs, and the UI plug in at the edges (dependency inversion). Importing the
core (`ladpipe`) and running the mock path pulls in **zero heavy / GPU / network dependencies**.

```
                 ┌────────────────────────── ladpipe core (UI-agnostic) ──────────────────────────┐
 video ─▶ Preprocessor ─▶ prefilter ─▶ VLBackend ─▶ TTSBackend ─▶ rungs ─▶ mixer ─▶ captions ─▶ cache
                 │  (Protocol)            (Protocol)   (Protocol)                                    │
                 └──────── orchestrator only *sequences* these; it implements none ─────────────────┘
                                  ▲                          ▲
              factory builds backends from config      progress events (JSON) ─▶ macOS shell (Phase 3)
```

## The boundaries (SOLID)

- **S — one responsibility per module.** `preprocess`, `prefilter`, `vl`, `tts`, `rungs`, `mixer`,
  `captions`, `cache`, `orchestrator`. The orchestrator sequences; it implements no stage.
- **O — open for extension.** A new VL/TTS/preprocess backend is a new class implementing the
  Protocol plus one branch in `factory.py`. No edits to the orchestrator or other stages.
- **L — substitutable.** Mock and real backends are interchangeable; the orchestrator cannot tell
  which it holds, and the mock path runs the *same* orchestration the real path will (the Phase 1
  tests are therefore meaningful for the real path too).
- **I — narrow protocols.** `Preprocessor`, `VLBackend`, `TTSBackend` are separate (`*/base.py`).
- **D — depend on abstractions.** Stages depend on the Protocols. Heavy libs (`whisper`,
  `mlx-vlm`, `mlx-audio`, `silero-vad`, `imagehash`) are **lazy-imported only inside their
  concrete backend classes**, never at module top level.

### Single MLX runtime (§6.2)

VL (`mlx-vlm`) and TTS (`mlx-audio`) share **one runtime — MLX**. The earlier llama.cpp/GGUF VL
path was dropped: on 8 GB the llama.cpp vision encoder fell back off the GPU (~40 s/call); 4-bit MLX
weights keep the language **and** vision encoder GPU-resident. One runtime is simpler to bundle and
keeps the two heavy models version-compatible. `MlxVlmBackend` loads **either** trained model
(Gemma or Qwen3-VL) from `vl.model` — mlx-vlm auto-detects the architecture, so there is no
per-model class. The app auto-selects by RAM (smaller model on 8 GB, `model_large` on 16 GB+).

### One deviation from the spec layout

`audio.py` (stdlib-only PCM/WAV helpers) and `captions.py` (WebVTT generation) are not in the
original layout sketch. Both trace to concrete requirements (length-matched WAV output across stages;
the WebVTT captions output added in §3/§7/§8) and each is a single-responsibility module, so they
are justified rather than speculative. `AudioClip` stays in `types.py` as specified.

## Data flow

1. **Preprocessor** returns the lecturer base audio track + ordered `Moment`s. A moment is a
   keyframe + transcript window + slide OCR — the VL model never sees "the video".
2. **prefilter** suppresses a moment *without* a VL call only when OCR/transcript cosine ≥ threshold
   **and** there is no visual signal. Asymmetric on purpose (a wrong "redundant" loses a high-value
   line; a wrong "ambiguous" costs one cheap VL call).
3. **VLBackend** decides `{emit | suppress}` + AD text per surviving moment.
4. **TTSBackend** synthesises emits. `estimate_duration` gates obvious rung-5 drops *before*
   synthesis; the rung ladder then re-checks against the **actual** clip duration (estimate → gate →
   synth → reconcile), so placement is honest against real audio length, never the estimate.
5. **rungs** place each line, least-disruptive first: 1 gap-insert · 2 compress (≤ max factor) ·
   3 time-shift (≤ 5 s, hard cap) · **0 pause-and-describe (extended AD)** for high-value content
   that fits no gap · 4 placeholder marker (low-value) · 5 drop (low-value). Per-rung counts (0–5)
   go into the result/manifest. The gap-fit analysis on a real lecture showed gap-only placement
   drops most AD, which is why rung 0 exists (`extended_ad.enabled`, default on).
6. **mixer** overlays rungs 1–4 onto the base track → a track of **exactly** the original length.
   Rung-0 clips are NOT mixed in; they go to the descriptions track + a bundled `.ext.wav`, and the
   player pauses the video to play them — so the *played* timeline is longer than the audio track.
7. **captions** emit two WebVTT files: the captions track (lecturer cues + rung 1–3 AD cues,
   `<c.ad>`) and the **descriptions** track (rung-0 extended-AD cues, `<c.ad-extended>`). Near-free.
8. **cache** keys the artifact set (wav + captions vtt + descriptions vtt + optional ext.wav +
   manifest) on `sha256(video) + pipeline_version + backend_ids + config_hash`.

## Model loading & footprint (§6.2)

The orchestrator runs the VL loop, **releases vision**, then loads TTS — sequential, never
concurrent — so two ~4B models + Whisper fit in 16 GB and degrade gracefully on 8 GB. The app bundles
two inference runtimes (llama.cpp + MLX); that is the swappable-backend boundary doing its job.

## The base → fine-tuned VL swap (§6, §6.1)

The VL model runs through one `MlxVlmBackend` (mlx-vlm auto-detects the architecture). The base
placeholder is `mlx-community/gemma-4-e2b-it-4bit` (4-bit MLX, ~3.6 GB, fits 8 GB with vision on the
GPU). Swapping in the fine-tuned model is a **config change only** — convert the fine-tune to MLX
(`mlx_vlm.convert`) and point `vl.model` at it. Because `vl.model` feeds `config_hash`, the swap
changes the cache key and invalidates stale artifacts automatically. Same family + same MLX format ⇒
a pure config swap; no new class. Pin `mlx-vlm` past the Gemma-4 PLE-quant fix (PR #893) and
smoke-test 4-bit output before trusting it (gibberish ⇒ that bug, not the pipeline).

## Player / processor separation (§1)

The **processor** (`orchestrator`) produces and caches the artifact. The **player** (Phase 3)
consumes a finished cached artifact only and **never** starts the inference path. Pressing play
cannot trigger inference.

## Streaming (`ChunkedStreamingOrchestrator`, `stream.py` — BUILT)

Prepares the lecture in **windows** so playback can begin after the first window instead of after
the whole lecture — the answer to "start watching in under 5 minutes" (measured ~3.3 min to first
window on 8 GB). It **reuses every backend unchanged**; a *window source* splits the work:
`_SliceSource` ffmpeg-slices the video and runs preprocess per window (first window ready fast — the
real win), `_PartitionSource` runs preprocess once then splits by time (mock path / fallback).
Per-window artifacts carry **global timestamps**; a `stream.json` manifest grows one entry per
window; the CLI `stream` subcommand emits a `window_ready` event each time. The hard 5 s rung cap
bounds how far an AD line can shift, which is what makes per-window processing safe.

**Memory (§6.2 applied per window).** Three resident MLX models (Whisper + VL + TTS) overflow the
8 GB GPU. So streaming keeps VL+TTS warm across windows only when RAM ≥ 14 GB; below that it loads VL,
runs it, frees it, then loads TTS (sequential, per window) so the two never coexist. Trade-off:
per-window reloads add overhead, so on 8 GB with the verbose base model a window can take longer than
it plays (playback may stall between windows). Concise fine-tuned AD (less TTS) and/or ≥16 GB
(warm, no reloads) close that gap. The player-side consumption (AVQueuePlayer over `window_ready`)
is the remaining integration.

## macOS shell choice (Phase 3 — DECIDED: SwiftUI)

A **SwiftUI** app (`app/LectureAD/`) launches the Python core as a **sidecar** subprocess and consumes
the CLI's newline-delimited JSON events (`cli.py`). Confirmed buildable **without full Xcode**: the
Command Line Tools `swiftc` + macOS SDK ship `SwiftUI`/`AVKit`/`AVFoundation`, so `app/build_app.sh`
compiles and assembles `LectureAD.app` directly (no `.xcodeproj`/`xcodebuild`). The Toga fallback
(§8) is therefore not needed. **The core is unchanged** — the shell only consumes the JSON protocol
and plays a finished cached artifact; it never starts inference (§1).

Player design: an `AVMutableComposition` plays the original **video track** with the cached
**enhanced-audio `.wav`** (the original audio track is dropped). Captions are parsed from the two
WebVTT files and rendered as **SwiftUI overlays** (not AVKit's built-in legible track) so the two cue
kinds can be independently toggled, styled, resized, and repositioned (low-vision requirement, §8).
Extended AD (rung 0) is realized by the player: at each `descriptions` cue it pauses the video, plays
the matching segment of the bundled `.ext.wav`, then resumes (the Able-Player extended-description
pattern). The sidecar command is config-driven (a bundled frozen binary in release; the dev `ladpipe`
in development) so the same app works in both.

## Offline guarantee (§2.1, §10)

No cloud SDKs in the core or app target; no network in the pipeline or player. Models are fetched
**once at build time** by the developer and bundled into the `.app` (§9.1); the shipped app makes no
network calls, including first launch.
