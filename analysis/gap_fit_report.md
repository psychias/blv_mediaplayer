# Gap-fit analysis — real lecture (anat-1, 49 min)

**Question this answers:** what AD-line length should the fine-tune target, and should AD that
doesn't fit a gap be *placed differently* or *dropped*? Decided on real data from the Phase-2 run,
not assumption.

## Method (cheap, no VL/Whisper)

- **Slide changes:** ffmpeg scene detection over the full video → **38 slides** (37 transitions + t=0).
- **Pauses:** ffmpeg `silencedetect` (−30 dB, ≥0.3 s) over the full audio → **1051 silences**.
- **Per-slide best gap:** the longest pause available within each slide's span (an *upper bound* on
  what could be placed — real usable gaps sit at sentence boundaries and are fewer/smaller).
- **AD duration:** Voxtral calibrated on-device → `dur(words) ≈ 1.38 + 0.57·words` (≈0.57 s/word
  plus ~1.38 s of fixed lead/tail padding; high variance at temperature 0.8).
- **Rung rules:** mirror the pipeline — rung 1 gap-insert (`dur ≤ gap`), rung 2 compress
  (`dur ≤ gap × 1.3`). Reproduce with `scripts/analyze_gap_fit.py`.

## Findings

**The gaps are tiny.** Per-slide best gap: **median 1.78 s, p75 2.33 s, p90 3.41 s, max 4.03 s.**
There is no pause longer than ~4 s anywhere in the lecture. (So rung-3 time-shift can't rescue
anything — there is no bigger gap within reach to shift to.)

**Spoken-placement rate vs AD length (current config):**

| AD words | dur (s) | spoken (rung 1–2) | marker/drop |
|---------:|--------:|------------------:|------------:|
| 3 | 3.1 | **24 %** | 76 % |
| 4 | 3.7 | 18 % | 82 % |
| 5 | 4.2 | 13 % | 87 % |
| 6 | 4.8 | 5 % | 95 % |
| 8 | 6.0 | **0 %** | 100 % |
| 12 | 8.3 | 0 % | 100 % |

The base model emits ~13–15-word descriptions (~9–10 s) → **0 % spoken; everything markers/drops.**
That matches what the live run produced (cytoplasm slide → drop; microtubules slide → rung-4 marker).

**No AD length reaches 50 % spoken placement** under the current config — even 3-word telegraphic
lines fit only ~24 % of slides, because Voxtral's 1.38 s padding alone consumes most of a median gap.

## Levers (quantified)

Trimming Voxtral's lead/tail silence (overhead 1.38 → ~0.48 s) **and** raising the compress cap to
1.5× roughly **doubles** placement:

| AD words | spoken (current) | spoken (trim + 1.5×) |
|---------:|-----------------:|---------------------:|
| 3 | 24 % | **61 %** |
| 4 | 18 % | 45 % |
| 6 | 5 % | 21 % |
| 8 | 0 % | 13 % |

Even then, genuinely useful AD (≥8 words) tops out at ~13 %.

## Decisions

1. **Fine-tune length target.** Train for **≤6 words (~3–4 s)** AD lines, and emit a hard *short* and
   *long* form per moment. ≤3 words is the only band that places in a majority of slides, but 3 words
   is rarely enough to describe a diagram — so brevity tuning **cannot** by itself make audio-AD the
   primary channel for this lecture style.

2. **Pause vs drop — decide for "drop-from-audio, keep-in-captions," not silent loss.** The data says
   ≥76 % (often 100 %) of useful AD *cannot* be woven into gaps without pausing the video. Since the
   pipeline already emits every `ad_text` as a **WebVTT AD cue** (timestamped to the moment), the
   dropped lines are **not lost** — they remain in the caption track for low-vision readers and for a
   screen-reader pass. Recommendation: make the **caption AD track the primary delivery** for this
   lecture style, with audio-AD as best-effort for the ~5–20 % of slides that have a real gap.
   - Cheap win to fund first: **trim leading/trailing silence from TTS clips** (≈+2× placement,
     pure post-process, no model change), then revisit the compress cap.
   - Only if audio-AD must cover more: add an optional **micro-pause rung** (briefly pause the video
     to open a slot). That breaks the "video never pauses" promise, so it is a **product** decision,
     not a tuning one — the evidence says it's the *only* way to raise audio-AD coverage materially.

## Caveat

Best-gap-per-slide is an optimistic upper bound (any pause in the span, not just sentence-boundary
pauses the rung ladder actually uses). True spoken-placement rates are **lower** than the table shows.
