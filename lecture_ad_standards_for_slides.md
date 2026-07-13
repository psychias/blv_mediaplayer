# Audio Description Standards for Slide-Based Lecture Recordings

*Generated from `rules_for_slides.yaml`. This document is produced directly from the rule set so the two never diverge; edit the YAML, not this file.*

## Preamble

**Purpose.** Operative standards governing automated audio description (AD) generation for screencast-style lecture recordings serving blind and low-vision (BLV) learners. The system speaks the pedagogically meaningful visual content that the lecturer's own words leave uncovered, and stays silent when the lecturer's words already cover what is on screen.

**Scope.** Screencast-style lecture recordings where the lecturer shares their screen and slides are the entire visual surface. A lecturer face thumbnail may appear in a corner and is treated as decoration. The cursor, on-screen highlights, callout boxes, and ink annotations layered on slides are the only pointing modality in scope. Delivery is live: AD is inserted into existing pauses in the lecturer's speech, with a fallback ladder for content that cannot fit a pause.

**Document structure.** The standard is organised in two parts. **Part I — General principles** establishes the framing applying to every AD decision: the redundancy gate, voice and tense, length and insertion mechanics, uncertainty handling. **Part II — Slide-specific rules** specifies how each visual element type on slides is to be handled (text, figures, tables, charts, math, code, deixis, edge cases).

**Companion document.** A comprehensive set of general principles spanning categories not applied operationally here (personalization, cognitive load, broader prioritization and uncertainty) is maintained separately in `rules_general.yaml` and `lecture_ad_standards_general.md`. The general companion is the broader reference; this document is the operative standard.

**Legend.** `[DOC]` = grounded in a documented standard (citation given). `[PROV·<basis>]` = provisional, pending BLV-user validation; `<basis>` records derivation: *transfer-from*, *corollary-of*, *operationalization-of*, or *design-hypothesis*.

---

## Part I — General principles

General principles applying to every AD decision regardless of the element type involved. These mirror a subset of the comprehensive principles in `rules_general.yaml`; included here so the slide-specific standard can be applied in isolation.

### Cross-cutting

- `[DOC]` REDUNDANCY GATE (governs every 'describe' rule in §2): describe on-screen content only to the extent the lecturer's speech does not already convey it. The element rules in §2 specify HOW to describe a figure/table/chart/equation/etc.; this rule decides WHETHER to, and how much — always only the gap the voice leaves. When the lecturer's words already carry the content, suppress entirely. This is a system for covering what speech omits, not for reading the screen aloud.  
  *Source:* WCAG 2.2 Understanding 1.2.5 · https://www.w3.org/WAI/WCAG22/Understanding/audio-description-prerecorded.html  
  *Also:* Mayer 2009 redundancy principle (SECONDARY) · https://sites.google.com/site/cognitivetheorymmlearning/redundancy-principle  
  *Also:* DCMP Description Key §7 · https://dcmp.org/learn/618-description-key---what-to-describe

- `[DOC]` Use present tense, active voice, third-person narration.  
  *Source:* DCMP Description Key §8 · https://dcmp.org/learn/617-description-key---how-to-describe  
  *Also:* VideoA11y G3 · https://arxiv.org/html/2502.20480  
  *Also:* Netflix v2.5 · https://partnerhelp.netflixstudios.com/hc/en-us/articles/215510667-Audio-Description-Style-Guide-v2-5

- `[DOC]` Describe observable visual content; do not infer emotions, intent, or significance.  
  *Source:* DCMP Description Key §7 · https://dcmp.org/learn/618-description-key---what-to-describe  
  *Also:* DCMP §8 · https://dcmp.org/learn/617-description-key---how-to-describe  
  *Also:* VideoA11y G41 · https://arxiv.org/html/2502.20480

- `[DOC]` Use consistent terminology within a lecture and across a course; adopt the lecturer's wording when terms are introduced.  
  *Source:* DCMP Description Key §7 · https://dcmp.org/learn/618-description-key---what-to-describe  
  *Also:* VideoA11y G22 · https://arxiv.org/html/2502.20480

- `[DOC]` When the AD system's confidence in what is on screen is low, prefer silence over a confident wrong description. A BLV student cannot verify a description; a wrong one is worse than silence.  
  *Source:* Describe Now · https://arxiv.org/html/2411.11835v2 (S15.7)

- `[DOC]` Do not re-describe visual content already described earlier in the same lecture. After first describing an element (a diagram, a definition, a figure), subsequent appearances within the same lecture get either a name-only reference or silence, not a full re-description.  
  *Source:* WCAG 2.2 Understanding 1.2.5 · https://www.w3.org/WAI/WCAG22/Understanding/audio-description-prerecorded.html (S5.5)  
  *Also:* Mayer 2009 redundancy principle (SECONDARY) · https://sites.google.com/site/cognitivetheorymmlearning/redundancy-principle (S12.1)  
  *Also:* Sweller/Chandler split-attention effect (SECONDARY) · https://sites.google.com/site/cognitivetheorymmlearning/redundancy-principle (S12.5) — motivating rationale for consistent naming / no re-description, not proof for BLV lecture listeners (was cognitive_006)  
  *Also:* Holsanova, Blomberg, Blomberg, Gardenfors & Johansson (2023), JAT 6(1):64-92 · https://doi.org/10.47476/jat.v6i1.2023.245 — AD at event boundaries is sensitive to spatiotemporal (time/location) circumstances; event-segmentation is an active AD-research area (film-AD; only an indirect analogy to lecture-scale re-description)

- `[PROV·design-hypothesis]` Lookahead redundancy (extends the redundancy gate cross_cutting_001 across time): suppress a description if the lecturer covers the same content shortly AFTER the visual event, not only simultaneously. OFFLINE dataset generation: look ahead over the transcript and suppress the description if the lecturer verbalizes the content within a window LOCKED to: before the next pedagogical event, or 8 seconds, whichever comes first. LIVE deployment: hold a non-urgent description for a brief grace window; if the lecturer begins covering it within the window, suppress, otherwise describe. Prevents the AD from pre-empting an explanation the lecturer is about to give (the covered-later case for reveals, equations, tables, figures).  

- `[DOC]` Describing the lecturer's gestures and board drawings — and resolving the deixis attached to them — is a core (not peripheral) lecture-AD task. The WCAG 1.2.7 physics-lecture example is the canonical case: a professor sketches rapidly on a whiteboard while gesturing and pauses are insufficient — the case proving gap-insertion alone fails. In a live system this is handled by the fallback ladder (length_005), not by pausing (WCAG 1.2.7 extended AD is prerecorded-only). The per-element machinery lives in §2.Deixis (rules deixis_001..007); this rule frames it as a first-class concern of lecture AD.  
  *Source:* WCAG 2.2 Understanding 1.2.7 — extended AD physics-lecture example · https://www.w3.org/WAI/WCAG22/Understanding/extended-audio-description-prerecorded.html (S5.6)

### Length and insertion (live mode)

- `[DOC]` Gap-insertion is the base delivery mechanism: insert AD into existing pauses in the lecturer's speech.  
  *Source:* WCAG 2.2 SC 1.2.5 · https://www.w3.org/TR/WCAG22/

- `[PROV·design-hypothesis]` Live mode prioritization: deixis-resolution > slide-text gist > figure summary > full figure.  
  *Open question:* OQ-Length-2 — RESOLVED: live priority LOCKED (deixis-resolution > slide-text gist > figure summary > full figure), implementing the deixis-first scheme of length_012. Basis: deixis primacy + drill-down (deixis_008 DOC; NCAM S4.G.4).

- `[PROV·design-hypothesis]` Live fallback ladder (the live replacement for extended AD, which is unavailable because the live stream cannot be paused for the room). The BLV listener's audio is a per-user track, so it may run behind the live feed without affecting anyone else. When a describable visual cannot be conveyed in the available speech gap, descend until one rung succeeds: (1) full description if it fits the gap; (2) compressed description if a shorter gap fits; (3) time-shift — let the listener's track fall behind the live feed to deliver the full description, then catch up during the next pause (or by briefly faster playback), up to a maximum lag cap L (team-chosen, default ~20s); (4) honest placeholder naming what is on screen without faking coverage (e.g. 'equation on screen, long derivation in progress') when time-shift cannot keep up — lag would exceed L, or no upcoming pause exists to catch up in; (5) drop, only as a last resort. Collision-losers (two events competing for one gap) are handled separately by the queue rule (length_014). This ladder is the live replacement for every former per-element 'default to extended AD' instruction (figures, typeset math, ink writing, handwritten derivations). Tables (table_005) and code keep their own element-specific compression and reference this ladder only for overflow.  

- `[DOC]` Concise insertion default = 25 words; detailed override = 100 words.  
  *Source:* Describe Now · https://arxiv.org/html/2411.11835v2  
  *Also:* Pavel, Reyes & Bigham (2020), Rescribe, UIST · arXiv:2010.03667 — auto-edits description length to fit gaps; residual: educational-content comprehension preservation untested

- `[PROV·transfer-from]` Avoid continuous description; leave silence on most lecturer-narrated stretches.  

## Part II — Slide-specific rules

Rules applying to specific visual elements as they appear on slides.

### Slide text

- `[DOC]` Read on-screen text central to comprehension that is not already conveyed by the lecturer's speech. This covers the slide title and any individual body item: surface only the specific uncovered item, gated by cross_cutting_001 — never read the slide top-to-bottom.  
  *Source:* W3C MAUR §1.8 · https://www.w3.org/TR/media-accessibility-reqs/  
  *Also:* VideoA11y G30 · https://arxiv.org/html/2502.20480  
  *Also:* Netflix v2.5 · https://partnerhelp.netflixstudios.com/hc/en-us/articles/215510667-Audio-Description-Style-Guide-v2-5

- `[DOC]` Do not read aloud slide text the lecturer is reading aloud (redundancy).  
  *Source:* WCAG 2.2 Understanding 1.2.5 · https://www.w3.org/WAI/WCAG22/Understanding/audio-description-prerecorded.html

### Slide transitions

- `[PROV·transfer-from]` Do not describe transition animations (dissolves, wipes, slide-in).  

### Slide animations and reveals

- `[PROV·transfer-from]` Do not describe animation effects (fly-in, fade-up).  
  *Source:* BY ANALOGY (not direct): NCAM Bar Charts S4.B.3 · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-bar-charts — 'It is not necessary to describe the visual attributes of the bars … unless there is an explicit need'. NCAM addresses bar colour only and does not mention animation effects.

- `[PROV·corollary-of]` Apply the redundancy gate to each revealed increment independently: when a build adds a bullet, equation step, or chart series, describe only the delta the new step adds, and only if speech leaves it uncovered — never re-read the accumulated slide state. Stepwise typeset-equation builds follow the delta convention of inked_math_003; chart build animations are described as the completed data state, not frame by frame.  
  *Source:* COROLLARY (not direct): WCAG 2.2 Understanding 1.2.5 redundancy · https://www.w3.org/WAI/WCAG22/Understanding/audio-description-prerecorded.html — the redundancy principle applied per increment; WCAG does not address slide builds.

### Figures

- `[DOC]` Drill down: brief summary first; then main components; then details only if a gap remains. Describe only the part the lecturer's speech does not already convey (redundancy gate, cross_cutting_001).  
  *Source:* NCAM STEM overview · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-guidelines-for-describing-stem-images

- `[DOC]` Foreground data-carrying elements; suppress decorative styling.  
  *Source:* NCAM STEM overview · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-guidelines-for-describing-stem-images

- `[DOC]` Do not describe decorative elements (ornamental backgrounds, branded logos, semantically inert color).  
  *Source:* NCAM STEM overview · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-guidelines-for-describing-stem-images

- `[DOC]` Open with single-sentence type-and-purpose ('A block diagram of …'), then a brief list of components in reading order.  
  *Source:* NCAM STEM overview · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-guidelines-for-describing-stem-images

### Tables

- `[DOC]` Provide brief summary before reading the table (what it shows, what the dimensions are). Describe only the part the lecturer's speech does not already convey (redundancy gate, cross_cutting_001).  
  *Source:* NCAM STEM overview · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-guidelines-for-describing-stem-images

- `[DOC]` Split multi-layered tables into smaller sub-tables organized by category.  
  *Source:* NCAM Tables · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-tables

- `[DOC]` Do not describe cell-level styling unless it encodes semantic meaning.  
  *Source:* NCAM Bar Charts · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-bar-charts

### Charts

- `[DOC]` Open with chart type and what it measures, then a one-sentence trend, then data structure. Describe only the part the lecturer's speech does not already convey (redundancy gate, cross_cutting_001).  
  *Source:* NCAM Bar Charts · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-bar-charts  
  *Also:* NCAM STEM overview · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-guidelines-for-describing-stem-images

- `[DOC]` Where data is sparse (4 or fewer values), present as a short text list rather than a full table.  
  *Source:* NCAM Bar Charts · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-bar-charts

- `[DOC]` Do not describe bar/line color unless colours encode categories the listener must distinguish.  
  *Source:* NCAM Bar Charts · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-bar-charts

### Typeset math

- `[DOC]` Surface the equation aurally; mark it semantically so a renderer can verbalize per user preference. Describe only the part the lecturer's speech does not already convey (redundancy gate, cross_cutting_001).  
  *Source:* NCAM STEM overview · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-guidelines-for-describing-stem-images

- `[PROV·design-hypothesis]` Pair every non-trivial equation with a one-line natural-language gloss in the same insertion.  

- `[PROV·transfer-from]` Use ClearSpeak as the default verbalization grammar, applied consistently within a course; defer to learner preference where the learner has one. (ClearSpeak chosen over MathSpeak because it reads closer to natural spoken mathematics; no universal standard exists.)  
  *Source:* No universal spoken-math standard exists (NFB, Guidelines for Collegiate Faculty to Teach Mathematics to Blind or Visually Impaired Students). Frankel, Brownstein, Soiffer & Hansen (2016), ETS Research Report RR-16-23 — supporting (grade C): documents ClearSpeak as a defined rule set, not a universal standard.

### Code and pseudo-code

- `[PROV·operationalization-of]` Announce language and purpose ('Python snippet, five lines, defines a binary-search function'). Describe only the part the lecturer's speech does not already convey (redundancy gate, cross_cutting_001).  

- `[PROV·corollary-of]` Surface error or output highlights when the lecturer references them deictically.  

- `[DOC]` Do not re-read code the lecturer has read aloud line-by-line (redundancy).  
  *Source:* WCAG 2.2 Understanding 1.2.5 · https://www.w3.org/WAI/WCAG22/Understanding/audio-description-prerecorded.html

### Deixis — cursor, pointer, highlight, callout

- `[PROV·corollary-of]` Surface the referent ('the kinetic-energy term, ½mv²'), not the act of pointing.  

- `[DOC]` When referent cannot be resolved with confidence, prefer silence to a wrong guess.  
  *Source:* Describe Now · https://arxiv.org/html/2411.11835v2 (S15.7) — Cheema, Seifi & Fazli (2025), DIS · https://doi.org/10.1145/3715336.3735685; also backed by the objectivity principle (cross_cutting_003).

- `[PROV·corollary-of]` Do not describe idle cursor motion uncoupled from speech.  

- `[PROV·corollary-of]` Do not describe the pointing act as the description ('the cursor is pointing at it').  
  *Source:* BY ANALOGY (not direct): NCAM STEM overview S4.G.2 · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-guidelines-for-describing-stem-images — 'Description should focus on the data and not extraneous visual elements'; also leans on the provisional surface-the-referent rule deixis_001. No fetched source directly addresses describing a pointing gesture vs its referent in lecture AD.  

- `[PROV·design-hypothesis]` Resolve bare deictics ('this', 'here', 'this term') from the cursor's dwell anchor at utterance time: sustained dwell or deliberate circling over a slide region counts as a point; transit motion between regions is non-deictic (deixis_003). In this scope the cursor — with highlights and ink — is the only pointing modality, so an unanchored bare deictic resolves to silence (deixis_002).  

- `[PROV·corollary-of]` Treat highlight boxes, callout shapes, and colour emphasis drawn over a slide as deictic acts: surface the highlighted referent ('the boundary condition, u(0)=0'), not the overlay's appearance — describe colour, shape, or stroke only when it encodes meaning the lecturer relies on.  
  *Source:* BY ANALOGY (not direct): NCAM STEM overview S4.G.2 · https://www.wgbh.org/foundation/services/ncam/tools-resources/effective-practices-for-description-of-science-content-guidelines-for-describing-stem-images — 'Description should focus on the data and not extraneous visual elements'. NCAM addresses static STEM images and does not mention highlight or callout overlays.

### Edge cases (slide-specific)

- `[PROV·transfer-from]` Do not describe the lecturer's face thumbnail — its presence, position, facial expressions, clothing, background, or appearance/disappearance; in this scope it is decoration and the speaker is already carried by the voice. If the lecturer explicitly directs attention to the webcam view (e.g. holds an object to the camera), treat it as an off-slide surface and route per edge_cases_004.  
  *Source:* BY ANALOGY (not direct): WCAG Technique G203 · https://www.w3.org/WAI/WCAG21/Techniques/general/G203.html — a single speaker against an unchanging background carries no important time-based visual information warranting description. G203 addresses whole talking-head videos, not a picture-in-picture thumbnail over slides.  

- `[PROV·design-hypothesis]` When the lecturer zooms into, scrolls within, or otherwise reframes the shared slide, describe the content the new framing presents ('the lower-right quadrant of the diagram fills the screen: ...'), not the navigation mechanics; treat a sustained close-up on a region as deictic emphasis and resolve it per §2.Deixis. Name the region now shown rather than the camera-like move (cross_cutting_007).  
