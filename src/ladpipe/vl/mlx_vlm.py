"""MlxVlmBackend — VL model on-device via mlx-vlm (Apple Silicon, MLX runtime).

One backend loads EITHER trained model (Gemma or Qwen3-VL) from a config path —
mlx-vlm auto-detects the architecture, so there is no per-model class. Using 4-bit
MLX weights keeps the language AND vision encoder GPU-resident (the fix for the
llama.cpp CPU-fallback that caused ~40 s/call). Default: mlx-community/gemma-4-e2b-it-4bit.

Prompt building and JSON parsing are pure and unit-tested with no model. The model
call is isolated in ``describe`` and lazy-imports mlx_vlm. The model is loaded once
and kept warm for the whole lecture.

VERSION PIN: early MLX 4-bit Gemma-4 quants emitted garbage (they quantized the
Per-Layer-Embedding layers; fixed in mlx-vlm PR #893). Pin mlx-vlm at/after that fix
and smoke-test 4-bit output on one slide. Gibberish ⇒ this bug (bump the version),
not the pipeline; the -bf16 build is the safe higher-memory fallback.
"""

from __future__ import annotations

import json

from ..types import ADDecision, Moment

_MAX_TOKENS = 300

_INSTRUCTION = """\
You are an audio-description assistant for blind and low-vision university students watching a
recorded slide lecture. You see ONE slide keyframe and the lecturer's nearby words. Speak only the
PEDAGOGICALLY IMPORTANT visual content the lecturer's speech does NOT already convey — the content a
student needs to follow the concept — and stay silent otherwise.

DESCRIBE (only the part speech leaves uncovered):
- A figure or diagram: open with its type and purpose ("A block diagram of the cell ...") then its
  key labeled parts or relationships in reading order.
- A chart/graph: the trend or comparison that matters (not its colours).
- An equation, formula, or labeled relationship the student must see.
- On-slide text that carries meaning the speech skips — its gist, not read word for word.
- The actual referent of the lecturer's pointing ("this", "here") — name the thing pointed to.

DO NOT:
- Read the whole slide aloud or repeat what the lecturer is already saying.
- Describe decorative content: logos, backgrounds, or colours that carry no meaning.
- Describe slide transitions/animations (fades, fly-ins) or the act of pointing / cursor motion.
- Describe the lecturer's webcam thumbnail.
- Guess at significance, emotion, or intent — describe only what is observably on the slide.

STYLE: {style}
If speech already covers the slide, or nothing pedagogically important is uncovered, set emit=false.

Return ONLY a JSON object, no prose, with exactly these keys:
  "emit": true|false
  "ad_text": string|null   (the description to speak; null when emit is false)
  "teacher_rung": 0|1|2|3|4|5|null   (your suggested placement; deployment re-checks feasibility)
  "rationale": string   (one short sentence)

OPERATIVE RULES (the standard you must follow):
{rules}

LECTURER SPEECH (around this moment):
{transcript}

SLIDE OCR TEXT (may be empty — read the slide directly):
{ocr}
"""

# User-selectable level of detail (MAVP-style minimal | balanced | expansive). Only the
# style line changes; the emit criteria stay identical across levels.
_STYLE = {
    "minimal": (
        "present tense, third person, ONE very short spoken sentence (at most 12 words), "
        "plain and concrete — only the single most important visual fact."
    ),
    "balanced": "present tense, third person, ONE short spoken sentence, plain and concrete.",
    "expansive": (
        "present tense, third person, one to two short spoken sentences (at most 35 words), "
        "plain and concrete — include the key labels or values the student needs."
    ),
}


def condense_rules(rules: str) -> str:
    """Extract just the operative rule statements from the rules YAML.

    The full rules file carries ids, sections, citations and metadata the model
    doesn't need; embedding it verbatim wastes thousands of tokens per moment.
    Pull out the ``rule:`` statements only. Falls back to the raw text if it isn't
    the expected YAML shape — no silent loss of content.
    """
    import yaml

    try:
        data = yaml.safe_load(rules)
    except yaml.YAMLError:
        return rules.strip()
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        return rules.strip()
    statements = [
        f"- {item['rule']}"
        for item in data["rules"]
        if isinstance(item, dict) and isinstance(item.get("rule"), str)
    ]
    return "\n".join(statements) if statements else rules.strip()


def build_prompt(moment: Moment, rules: str, verbosity: str = "balanced") -> str:
    return _INSTRUCTION.format(
        style=_STYLE.get(verbosity, _STYLE["balanced"]),
        rules=condense_rules(rules) or "(no rules provided)",
        transcript=moment.transcript_window.strip() or "(silence)",
        ocr=moment.ocr_text.strip() or "(none — read the slide directly)",
    )


def _extract_json(raw: str) -> dict[str, object] | None:
    raw = raw.strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} block (models often wrap JSON in prose).
    depth = 0
    start = -1
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(raw[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    start = -1
    return None


def parse_decision(raw: str) -> ADDecision:
    obj = _extract_json(raw)
    if obj is None:
        return ADDecision(emit=False, ad_text=None, teacher_rung=None,
                          rationale="unparseable model output")
    emit = bool(obj.get("emit", False))
    ad_value = obj.get("ad_text")
    ad_text = str(ad_value) if (emit and ad_value) else None
    rung_value = obj.get("teacher_rung")
    teacher_rung = int(rung_value) if isinstance(rung_value, (int, float)) else None
    return ADDecision(
        emit=emit and ad_text is not None,
        ad_text=ad_text,
        teacher_rung=teacher_rung,
        rationale=str(obj.get("rationale", "")),
    )


class MlxVlmBackend:
    def __init__(self, model: str, image_max_side: int = 768, verbosity: str = "balanced") -> None:
        self._model_ref = model
        self._image_max_side = image_max_side
        self._verbosity = verbosity
        self._loaded: object | None = None  # (model, processor, config)

    def _ensure_loaded(self) -> tuple[object, object, object]:
        if self._loaded is None:
            try:
                from mlx_vlm import load
                from mlx_vlm.utils import load_config
            except ImportError as exc:  # pragma: no cover - environment-dependent
                raise RuntimeError(
                    "mlx-vlm is required for the VL backend. Install the 'real' extra and pin "
                    "mlx-vlm past the Gemma-4 PLE-quant fix (PR #893, README/§6)."
                ) from exc
            model, processor = load(self._model_ref)
            config = load_config(self._model_ref)
            self._loaded = (model, processor, config)
        assert self._loaded is not None
        return self._loaded  # type: ignore[return-value]

    def describe(self, moment: Moment, rules: str) -> ADDecision:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        model, processor, config = self._ensure_loaded()
        prompt = build_prompt(moment, rules, self._verbosity)
        images = [self._image(moment.keyframe_path)] if moment.keyframe_path else []
        formatted = apply_chat_template(processor, config, prompt, num_images=len(images))
        result = generate(
            model, processor, formatted, images,
            max_tokens=_MAX_TOKENS, temperature=0.0, verbose=False,
        )
        text = result if isinstance(result, str) else getattr(result, "text", str(result))
        return parse_decision(text)

    def _image(self, keyframe_path: str) -> object:
        from PIL import Image

        img = Image.open(keyframe_path).convert("RGB")
        img.thumbnail((self._image_max_side, self._image_max_side))
        return img
