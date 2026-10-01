"""MlxVlmBackend — the AD4Edu fine-tuned Qwen3-VL on-device via mlx-vlm (MLX runtime).

The shipped weights are Qwen3-VL-2B-Instruct with the AD4Edu LoRA merged in
(``scripts/merge_adapter.py``). That adapter was trained in the **multimodal** arm, so
the model is prompted exactly as it was trained: the AD4Edu system prompt, then a user
turn carrying the keyframe image plus four labelled lines (moment type, lecturer
speech, slide OCR, pause available). Training fed up to three keyframes at native
resolution; inference sends the moment's single keyframe downscaled to
``vl.image_max_side``, with OCR still carrying the small print. The prompt text mirrors
``ad4edu/training/build_sft.py`` (``_user_text``, ``text_only=False``); keep them in sync.

Prompt building and JSON parsing are pure and unit-tested with no model. The model
itself runs in a child process (``mlx_worker``), which the backend restarts on a
generation budget: the pinned MLX stack goes numerically bad after roughly 70
generations and only a fresh process recovers. mlx is therefore never imported into
the pipeline's own process by this module.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import subprocess
import sys

from ..types import ADDecision, Moment

# Training used max_new_tokens=160 with a 256-token retry; one 256 pass avoids the retry.
_MAX_TOKENS = 256

# Restart the worker well before the ~70-generation cliff described in mlx_worker.
# 32 generations is 16 moments, about 4 s of reload on a lecture that needs two of them.
_GENERATIONS_PER_WORKER = 32

# Verbatim from ad4edu/training/build_sft.py::SYSTEM_PROMPT (shared by every arm).
SYSTEM_PROMPT = (
    "You are an audio describer for slide-based lecture videos, writing for blind and "
    "low-vision learners. For each lecture moment you receive the on-screen visuals "
    "(keyframe images and slide OCR text), the lecturer's speech around the moment, the "
    "moment type, and the length of the pause available.\n\n"
    "Follow the operative standard:\n"
    "- Redundancy gate: describe on-screen content ONLY to the extent the lecturer's speech "
    "does not already convey it. If the speech already carries the content, suppress "
    "(do not describe).\n"
    "- Fit the pause: keep the description within what the available pause allows.\n"
    "- Be faithful: describe only what is actually visible; never invent content.\n"
    "- Style: present tense, active voice, third person; concise; no meta-language "
    '("the slide shows", "an image of").\n\n'
    'Output ONLY a JSON object: {"emit": <true|false>, "ad_text": <string or null>, '
    '"rung": <1-5 or null>, "rationale": <string>}. Use emit=false with ad_text=null when the '
    "moment should not be described; give the reason for suppressing in rationale."
)

# "Moment type" is a member of the training taxonomy (pointing/slide/reveal/figure/math/
# ink/animation/transition/table/chart/other) and it steers the emit gate hard: labelled
# "slide" the fine-tune suppresses nearly every moment (speech usually covers a text
# slide), labelled "chart"/"figure" it describes the graphic. The corpus had human
# annotators for this; the pipeline asks the same model to classify the keyframe first
# (one short extra generation, ~0.7 s) and falls back to "slide".
DEFAULT_MOMENT_TYPE = "slide"
# Wording chosen on real 640 px keyframes: a "pick one of chart/figure/table/math/text"
# prompt labelled plain bullet slides "chart"; asking text-vs-graphic first was reliable.
# The fine-tune often answers with the graphic's kind ("chart", "picture") instead of
# "visual", so the mapping accepts those too.
CLASSIFY_PROMPT = (
    "Look at this lecture slide. Apart from its title, does it contain a graph, chart, "
    "diagram, table, equation or picture? Answer with exactly one word: visual or text."
)
_TYPE_BY_ANSWER = {
    "text": "slide", "no": "slide",
    "chart": "chart", "graph": "chart", "plot": "chart",
    "table": "table",
    "math": "math", "equation": "math", "formula": "math",
}
_VISUAL_FALLBACK = "figure"  # visual / picture / diagram / image / yes / ...
_CLASSIFY_MAX_TOKENS = 4


def moment_type_from_answer(raw: str) -> str:
    """Map the classifier's one-word answer onto the training taxonomy.

    Text-only slides -> "slide"; a named graphic kind -> its type; any other non-empty
    answer is treated as a graphic ("figure"); an empty answer falls back to "slide"."""
    words = raw.strip().lower().split()
    first = words[0].strip(".,;:!'\"`") if words else ""
    if not first:
        return DEFAULT_MOMENT_TYPE
    return _TYPE_BY_ANSWER.get(first, _VISUAL_FALLBACK)


def build_messages(
    moment: Moment, moment_type: str = DEFAULT_MOMENT_TYPE
) -> list[dict[str, str]]:
    """System + user turns in the exact multimodal training format (build_sft._user_text).

    The keyframe itself is not in the text: mlx-vlm's ``apply_chat_template`` inserts the
    image token(s) into the last user turn according to ``num_images``."""
    user = "\n".join(
        [
            f"Moment type: {moment_type}",
            f"Lecturer said (+/-8s): {moment.transcript_window.strip()}",
            f"On-screen text (OCR): {moment.ocr_text.strip()}",
            f"Pause available after the moment: {round(moment.pause_after, 1):g}s",
        ]
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


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
    rung_value = obj.get("rung", obj.get("teacher_rung"))  # "rung" is the trained key
    teacher_rung = int(rung_value) if isinstance(rung_value, (int, float)) else None
    return ADDecision(
        emit=emit and ad_text is not None,
        ad_text=ad_text,
        teacher_rung=teacher_rung,
        rationale=str(obj.get("rationale", "")),
    )


def _text_of(result: object) -> str:
    return result if isinstance(result, str) else str(getattr(result, "text", result))


def is_degenerate(text: str) -> bool:
    """True for the NaN-logit signature: argmax over NaN picks token 0, which is "!"."""
    return text.lstrip().startswith("!!")


# --------------------------------------------------------------------------- #
# Model side — imported only by mlx_worker, inside the child process           #
# --------------------------------------------------------------------------- #
def load_model(weights: str) -> tuple[object, object, object]:
    """(model, processor, config) for the MLX weights at ``weights``."""
    try:
        from mlx_vlm import load
        from mlx_vlm.utils import load_config
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "mlx-vlm is required for the VL backend. Install the 'real' extra (README/§6)."
        ) from exc
    model, processor = load(weights)
    return model, processor, load_config(weights)


def generate_for_moment(
    loaded: tuple[object, object, object], moment: Moment, image_max_side: int
) -> tuple[str, str]:
    """Classify the keyframe, then describe the moment: (classifier answer, raw reply)."""
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template

    model, processor, config = loaded
    images = [_image(moment.keyframe_path, image_max_side)] if moment.keyframe_path else []
    answer = ""
    if moment.kind == "pointing":
        # The keyframe carries a visible pointer at the dwell; "pointing" is the corpus type
        # and nothing needs classifying.
        answer = moment_type = "pointing"
    else:
        if images:
            formatted = apply_chat_template(processor, config, CLASSIFY_PROMPT, num_images=1)
            answer = _text_of(generate(
                model, processor, formatted, images,
                max_tokens=_CLASSIFY_MAX_TOKENS, temperature=0.0, verbose=False,
            ))
        moment_type = moment_type_from_answer(answer)
    formatted = apply_chat_template(
        processor, config, build_messages(moment, moment_type), num_images=len(images)
    )
    raw = _text_of(generate(
        model, processor, formatted, images,
        max_tokens=_MAX_TOKENS, temperature=0.0, verbose=False,
    ))
    return answer, raw


def _image(keyframe_path: str, max_side: int) -> object:
    from PIL import Image

    img = Image.open(keyframe_path).convert("RGB")
    img.thumbnail((max_side, max_side))
    return img


class _WorkerError(RuntimeError):
    """The VL worker died, or answered with something that is not a reply."""


class MlxVlmBackend:
    """Drives the VL model in a child process, restarted on a budget (see mlx_worker)."""

    def __init__(self, model: str, image_max_side: int = 768) -> None:
        self._model_ref = model
        self._image_max_side = image_max_side
        self._proc: subprocess.Popen[str] | None = None
        self._generations = 0

    def describe(self, moment: Moment, rules: str) -> ADDecision:
        # ``rules`` is part of the VLBackend protocol; the fine-tune internalised the
        # operative standard during training, so the prompt does not carry it.
        if self._generations >= _GENERATIONS_PER_WORKER:
            self._restart()
        answer, raw = self._attempt(moment)
        if is_degenerate(answer) or is_degenerate(raw):
            # The worker went numerically bad early; only a new process recovers.
            self._restart()
            answer, raw = self._attempt(moment)
        return parse_decision(raw)

    # -- worker plumbing ---------------------------------------------------- #
    def _start(self) -> subprocess.Popen[str]:
        return subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "ladpipe.vl.mlx_worker",
             self._model_ref, str(self._image_max_side)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )

    def _ensure_worker(self) -> subprocess.Popen[str]:
        if self._proc is None:
            self._proc = self._start()
            self._generations = 0
        return self._proc

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()  # the worker leaves its read loop on EOF
            proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()

    def _restart(self) -> None:
        self._stop()
        self._ensure_worker()

    def _attempt(self, moment: Moment) -> tuple[str, str]:
        """Ask the worker, giving it one restart if it has died."""
        try:
            return self._ask(moment)
        except _WorkerError:
            self._restart()
            return self._ask(moment)

    def _ask(self, moment: Moment) -> tuple[str, str]:
        proc = self._ensure_worker()
        try:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(json.dumps(dataclasses.asdict(moment)) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        except OSError as exc:
            raise _WorkerError("VL worker pipe failed") from exc
        if not line.strip():
            raise _WorkerError(f"VL worker exited (code {proc.poll()})")
        try:
            reply = json.loads(line)
            answer, raw = str(reply["answer"]), str(reply["raw"])
        except (ValueError, KeyError, TypeError) as exc:
            raise _WorkerError("VL worker sent a malformed reply") from exc
        self._generations += 2  # one classify + one describe
        return answer, raw

    def __del__(self) -> None:  # pragma: no cover - interpreter shutdown ordering
        with contextlib.suppress(Exception):
            self._stop()
