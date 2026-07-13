# Accessibility Overhaul — what this version adds

This version makes LectureAD **fully operable without a mouse**, gives the listener
**control over when and how much** audio description (AD) is spoken, and brings the
whole UI to **WCAG 2.1 AA**. It was ported onto this repo from the `accessibility-overhaul`
branch of the sibling `AD_video_player` repo and merged with this copy's newer features
(streaming, `smoothPlayback`, find-in-lecture search).

- Port commit: `1a86bbf`
- Follow-up crash fix: `8c6db1c` (see [Reliability](#reliability) below)

Verified end-to-end under the mock pipeline via an automated GUI walkthrough (keyboard
driving + screenshots): 94 pytest tests, strict mypy, ruff, contrast audit 11/11 AA, and
the app builds and runs the streaming flow.

---

## How you control the app

The app can be driven four ways, and every action is reachable by more than one — so it
works with a mouse, with the keyboard alone, or with VoiceOver.

**Getting started.** On the launch screen, pick a preparation mode — **Start sooner**
(streaming: playback begins after the first window while the rest prepares) or **Smoothest
playback** (batch: the whole lecture prepares first) — then **Open Lecture** (or `⌘O`) and
choose a video. You then land in the player.

**On-screen controls.** The transport bar (Open · Find · Back 15 · Play/Pause · Forward 15 ·
Mute · scrubber) and, below it, the caption row (Lecturer captions · AD captions · font size
A/A · High contrast · Caption position · video zoom).

**Menu bar / hardware.** All actions live in the **Playback**, **Audio Description**, **View**
and **Help** menus. The hardware play/pause media key also controls the player, and every
control has a VoiceOver label.

**Keyboard shortcuts.** Two layers — fast **single keys** while the player is on screen (can
be turned off for WCAG 2.1.4), and **menu-bar shortcuts** that always work even with single
keys off. Press `⌘/` in the app for this list.

| Action | Single key | Menu shortcut |
| --- | --- | --- |
| Play / pause | `Space` or `K` | `⌥⌘P` |
| Back / forward 15 s | `J` / `L` | `⌥⌘J` / `⌥⌘L` |
| Back / forward 5 s | `←` / `→` | `⌥⌘←` / `⌥⌘→` |
| Mute / unmute | `M` | `⌥⌘U` |
| Open another lecture | — | `⌘O` |
| Play the offered description now | `D` | `⇧⌘D` |
| Skip the description being spoken | `X` | `⌥⌘X` |
| Replay the last description | `R` | `⌥⌘R` |
| AD timing: Automatic / On-Demand / Off | — | `⌥⌘1` / `⌥⌘2` / `⌥⌘3` |
| AD detail: Brief / Standard / Detailed | — | `⌥⌘7` / `⌥⌘8` / `⌥⌘9` |
| Lecturer captions on/off | `C` | `⌥⌘C` |
| AD captions on/off | `A` | `⌥⌘A` |
| High-contrast captions on/off | `H` | `⌃⌘H` |
| Larger / smaller captions | — | `⌘=` / `⌘-` |
| Zoom video in / out | — | `⇧⌘=` / `⇧⌘-` |
| Turn single-key shortcuts on/off | — | Playback menu |
| Show this shortcut list | `?` | `⌘/` |
| Close a sheet / menu | `Esc` | — |

Two AD-specific behaviours: in **On-Demand** timing a "Description available — press D" badge
appears and you choose when to hear each description; and the **detail level** can be changed
mid-playback, which re-prepares and resumes where you were.

---

## Improvements in this version

### Keyboard-only operation (WCAG 2.1.1 / 2.1.4)

Everything is reachable from the keyboard, and every action lives in the **menu bar** as
the single source of truth (`AppCommands.swift`):

- **Playback** menu — Play/Pause, Back/Forward 15 s, Back/Forward 5 s, Mute (all `⌥⌘`).
- **Audio Description** menu — timing mode, Play/Skip/Replay description, detail level.
- **View** menu — caption toggles, caption size/position, video zoom.
- **Help → Keyboard Shortcuts (`⌘/`)** — a full, searchable shortcut sheet
  (`KeyboardHelpView.swift`).
- **Single-key player shortcuts** (`Space` `K` `J` `L` `M` `D` `X` `R` `C` `A` `H` `?`,
  bare `←/→` = ±5 s) via `PlayerShortcutLayer`, behind a **WCAG 2.1.4 "Single-Key Shortcuts"
  toggle** so they can be turned off — the menu-bar `⌥⌘` shortcuts always work.
- Sensible initial focus (`defaultFocus` on Play/Pause and the Open button) and Tab
  traversal with a visible focus ring.

### AD timing control

A shared `ADScheduler` decides when AD is spoken, in three modes:

- **Automatic** — pause the video and describe (extended AD, "rung 0").
- **On-Demand** — a **"Description available — press D"** badge appears; the listener
  chooses when to hear it (`D`), skip (`X`), or replay the last one (`R`).
- **Off** — no spoken description.

Seeking re-arms cues (rewinding replays the AD), and both the batch and streaming players
share the one scheduler.

### AD verbosity control (brief / standard / detailed)

The listener picks how much detail each description carries:

- Changes the VL prompt's style budget and scales the per-line word cap
  (`effective_max_ad_words`), so *brief* is one short sentence and *detailed* allows a few.
- Exposed as a `--verbosity` CLI flag, a `vl.verbosity` config field (part of the cache key,
  so each level caches separately), and an in-app menu (`⌥⌘7/8/9`).
- **Switchable mid-session**: changing the level re-prepares via the sidecar while keeping
  the player on screen and **resumes at the playhead** (streaming) or from cache (batch).

### Streaming resume-from-manifest

On a sidecar restart (e.g. a verbosity switch), already-prepared windows **replay instantly**
from the cached manifest with no re-inference and no pacer stalls, so the switch is seamless.

### Find-in-lecture search (`⌘F`)

Content-based navigation instead of time-scrubbing — search lecturer captions and AD text
and jump to the moment, reflecting the finding that BLV users navigate by content.

### WCAG 2.1 AA visual contrast

- A dedicated AA palette in `Theme.swift` (secondary text `#595959`, solid bars, high-contrast
  caption pills, `#FFFF00` AD-caption yellow).
- A build-time gate, `scripts/contrast_audit.py`, checks **every colour literal** against the
  required ratio (text 4.5:1, non-text 3.0:1) — currently **11/11 pass**.
- Non-speech **earcon** cue before each system-initiated pause, plus AD-track **bookending**
  and near-adjacent line **merging**, so listeners can tell where descriptions start and end.

### Reliability

- **Fixed a streaming crash (`8c6db1c`):** writing a pacing credit to a sidecar that had
  already exited raised `SIGPIPE` and killed the app (opening any lecture in streaming mode
  crashed instantly under mock; real runs hit it once the sidecar finished). Now `SIGPIPE`
  is ignored process-wide so those writes fail harmlessly, as the code already intended.

---

## Resources used

### Accessibility standards & AD research

- **WCAG 2.1 Level AA** — the target conformance level. Specific criteria applied:
  - **2.1.1 Keyboard** — all functionality operable from the keyboard.
  - **2.1.4 Character Key Shortcuts** — single-key shortcuts are toggleable.
  - **1.4.11 Non-text Contrast** — control/icon contrast ≥ 3:1.
  - **1.2.5 Audio Description (Prerecorded)** — the redundancy gate (describe only what
    speech leaves uncovered).
- **eCH-0059** — the Swiss accessibility standard used as the contrast audit's reference.
- **MAVP study** (BLV lecture-AD research) — informed several design choices: navigate by
  content (search), non-speech cues for system-initiated pauses (earcon), merge descriptions
  ≤ 3 s apart, and bookend the description track.
- **DCMP Description Key** and **Mayer (2009) redundancy principle** — secondary sources for
  the redundancy gate.
- Operative in-repo standard: **`rules_for_slides.yaml`** / **`lecture_ad_standards_for_slides.md`**
  (what to describe, per slide-element type).

### On-device models (fully offline, Apple Silicon)

- **Vision-language (AD generation):** a 4-bit MLX VL model via **mlx-vlm** — Qwen3-VL-2B on
  8 GB machines; Gemma 4 / Qwen3-VL family, config-swappable (`vl.model`).
- **Text-to-speech:** **Voxtral-4B-TTS** via **mlx-audio** (CC-BY-NC-4.0 — non-commercial).
- **Speech-to-text:** **Whisper-large-v3-turbo** via **mlx-whisper** (GPU), with
  **openai-whisper** as the CPU fallback.
- **Voice activity detection:** **Silero VAD** (finds the pauses AD is placed into).
- **OCR:** macOS-native **Apple Vision** (skipped when the VL model reads slides itself).

### Tooling

- **SwiftUI** app built **without Xcode** (Command Line Tools `swiftc` + macOS SDK) via
  `app/build_app.sh`.
- **Python core** (`ladpipe`) driven as a JSON-over-stdio sidecar; **ffmpeg** for media.
- **MLX** runtime stack (`mlx-vlm`, `mlx-audio`, `mlx-whisper`).
- Dev/CI gates: **pytest**, **ruff**, **mypy --strict**, and the custom
  **`scripts/contrast_audit.py`** WCAG gate.
- GUI walkthrough verification via macOS `screencapture` + `osascript` (System Events)
  automation.
