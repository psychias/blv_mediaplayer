# Architecture

The pipeline core depends only on protocols. Concrete models, media libraries and the user
interface plug in at the edges. Importing the core and running the mock path pulls in no GPU
libraries, no model weights and no network calls.

```
ladpipe core
  orchestrator   sequences the stages and implements none of them
  stages         preprocess, prefilter, vl, tts, rungs, mixer, captions, cache
  protocols      Preprocessor, VLBackend, TTSBackend

edges, which plug in through those protocols
  real backends  ffmpeg, Whisper, Silero VAD, Apple Vision, the MLX models
  mock backends  deterministic, no models, used by the test suite
  macOS app      reads JSON events from the CLI and plays a finished artifact
```

## Module boundaries

Five rules keep the core independent of what plugs into it.

**One responsibility per module.** `preprocess`, `prefilter`, `vl`, `tts`, `rungs`, `mixer`,
`captions` and `cache` each do one thing. The orchestrator sequences them and implements none of
them.

**Adding a backend touches two places.** A new description or speech backend is a new class
implementing the protocol, plus one branch in `factory.py`. The orchestrator and the other stages
do not change.

**Mock and real backends are interchangeable.** The orchestrator cannot tell which it is holding,
and the mock path runs the same orchestration as the real one. That is what makes a passing test
suite meaningful for the real path.

**Protocols stay narrow.** `Preprocessor`, `VLBackend` and `TTSBackend` are separate, each defined
in its own `base.py`.

**Heavy libraries are imported inside their backend class, never at module level.** Whisper,
mlx-vlm, mlx-audio, Silero and imagehash are only loaded when the backend that needs them is built.

## Data flow

1. **Preprocess** returns the lecturer's audio track and an ordered list of moments. A moment is a
   keyframe, the transcript around it and the slide text. The description model never sees the
   video, only one moment at a time.
2. **Prefilter** drops a moment without calling the model, but only when the slide text and the
   transcript overlap above a threshold and there is no visual signal. The test is deliberately
   one-sided: a wrong "redundant" loses a useful line, while a wrong "unclear" costs one cheap
   model call.
3. **Describe.** The model returns a decision for each surviving moment, either a description or a
   suppression with a reason. Before describing, the pipeline asks the model one short question
   about the frame, because the moment type it is given strongly affects whether it describes
   anything at all. Labelled as a plain slide it suppresses almost everything, including graphs.
4. **Speak.** An estimated duration drops obviously unplaceable lines before anything is
   synthesised. The placement is then re-checked against the real clip length, so it is honest
   about the audio that exists rather than the estimate.
5. **Place.** Each line is placed in the least disruptive way that fits: insert into a gap,
   compress slightly, shift to a sentence boundary within a hard five-second cap, pause the video
   and describe, mark the moment with a short non-speech cue, or drop it. Per-option counts go into
   the manifest.
6. **Mix.** Lines that fit the lecture are overlaid onto the base track, producing audio of exactly
   the original length. Lines that need a pause are not mixed in. They go to a separate descriptions
   track and an accompanying audio file, and the player pauses the video to play them, so the played
   timeline is longer than the audio track.
7. **Captions.** Two WebVTT files: a captions track with lecturer speech and the descriptions that
   fit the lecture, and a descriptions track with the ones that need a pause.
8. **Cache.** The artifact set is keyed on the video hash, the pipeline version, which backends ran
   and a hash of the tuning that affects output. Changing the model or a threshold re-keys the cache,
   so a stale result is never served.

## Finding moments

Two detectors feed step 1, because they see different things.

**Slide changes** come from ffmpeg scene detection. The threshold is tuned low, at 0.15, because
0.3 missed 15 of 41 real slide changes on a textbook deck. Near-duplicate keyframes are dropped by
perceptual hash.

**Pointing gestures** come from cursor tracking in `preprocess/pointing.py`. Scene detection cannot
find these: a moving cursor scores about 0.01 where the threshold is 0.15, so it is invisible by two
orders of magnitude. Frames are decoded small and grey, differenced, and the centroid of what
changed is followed. A deliberate move followed by a hold becomes a pointing moment, with a pointer
drawn onto the keyframe so the model can see what is being indicated. It fails closed: a recording
with no cursor produces no gestures, and a change too large to be a cursor is treated as animation
and resets tracking.

This matters more than it sounds. Pointing is the largest class in the corpus the description model
was trained on, at 3,559 of 6,868 moments, so without this detector the model's best-trained
behaviour is never used.

## Running the models

**One runtime.** Description and speech both run on MLX. An earlier llama.cpp path was dropped
because its vision encoder fell back to the CPU on 8 GB machines, at roughly 40 seconds per call
against 4 seconds for MLX. One runtime is also simpler to bundle and keeps the two models version
compatible. A single backend class loads whatever weights `vl.model` points at, since mlx-vlm
detects the architecture, so there is no class per model.

**Models load one at a time.** The orchestrator runs the description loop, releases that model, then
loads speech. They are never resident together, which is what lets the pipeline fit in 8 GB and run
comfortably in 16 GB.

**Whisper and the description model each run in a child process.** This is a correctness
requirement, not a speed optimisation. The pinned MLX stack begins returning NaN logits after
roughly 70 generations in one process. Those decode to punctuation, the parser discards them, and
the result is that the back half of a lecture is silently left undescribed. Reloading the weights
does not clear it; only a fresh process does. So the parent restarts the description worker every 32
generations and again if a bad reply appears, and transcription runs in its own child, which also
frees its memory before the description model loads.

**The dependency versions are pinned deliberately.** mlx 0.32 breaks this quantisation and
mlx-vlm 0.6.4 stopped attaching images to the prompt. Either fault silently suppresses all
description rather than failing, so raising these versions needs a real end-to-end check.

## Placing descriptions

The placement options above form a ladder from least to most disruptive. On real lectures, though,
the gaps in speech are too short to use: the median best gap is about 1.8 seconds and the longest
about 4. Gap-only placement therefore drops most description, which is why pausing the video is an
option at all.

The shipped configuration sets `extended_ad.always_pause`, so every description pauses rather than
being squeezed into a gap. The ladder still exists and still runs when that setting is off.

A pause starts a short settle after the slide change rather than on the first frame of it, so the
viewer sees the slide and hears the lecturer's own reference to it before the video freezes.

## Player and processor are separate

The processor produces and caches an artifact. The player consumes a finished cached artifact and
never starts the model path. Pressing play cannot trigger inference. This is what makes playback
predictable on a machine that would otherwise be busy running models.

## Streaming

`stream.py` prepares a lecture in windows so playback can begin after the first one instead of after
the whole lecture. The first window is ready in about 3.3 minutes on an 8 GB machine.

It reuses every backend unchanged. A window source splits the work: one slices the video with ffmpeg
and preprocesses each window, which is what makes the first window fast, and a simpler one
preprocesses once and splits by time for the mock path. Per-window artifacts carry timestamps on the
lecture's own timeline, a manifest grows an entry per window, and the CLI emits an event as each
window completes. The hard five-second cap on shifting a line is what makes per-window processing
safe, since no line can move far enough to land in a window that has already been written.

**Memory.** Three resident MLX models do not fit an 8 GB GPU. Above 14 GB the description and speech
models stay warm across windows. Below it they load one at a time per window, so they never coexist.
The cost is reload overhead, and on 8 GB with a verbose model a window can take longer to prepare
than it takes to play, which stalls playback. A concise model or more memory closes that gap.

The player consumes these events into a single composition that grows along the lecture timeline,
rather than a forward-only queue, so the viewer can scrub anywhere already prepared.

## The macOS app

A SwiftUI app launches the pipeline as a sidecar subprocess and consumes its newline-delimited JSON
events. It builds without full Xcode: the Command Line Tools compiler and the macOS SDK ship the
frameworks it needs, so the build script compiles and assembles the app directly with no project
file.

The player composes the original video track with the cached enhanced audio, dropping the original
audio. Captions are parsed from the two WebVTT files and drawn as SwiftUI overlays rather than using
the built-in subtitle track, because the two kinds of cue have to be toggled, styled, resized and
repositioned independently. Descriptions that need a pause are realised in the player: at each cue it
pauses the video, plays the matching segment, then resumes.

The sidecar command is config-driven, so the same app runs against the development pipeline or a
bundled self-contained copy without a code change.

## Offline guarantee

There are no cloud dependencies in the pipeline or the app, and neither makes a network call. Models
are fetched once at build time by the developer and bundled into the app, so a shipped copy reaches
nothing on first launch or any launch after it.
