"""SSE frame parsing — the protocol port of agentStream.ts."""

from ovb.sse import (
    CardFrame,
    CardProposedFrame,
    DeltaFrame,
    DoneFrame,
    ErrorFrame,
    MoodFrame,
    UnknownFrame,
    parse_frames,
)


def _wire(*payloads: str) -> str:
    return "".join(f"data: {p}\n\n" for p in payloads)


def test_parses_delta_done_sequence() -> None:
    buf = _wire(
        '{"type":"delta","text":"Hel"}',
        '{"type":"delta","text":"lo"}',
        '{"type":"done","turn_id":"t1","latency_ms":42}',
    )
    frames, remaining = parse_frames(buf)
    assert remaining == ""
    assert [type(f) for f in frames] == [DeltaFrame, DeltaFrame, DoneFrame]
    assert "".join(f.text for f in frames if isinstance(f, DeltaFrame)) == "Hello"
    done = frames[-1]
    assert isinstance(done, DoneFrame) and done.turn_id == "t1" and done.latency_ms == 42


def test_keeps_incomplete_trailing_frame_in_remaining() -> None:
    buf = 'data: {"type":"delta","text":"a"}\n\ndata: {"type":"delta","te'
    frames, remaining = parse_frames(buf)
    assert len(frames) == 1
    assert remaining == 'data: {"type":"delta","te'


def test_drops_non_json_and_non_dict_frames() -> None:
    buf = _wire("not json at all", "[1,2,3]", '{"type":"delta","text":"ok"}')
    frames, _ = parse_frames(buf)
    assert len(frames) == 1
    assert isinstance(frames[0], DeltaFrame)


def test_unknown_type_is_kept_as_unknown_not_dropped() -> None:
    frames, _ = parse_frames(_wire('{"type":"speculative","x":1}'))
    assert len(frames) == 1 and isinstance(frames[0], UnknownFrame)
    assert frames[0].type == "speculative"


def test_card_error_mood_proposed_mapping() -> None:
    buf = _wire(
        '{"type":"card","source":"ov","source_id":"x","node_id":"n1","snapshot":{"a":1}}',
        '{"type":"card_proposed","node":{"id":"n2","title":"Aman"}}',
        '{"type":"mood","mood_id":"twilight"}',
        '{"type":"error","reason":"upstream_unavailable"}',
    )
    frames, _ = parse_frames(buf)
    card, proposed, mood, err = frames
    assert isinstance(card, CardFrame) and card.node_id == "n1" and card.snapshot == {"a": 1}
    assert isinstance(proposed, CardProposedFrame) and proposed.node["title"] == "Aman"
    assert isinstance(mood, MoodFrame) and mood.mood_id == "twilight"
    assert isinstance(err, ErrorFrame) and err.reason == "upstream_unavailable"


def test_data_without_space_is_valid_per_spec() -> None:
    frames, _ = parse_frames('data:{"type":"delta","text":"q"}\n\n')
    assert isinstance(frames[0], DeltaFrame) and frames[0].text == "q"
