# Accessibility

LectureAD is built for blind and low-vision students, so the app is fully operable without a
mouse, the listener controls when and how much description is spoken, and the interface meets
WCAG 2.1 Level AA.

This document covers how to drive the app, what each accessibility feature does, and the
standards and research behind those choices.

## How you control the app

There are four ways to drive the app, and every action is reachable by more than one. It works
with a mouse, with the keyboard alone, or with VoiceOver.

**Getting started.** On the launch screen, choose a preparation mode. "Start sooner" begins
playback after the first window while the rest prepares. "Smoothest playback" prepares the whole
lecture first. Then choose Open Lecture, or press Cmd-O, and pick a video.

**On-screen controls.** The transport bar carries Open, Find, Back 15, Play/Pause, Forward 15,
Mute and the scrubber. The caption row below it carries lecturer captions, description captions,
font size, high contrast, caption position and video zoom.

**Menu bar and hardware.** Every action also lives in the Playback, Audio Description, View and
Help menus. The hardware play/pause key controls the player, and every control has a VoiceOver
label.

**Keyboard shortcuts.** There are two layers. Single keys are fast and work while the player is on
screen. Menu-bar shortcuts always work, including when single keys are switched off. Press Cmd-/
in the app for the same list.

| Action | Single key | Menu shortcut |
| --- | --- | --- |
| Play or pause | `Space` or `K` | `⌥⌘P` |
| Back or forward 15 s | `J` / `L` | `⌥⌘J` / `⌥⌘L` |
| Back or forward 5 s | `←` / `→` | `⌥⌘←` / `⌥⌘→` |
| Mute or unmute | `M` | `⌥⌘U` |
| Open another lecture | none | `⌘O` |
| Play the offered description now | `D` | `⇧⌘D` |
| Skip the description being spoken | `X` | `⌥⌘X` |
| Replay the last description | `R` | `⌥⌘R` |
| Description timing: automatic, on demand, off | none | `⌥⌘1` / `⌥⌘2` / `⌥⌘3` |
| Description detail: brief, standard, detailed | none | `⌥⌘7` / `⌥⌘8` / `⌥⌘9` |
| Lecturer captions on or off | `C` | `⌥⌘C` |
| Description captions on or off | `A` | `⌥⌘A` |
| High-contrast captions on or off | `H` | `⌃⌘H` |
| Larger or smaller captions | none | `⌘=` / `⌘-` |
| Zoom video in or out | none | `⇧⌘=` / `⇧⌘-` |
| Turn single-key shortcuts on or off | none | Playback menu |
| Show the shortcut list | `?` | `⌘/` |
| Close a sheet or menu | `Esc` | none |

## Keyboard-only operation

Every function is reachable from the keyboard, and the menu bar is the single source of truth for
what exists. This satisfies WCAG 2.1.1 Keyboard.

- **Playback menu**: play and pause, back and forward 15 seconds, back and forward 5 seconds, mute.
- **Audio Description menu**: timing mode, play, skip and replay a description, detail level.
- **View menu**: caption toggles, caption size and position, video zoom.
- **Help menu**: the full shortcut sheet at Cmd-/.

Single-key shortcuts sit behind a toggle, which satisfies WCAG 2.1.4 Character Key Shortcuts. A
screen reader in browse mode consumes plain keys before the page receives them, so a user who needs
that can switch the single keys off and still reach everything through the Option-Cmd shortcuts.

Focus starts somewhere sensible, on Play/Pause in the player and on the Open button at launch, and
Tab moves through the controls with a visible focus ring.

## Controlling when descriptions are spoken

A shared scheduler decides when description is spoken, in three modes.

- **Automatic.** The video pauses, the description plays, then playback resumes.
- **On demand.** A badge reads "Description available, press D". The listener chooses when to hear
  it, skips it with X, or replays the last one with R.
- **Off.** No spoken description.

Seeking re-arms the cues, so rewinding replays the description. The batch and streaming players
share one scheduler, so the behaviour is identical in both.

Descriptions do not begin on the exact frame a slide appears. The pause waits a short settle
period, 1.2 seconds by default, so the viewer registers the new slide and hears the lecturer's own
reference to it, such as "in this diagram", before the video freezes. Pausing on the first frame
gave the slide no screen time and cut the lecturer off mid-sentence.

A short non-speech tone plays before each pause, so a listener can tell that the system paused
deliberately rather than the video stalling. The description track is bookended, opening with
"Audio description begins" and closing with "That was the final description", and descriptions less
than three seconds apart are merged into one line so they do not arrive as fragments.

## Controlling how much detail

The listener chooses brief, standard or detailed.

The level scales the word cap for each line, so brief is one short sentence and detailed allows a
few. It is available as the `--verbosity` flag, as `vl.verbosity` in config, and in the Audio
Description menu. Because the level is part of the cache key, each level caches separately.

The level can be changed during playback. The pipeline re-prepares through the sidecar while the
player stays on screen, then resumes at the playhead in streaming mode or from cache in batch mode.
Already-prepared windows replay from the cached manifest without re-running the models, so the
switch does not stall.

## Describing pointing gestures

Descriptions cover more than slide changes. When the lecturer moves the cursor and rests it on part
of a slide, that becomes a described moment of its own, for example "The cursor points to the peak
of the curve".

This matters because slide-change detection cannot see a cursor. A moving pointer changes about one
hundredth of what a slide change does, far below any sensible detection threshold, so without
dedicated tracking these gestures are invisible to the pipeline and the listener loses every "as you
can see here" the lecturer makes.

Detection is deliberately conservative. A recording with no visible cursor produces no gestures
rather than invented ones, and the model still suppresses a gesture when the lecturer's words
already identify what is being pointed at.

## Finding a moment in the lecture

Cmd-F searches the lecturer transcript and the description text, and selecting a result jumps there.
This is content-based navigation rather than scrubbing through time, following the finding that
blind and low-vision users navigate recordings by content.

## Visual contrast

The interface meets WCAG 2.1 AA contrast for both text and controls.

- A dedicated palette in `Theme.swift`, with secondary text at `#595959`, opaque bars rather than
  translucent material, high-contrast caption pills and `#FFFF00` for description captions.
- A build-time gate, `scripts/contrast_audit.py`, checks every colour literal against the required
  ratio, 4.5:1 for text and 3:1 for non-text. All 11 pairs currently pass.

## Reliability

System-initiated pauses must never take the app down with them. One such fault has been fixed:
writing a pacing credit to a sidecar that had already exited raised `SIGPIPE` and killed the app,
which under mock meant any lecture opened in streaming mode crashed immediately. `SIGPIPE` is now
ignored process-wide, so those writes fail harmlessly as the surrounding code already assumed.

## Standards and research behind these choices

**WCAG 2.1 Level AA** is the target. The criteria that shaped specific decisions:

- **2.1.1 Keyboard**: all functionality operable from the keyboard.
- **2.1.4 Character Key Shortcuts**: single-key shortcuts can be switched off.
- **1.4.11 Non-text Contrast**: controls and icons at 3:1 or better.
- **1.2.5 Audio Description (Prerecorded)**: describe only what the speech leaves uncovered.

**eCH-0059**, the Swiss accessibility standard, is the reference the contrast audit checks against.

The **MAVP study** on lecture audio description for blind and low-vision users informed four
choices: navigate by content rather than time, use a non-speech cue before a system-initiated pause,
merge descriptions less than three seconds apart, and bookend the description track.

The **DCMP Description Key** and **Mayer's redundancy principle** are secondary sources for the rule
that description should not repeat what the lecturer already says.

The operative in-repo standard is `rules_for_slides.yaml` and
`lecture_ad_standards_for_slides.md`, which set out what to describe for each kind of slide element.

## Models and tooling

All models run on the machine. Nothing is sent anywhere.

- **Description**: Qwen3-VL-2B with the AD4Edu audio-description adapter merged in, quantised to
  8-bit MLX and run through mlx-vlm. Apache 2.0, and swappable through `vl.model`.
- **Speech**: Kokoro-82M with the `af_heart` voice through mlx-audio. Apache 2.0. English
  pronunciation comes from misaki, with a bundled espeak-ng fallback for technical vocabulary.
- **Transcription**: Whisper large-v3-turbo through mlx-whisper on the GPU, with openai-whisper as a
  CPU fallback.
- **Silence detection**: Silero VAD, which finds the pauses description is placed into.
- **Slide text**: Apple Vision OCR, built into macOS. The description model was trained with this
  text alongside the keyframe, so it stays on unless `preprocess.ocr` is set to off.

The app is SwiftUI, built without Xcode using the Command Line Tools compiler and the macOS SDK. It
drives the Python pipeline as a sidecar over newline-delimited JSON, and uses ffmpeg for media.

## Verification

The current state is checked by 123 tests, strict type checking with mypy, linting with ruff, and
the contrast gate at 11 of 11 pairs passing. The app builds and runs the streaming flow.

Screen-reader speech, playback behaviour and screen-off operation are verified by hand on a Mac with
a display session, since they cannot be asserted in an automated test.
