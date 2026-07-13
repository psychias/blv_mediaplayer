from __future__ import annotations

from ladpipe import audio, mixer


def test_mixer_length_invariance() -> None:
    base = audio.silence(5.0, 24000)
    clip = audio.tone(2.0, 24000)
    out = mixer.build(base, [(1.0, clip), (4.5, clip)])  # second clip overruns the end
    assert len(out.samples) == len(base.samples)  # output length == input length


def test_mixer_does_not_overflow_past_end() -> None:
    base = audio.silence(1.0, 24000)
    clip = audio.tone(2.0, 24000)  # longer than base
    out = mixer.build(base, [(0.5, clip)])
    assert len(out.samples) == len(base.samples)
    assert all(-1.0 <= s <= 1.0 for s in out.samples)


def test_overlay_clamps_to_unit_range() -> None:
    base = audio.tone(1.0, 24000, amp=0.9)
    loud = audio.tone(1.0, 24000, amp=0.9)
    out = mixer.build(base, [(0.0, loud)])
    assert max(out.samples) <= 1.0 and min(out.samples) >= -1.0


def test_silence_is_silent() -> None:
    base = audio.silence(0.5, 24000)
    assert set(base.samples) == {0.0}
