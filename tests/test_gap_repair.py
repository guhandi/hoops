import pytest
from hoops.gap_repair import find_gaps, build_spans, merge_recovered

pytestmark = pytest.mark.unit

def test_no_gaps_dense_words():
    words = [(0.5, 1.0), (6.0, 6.5), (12.0, 12.5)]
    assert find_gaps(words, 15.0, 10.0) == []

def test_interior_gap():
    words = [(5.6, 7.0), (30.1, 31.5), (49.6, 50.2)]
    assert find_gaps(words, 55.0, 10.0) == [(7.0, 30.1), (31.5, 49.6)]

def test_head_and_tail_gaps():
    words = [(20.0, 20.5), (25.0, 25.5)]
    assert find_gaps(words, 40.0, 10.0) == [(0.0, 20.0), (25.5, 40.0)]

def test_empty_transcript_is_one_full_gap():
    assert find_gaps([], 41.5, 10.0) == [(0.0, 41.5)]

def test_gap_exactly_at_threshold_does_not_trigger():
    words = [(0.0, 1.0), (11.0, 11.5)]
    assert find_gaps(words, 12.0, 10.0) == []

def test_r03_shape():
    # the two real gaps from session 20260819-131500 (word ends → next starts)
    words = [(30.1, 31.5), (49.6, 50.2), (110.96, 111.66), (127.48, 128.36)]
    gaps = find_gaps(words, 136.13, 10.0)
    assert (31.5, 49.6) in gaps and (111.66, 127.48) in gaps

def test_build_spans_pads_and_clamps():
    spans, truncated = build_spans([(1.0, 12.0), (100.0, 130.0)], 131.0, 2.0, 8)
    assert truncated is False
    assert spans == [{"gap": [1.0, 12.0], "clip": [0.0, 14.0]},
                     {"gap": [100.0, 130.0], "clip": [98.0, 131.0]}]

def test_build_spans_cap():
    gaps = [(float(i * 20), float(i * 20 + 11)) for i in range(10)]
    spans, truncated = build_spans(gaps, 500.0, 2.0, 8)
    assert len(spans) == 8 and truncated is True

def test_merge_recovered_keeps_only_inside_gap():
    clip_words = [{"word": "break", "start": 0.5, "end": 0.9},    # 110.16 — before gap
                  {"word": "splash", "start": 10.0, "end": 10.4},  # 119.66 — inside
                  {"word": "go", "start": 19.0, "end": 19.3}]      # 128.66 — after gap
    out = merge_recovered((111.66, 127.48), 109.66, clip_words)
    assert out == [{"word": "splash", "start": 119.66, "end": 120.06}]

def test_merge_recovered_empty_clip():
    assert merge_recovered((10.0, 25.0), 8.0, []) == []
