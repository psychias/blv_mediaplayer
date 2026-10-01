"""Pure-logic tests for the MLX VL backend — prompts, JSON parsing, reload policy; no model."""

from __future__ import annotations

import pytest

from ladpipe.types import Moment
from ladpipe.vl.mlx_vlm import (
    DEFAULT_MOMENT_TYPE,
    SYSTEM_PROMPT,
    MlxVlmBackend,
    build_messages,
    is_degenerate,
    moment_type_from_answer,
    parse_decision,
)


def _moment() -> Moment:
    return Moment(
        id="m1",
        t_start=0.0,
        t_end=4.0,
        keyframe_path="/f.png",
        transcript_window="now consider the diagram",
        ocr_text="System Architecture",
        pause_after=2.0,
    )


def test_messages_are_system_then_user() -> None:
    msgs = build_messages(_moment())
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == SYSTEM_PROMPT
    assert '"rung"' in SYSTEM_PROMPT  # the trained JSON contract


def test_user_turn_matches_training_format() -> None:
    user = build_messages(_moment())[1]["content"]
    assert user.splitlines() == [
        f"Moment type: {DEFAULT_MOMENT_TYPE}",
        "Lecturer said (+/-8s): now consider the diagram",
        "On-screen text (OCR): System Architecture",
        "Pause available after the moment: 2s",
    ]  # multimodal arm: no "What is on screen" line (text-only/screen-hint arms only)


def test_classified_type_replaces_default() -> None:
    user = build_messages(_moment(), "chart")[1]["content"]
    assert user.startswith("Moment type: chart\n")


def test_classifier_answer_maps_onto_training_taxonomy() -> None:
    assert moment_type_from_answer("text") == "slide"  # bullets/prose -> the 'slide' type
    assert moment_type_from_answer(" Text.\n") == "slide"
    assert moment_type_from_answer("chart") == "chart"
    assert moment_type_from_answer("Graph") == "chart"
    assert moment_type_from_answer("table") == "table"
    assert moment_type_from_answer("equation") == "math"
    assert moment_type_from_answer("visual") == "figure"  # any other graphic -> figure
    assert moment_type_from_answer("picture") == "figure"
    assert moment_type_from_answer("") == "slide"  # nothing -> safe default


def test_pause_is_rounded_to_one_decimal() -> None:
    import dataclasses

    user = build_messages(dataclasses.replace(_moment(), pause_after=3.14159))[1]["content"]
    assert user.endswith("Pause available after the moment: 3.1s")


def test_parse_clean_emit() -> None:
    raw = '{"emit": true, "ad_text": "A flowchart", "teacher_rung": 2, "rationale": "x"}'
    d = parse_decision(raw)
    assert d.emit and d.ad_text == "A flowchart" and d.teacher_rung == 2


def test_parse_accepts_finetune_rung_key() -> None:
    raw = '{"emit": true, "ad_text": "A flowchart", "rung": 3, "rationale": "x"}'
    assert parse_decision(raw).teacher_rung == 3


def test_parse_suppress() -> None:
    raw = '{"emit": false, "ad_text": null, "teacher_rung": null, "rationale": "covered"}'
    d = parse_decision(raw)
    assert not d.emit and d.ad_text is None


def test_parse_json_wrapped_in_prose() -> None:
    raw = 'Sure:\n{"emit": true, "ad_text": "A bar chart", "rationale": "y"}\nThanks!'
    d = parse_decision(raw)
    assert d.emit and d.ad_text == "A bar chart"


def test_parse_emit_true_but_no_text_becomes_suppress() -> None:
    d = parse_decision('{"emit": true, "ad_text": "", "rationale": "z"}')
    assert not d.emit and d.ad_text is None


def test_parse_garbage_is_safe_suppress() -> None:
    d = parse_decision("the model rambled and produced no json")
    assert not d.emit and d.ad_text is None and "unparseable" in d.rationale


def test_degenerate_output_detected() -> None:
    # NaN logits decode to token 0 ("!"), the signature of an exhausted MLX state.
    assert is_degenerate("!!!!!!!!!!!!")
    assert is_degenerate("  !!!! ")
    assert not is_degenerate('{"emit": false, "ad_text": null}')
    assert not is_degenerate("chart")
    assert not is_degenerate("")


def _stub_backend(
    monkeypatch: pytest.MonkeyPatch, replies: list[tuple[str, str]]
) -> tuple[MlxVlmBackend, list[str]]:
    """A backend whose worker is faked out, so the policy is testable with no model."""
    backend = MlxVlmBackend("weights")
    starts: list[str] = []

    def _start() -> object:
        starts.append("start")
        return object()  # stands in for the Popen handle; never read by the policy

    def _stop() -> None:
        backend._proc = None

    def _ask(moment: Moment) -> tuple[str, str]:
        backend._ensure_worker()
        backend._generations += 2  # one classify + one describe, as the worker does
        return replies.pop(0)

    monkeypatch.setattr(backend, "_start", _start)
    monkeypatch.setattr(backend, "_stop", _stop)
    monkeypatch.setattr(backend, "_ask", _ask)
    return backend, starts


_GOOD = ("chart", '{"emit": true, "ad_text": "A chart.", "rung": 2, "rationale": "x"}')


def test_worker_restarts_once_the_generation_budget_is_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, starts = _stub_backend(monkeypatch, [_GOOD] * 17)
    for _ in range(16):  # 16 moments = 32 generations = exactly the budget
        backend.describe(_moment(), "")
    assert len(starts) == 1
    backend.describe(_moment(), "")  # the 17th crosses it
    assert len(starts) == 2


def test_worker_restarts_and_retries_after_degenerate_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, starts = _stub_backend(monkeypatch, [("!!!!", "!!!!!!!!"), _GOOD])
    decision = backend.describe(_moment(), "")
    assert len(starts) == 2  # the original worker, then the replacement
    assert decision.emit and decision.ad_text == "A chart."

