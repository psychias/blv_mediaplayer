# LectureAD

LectureAD adds audio description to recorded slide-based lectures, for blind and low-vision
students. It takes a lecture video and produces an enhanced audio track with description spoken
into the gaps in the lecturer's speech, plus WebVTT captions for both the lecturer and the
description.

Everything runs on the machine. No audio, video or transcript leaves it, and after the models are
installed there is no network traffic at all.

## What it does

For each lecture, the pipeline:

1. Extracts the audio, transcribes it with Whisper, and finds the silences with Silero VAD.
2. Finds the moments worth describing. Slide changes come from ffmpeg scene detection. Pointing
   gestures come from cursor tracking, which scene detection cannot see.
3. Reads the slide text with Apple Vision OCR.
4. Asks a vision-language model, for each moment, whether a description is needed and what it
   should say. The model suppresses moments the lecturer already explains in words.
5. Speaks the description with Kokoro, places it against the lecture timeline, and mixes a
   length-matched audio track.
6. Writes captions, a manifest and the audio to a cache.

Preparation happens once per lecture. Every later open reads the cache and starts instantly.

The macOS app is keyboard-operable, works with VoiceOver and meets WCAG 2.1 AA. Those features are
documented in [ACCESSIBILITY.md](ACCESSIBILITY.md).

## Requirements

- macOS on Apple Silicon, version 14 or later, to run the models.
- Python 3.11 or later.
- About 10 GB of disk for the models.
- 8 GB of RAM is enough. 16 GB is faster, because the models stay loaded between windows.

The pipeline core is plain Python and runs anywhere against mock backends. Only the real models
require Apple Silicon.

## Quick start

Install the developer environment and run the pipeline against mock backends. This needs no GPU,
no models and no network, and is what the test suite exercises.

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ladpipe run --mock --demo
```

That writes a length-matched `.wav`, a `.vtt` with both lecturer and description cues, and a
`.json` manifest into `~/Library/Application Support/LectureAD/cache`, then prints how the
descriptions were placed. Running it again is a cache hit.

The macOS app drives the same command as a sidecar and reads newline-delimited JSON events:

```bash
ladpipe run --mock --demo --json
# {"event":"progress","stage":"vl","pct":0.5,"label":"Describing moments"}
# {"event":"done","artifact":".../<hash>.wav","captions":".../<hash>.vtt","manifest":".../<hash>.json"}
```

## Running a real lecture

Install the model dependencies, fetch the weights once, then merge the adapter into its base model.

```bash
pip install -e ".[real]" ".[build]"

# Fetch the adapter, its base model, Kokoro and Whisper into models/
scripts/fetch_models.sh

# Merge the adapter into the base and quantise to 8-bit MLX
pip install peft
python scripts/merge_adapter.py \
  --base models/qwen3vl-2b-base \
  --adapter models/ad4edu-qwen3vl-2b-mm-lora/seed0 \
  --out models/ad4edu-qwen3vl-2b-mm-8bit

# Run. config/real.yaml already points at these paths.
scripts/make_sample_video.sh sample.mp4    # or use your own lecture
ladpipe run --video sample.mp4 --config config/real.yaml
```

The description model is `Psychias/ad4edu-qwen3vl-2b-sft`, an adapter trained on the AD4Edu corpus
and merged into Qwen3-VL-2B-Instruct. Merge at 8 bits. At 4 bits the merged model stops returning
the JSON its training expects and produces loose text instead.

Backends are selected in config, under `backends`: `local` for preprocessing, `mlxvlm` for the
description model, `kokoro` for speech. A `voxtral` speech backend remains for compatibility but is
not bundled. Pointing `vl.model` at different weights re-keys the cache, so the next run prepares
from scratch rather than serving a stale result.

The MLX versions are pinned in `pyproject.toml` and should not be raised casually. mlx 0.32 breaks
this quantisation and mlx-vlm 0.6.4 stopped attaching images to the prompt. Either fault silently
suppresses all description rather than failing loudly.

## Configuration

`config/real.yaml` runs the real models. `config/default.yaml` runs the mock ones. Paths in both are
relative to the config file, so a fresh clone works without editing.

| Key | Default | What it controls |
|---|---|---|
| `preprocess.scene_threshold` | 0.15 | Slide-change sensitivity. 0.3 missed 15 of 41 real slide changes on a textbook deck. |
| `preprocess.pointing` | true | Turn cursor-dwell detection on or off. |
| `preprocess.pointing_min_dwell_s` | 0.8 | How long the cursor must hold still to count as pointing. |
| `preprocess.pointing_min_gap_s` | 10.0 | Minimum spacing between pointing descriptions on one slide. |
| `preprocess.ocr` | auto | Slide text extraction. Resolves to on, because the model was trained with it. |
| `vl.max_ad_words` | 30 | Upper bound on description length. The model already fits its text to the pause. |
| `vl.verbosity` | standard | `brief`, `standard` or `detailed`. Scales the word cap. |
| `vl.image_max_side` | 640 | Keyframe size sent to the model. At 384 it invented graph detail. |
| `rungs.merge_gap_s` | 3.0 | Fuses descriptions whose moments sit this close together. |
| `rungs.extended_settle_s` | 1.2 | How long after a slide change the video pauses to describe it. |
| `extended_ad.always_pause` | true | Pause for every description instead of squeezing it into a gap. |
| `player.captions_default_on` | true | Whether captions start visible. |
| `pipeline_version` | 0.1.3 | Bump to invalidate every cached lecture. |

`extended_settle_s` exists because pausing on the exact frame the slide appears gives the viewer no
time to see it, and cuts the lecturer off mid-sentence. Waiting a moment lets the slide register and
the lecturer's own "in this diagram" be heard first.

Note that `always_pause` is on in the real profile. Descriptions therefore always pause the video
rather than being fitted into gaps. On real lectures the gaps are too short to be useful: the median
best gap is about 1.8 seconds and the longest about 4, measured in
[analysis/gap_fit_report.md](analysis/gap_fit_report.md).

## The macOS app

A SwiftUI app in `app/LectureAD/` drives the pipeline as a sidecar and plays the result. It builds
without Xcode, using the command line tools:

```bash
app/build_app.sh                       # produces app/build/LectureAD.app, ad-hoc signed
open app/build/LectureAD.app
```

The app opens a lecture, shows preparation progress announced through VoiceOver, then plays the
video frames against the cached enhanced audio. Captions appear as two tracks, lecturer and
description, which toggle independently. Description cues are styled distinctly so they are never
mistaken for the lecturer's words. Font size, contrast, caption position and video zoom are
adjustable and persist between sessions.

When a description needs more time than the lecture allows, the player pauses the video, plays the
description, then resumes. Playing a lecture never triggers the models; the player only reads a
finished cached artifact.

Every control has a keyboard shortcut and a VoiceOver label. Space plays and pauses, J and L skip,
Cmd-F searches the transcript and the descriptions, and Cmd-/ opens the shortcut list.
[ACCESSIBILITY.md](ACCESSIBILITY.md) documents the full set.

Verifying VoiceOver speech and screen-off operation is a manual step on a Mac with a display
session. Building, bundling and launching are automated.

## Streaming mode

`ladpipe stream` prepares a lecture in windows and emits an event after each one, so playback can
start after the first window instead of after the whole lecture.

```bash
ladpipe stream --video sample.mp4 --config config/real.yaml --window 90 --lookahead 2 --json
# {"event":"window_ready","index":0,"t_start":0,"t_end":90,"artifact":".../w000.wav", ...}
```

On an 8 GB machine the first window is ready in about 3.3 minutes, against roughly 24 minutes to
prepare a 90-minute lecture in full. `--lookahead` bounds how far ahead of the viewer the pipeline
works, so it does not occupy the GPU during playback.

On 16 GB or more the models stay loaded across windows. On 8 GB they load one at a time per window,
so three MLX models never sit in memory together. On 8 GB with a verbose model, preparing a window
can take longer than the window takes to play, which stalls playback; a concise model or more memory
removes that.

The player consumes these events into a single growing composition on the lecture timeline rather
than a forward-only queue, so the viewer can scrub anywhere already prepared.

## Building a distributable app

`scripts/build_dist.sh` assembles a self-contained `dist/LectureAD.app` of about 5.9 GB that runs on
any Apple Silicon Mac with nothing installed: no repository, no virtual environment, no Homebrew, no
model downloads and no network.

```bash
scripts/build_dist.sh
ditto -c -k --keepParent dist/LectureAD.app LectureAD.zip
```

Into the bundle it puts a relocatable standalone Python with the pipeline installed, the three
models at about 4.4 GB in total, and `ffmpeg` and `ffprobe` relinked to load from inside the app.
The config it writes uses paths relative to the bundle, so the app works from wherever it is
installed.

Two things to know. The bundled `ffmpeg` is copied from your Homebrew installation, which is a GPL
build, so redistributing it carries the GPL's obligation to offer source. And the cache lives in
`~/Library/Application Support/LectureAD`, never inside the bundle, so the app never writes to
itself.

## Installing on another Mac

The build is ad-hoc signed and not notarised, because notarisation needs a paid Apple Developer ID.
On first open macOS will warn. To allow it once, do either:

- Right-click the app, choose Open, then Open again.
- Run `xattr -dr com.apple.quarantine /Applications/LectureAD.app`.

After that it launches normally. The first lecture takes a few minutes to prepare and every later
open of it is instant.

## Performance

Measured on an 8 GB Apple Silicon machine, with Wi-Fi switched off, against a 49-minute anatomy
lecture.

- **One MLX runtime, vision on the GPU.** An earlier llama.cpp path fell back to the CPU on 8 GB and
  took about 40 seconds per description. MLX keeps both language and vision on the GPU, at about 4
  seconds per description.
- **Transcription on the GPU.** `preprocess.whisper_backend: mlx` runs Whisper turbo at about 0.10
  times real time, against 0.35 for the CPU build. That roughly halved first-open time. A 90-minute
  lecture takes about 24 minutes to prepare, then opens instantly from cache.
- **Voice activity detection runs first and single-threaded**, because the first import of torch is
  not thread safe. Whisper then runs alongside keyframe extraction and OCR, so preprocessing costs
  the longer of the two rather than their sum.
- **Silero VAD** is fed the already-extracted 16 kHz samples directly, because its own audio loader
  now needs a dependency this project does not carry.

## Development

```bash
source .venv/bin/activate     # the scripts below call pytest, ruff and mypy directly

scripts/test.sh               # 123 tests, no GPU and no network
scripts/lint.sh               # ruff
scripts/type.sh               # mypy, strict
scripts/demo.sh               # ladpipe run --mock --demo
scripts/contrast_audit.py     # checks every app colour against WCAG AA
scripts/analyze_gap_fit.py    # regenerates analysis/gap_fit_report.md
```

The mock backends are interchangeable with the real ones, so a passing test suite exercises the same
orchestration the real path uses. Heavy libraries are imported inside their backends, which keeps
the mock path free of them.

## Model licences

- **Qwen3-VL-2B-Instruct**, with the AD4Edu adapter merged in: Apache 2.0.
- **Kokoro-82M** and its voice packs: Apache 2.0.
- **Whisper**: MIT.

All three can be bundled and redistributed with attribution. The bundled `ffmpeg` is GPL, as noted
above. This is not legal advice; check each model card and your own institution's position before
distributing.

## Roadmap

- A `.dmg` installer. The app is built and distributable as a zip today.
- Notarisation, which needs a paid Apple Developer ID and removes the first-open warning.
