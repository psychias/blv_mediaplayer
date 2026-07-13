"""Pure-logic tests for the MLX VL backend — prompt building + JSON parsing, no model."""

from __future__ import annotations

from ladpipe.types import Moment
from ladpipe.vl.mlx_vlm import build_prompt, condense_rules, parse_decision


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


def test_prompt_includes_rules_transcript_and_ocr() -> None:
    prompt = build_prompt(_moment(), rules="RULE: describe only the gap")
    assert "RULE: describe only the gap" in prompt
    assert "now consider the diagram" in prompt
    assert "System Architecture" in prompt
    assert '"emit"' in prompt  # asks for the JSON contract


def test_prompt_default_is_standard() -> None:
    assert "ONE short spoken sentence" in build_prompt(_moment(), rules="")


def test_prompt_brief_style() -> None:
    prompt = build_prompt(_moment(), rules="", verbosity="brief")
    assert "very short spoken sentence" in prompt
    assert "single most important uncovered fact" in prompt


def test_prompt_detailed_allows_multiple_sentences() -> None:
    prompt = build_prompt(_moment(), rules="", verbosity="detailed")
    assert "one to three short spoken sentences" in prompt


def test_prompt_unknown_verbosity_falls_back_to_standard() -> None:
    assert "ONE short spoken sentence" in build_prompt(_moment(), rules="", verbosity="bogus")


def test_prompt_verbosity_changes_style_line_only() -> None:
    # the emit criteria stay identical across levels
    for verbosity in ("brief", "standard", "detailed"):
        p = build_prompt(_moment(), rules="", verbosity=verbosity)
        assert "set emit=false" in p and '"emit"' in p


def test_condense_rules_extracts_statements() -> None:
    raw = (
        "rules:\n"
        "  - id: a\n    rule: describe figures concisely\n"
        "  - id: b\n    rule: present tense\n"
    )
    out = condense_rules(raw)
    assert "describe figures concisely" in out and "present tense" in out
    assert "id:" not in out  # metadata dropped


def test_parse_clean_emit() -> None:
    raw = '{"emit": true, "ad_text": "A flowchart", "teacher_rung": 2, "rationale": "x"}'
    d = parse_decision(raw)
    assert d.emit and d.ad_text == "A flowchart" and d.teacher_rung == 2


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
