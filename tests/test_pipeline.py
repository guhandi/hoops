import json
import shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.pipeline import process_file, replay_session
from hoops.session import read_session_json
from conftest import make_env

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
GOOD = [("okay", 0.5, 0.8), ("brick", 5.0, 5.3), ("come", 8.0, 8.2), ("on", 8.25, 8.4),
        ("swish", 12.0, 12.3), ("swish", 18.0, 18.3), ("swish", 24.0, 24.3),
        ("note", 27.0, 27.2), ("felt", 27.5, 27.7), ("good", 27.8, 28.0)]

class FakeTranscriber:
    model_id = "fake"
    def __init__(self, env): self.env = env
    def transcribe(self, path, prompt): return self.env["response"]

@pytest.fixture
def cfg(tmp_path, monkeypatch):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    c = load_config(tmp_path / "config.yaml")
    c.gudata["enabled"] = False      # tests assert offline behavior regardless of live config
    c.gap_repair["enabled"] = False      # gap-repair tests opt in explicitly
    return c

def audio(tmp_path, name="hoops__20260727-061204.m4a"):
    src = REPO / "fixtures" / "dev" / "dev03.m4a"   # real m4a → mutagen duration works
    dst = tmp_path / name
    shutil.copy(src, dst)
    return dst

def test_happy_path(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    assert out.status == "ok" and out.sid == "20260727-061204"
    sdir = out.session_dir
    for name in ["transcript.json", "transcript.txt", "shots.csv", "session.json",
                 "strip.png", "report.html", "audio.m4a"]:
        assert (sdir / name).exists(), name
    assert out.stats["shots_to_three"] == 4 and out.stats["invariants_passed"] is True
    assert out.stats["notes"] == "felt good"
    assert out.flags == []
    assert out.stats["session_id_source"] == "filename"

def test_duplicate_skipped(tmp_path, cfg):
    f = audio(tmp_path)
    t = FakeTranscriber(make_env(GOOD, duration=30.0))
    process_file(f, cfg, t, email=False, archive="copy")
    out2 = process_file(f, cfg, t, email=False, archive="copy")
    assert out2.status == "duplicate"

def test_short_audio_rejected(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD)), email=False,
                       archive="copy", min_duration_override=999999)
    assert out.status == "rejected"
    assert any((cfg.repo_root / "rejected").iterdir())

def test_reject_archive_none_leaves_source_untouched(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD)), email=False,
                       archive="none", min_duration_override=999999)
    assert out.status == "rejected"
    assert f.exists()
    rej = cfg.repo_root / "rejected"
    assert not rej.exists() or not any(rej.iterdir())

def test_truncated_audio_rejected(tmp_path, cfg):
    f = tmp_path / "hoops__20260727-070000.m4a"
    f.write_bytes(b"not an mp4 at all")
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD)), email=False, archive="copy")
    assert out.status == "rejected"

def test_zero_calls_needs_review(tmp_path, cfg):
    env = make_env([("just", 1.0, 1.2), ("talking", 1.3, 1.6)], duration=30.0)
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(env), email=False, archive="copy")
    assert out.status == "needs_review"
    assert (cfg.repo_root / "needs_review").exists()

def test_needs_review_respects_out_root(tmp_path, cfg):
    out_root = tmp_path / "isolated" / "sessions"
    env = make_env([("just", 1.0, 1.2), ("talking", 1.3, 1.6)], duration=30.0)
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(env), email=False,
                       archive="copy", out_root=out_root)
    assert out.status == "needs_review"
    assert (out_root.parent / "needs_review").exists()
    assert not (cfg.repo_root / "needs_review").exists()

def test_invariant_failure_flagged_not_dropped(tmp_path, cfg):
    env = make_env([("swish", 5.0, 5.3), ("brick", 10.0, 10.3)], duration=30.0)
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(env), email=False,
                       archive="copy", repair_enabled=False)
    assert out.status == "ok"
    assert out.stats["invariants_passed"] is False and out.flags

def test_replay_rewrites_and_preserves_quote(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    stats = read_session_json(out.session_dir)
    stats["quote_of_day"] = "kept quote"
    (out.session_dir / "session.json").write_text(__import__("json").dumps(stats))
    r = replay_session(out.session_dir, cfg)
    assert r.status == "ok"
    assert read_session_json(out.session_dir)["quote_of_day"] == "kept quote"
    assert read_session_json(out.session_dir)["shots_to_three"] == 4

def test_sidecar_named_vocab_applies(tmp_path, cfg):
    f = audio(tmp_path)
    f.with_suffix(".json").write_text('{"vocabulary": "make_miss"}')
    env = make_env([("make", 5.0, 5.3), ("miss", 12.0, 12.3)], duration=30.0)
    out = process_file(f, cfg, FakeTranscriber(env), email=False,
                       cached_env=env, repair_enabled=False, archive="move")
    assert out.status == "ok"
    assert [r["result"] for r in out.rows] == ["make", "miss"]
    assert (out.session_dir / "vocab.json").exists()
    assert not f.with_suffix(".json").exists()      # consumed

def test_sidecar_inline_map_applies(tmp_path, cfg):
    f = audio(tmp_path)
    f.with_suffix(".json").write_text('{"vocab_map": {"make": ["bucket"], "miss": ["clank"]}}')
    env = make_env([("bucket", 5.0, 5.3), ("clank", 12.0, 12.3)], duration=30.0)
    out = process_file(f, cfg, FakeTranscriber(env), email=False,
                       cached_env=env, repair_enabled=False)
    assert out.status == "ok"
    assert [r["result"] for r in out.rows] == ["make", "miss"]

def test_malformed_sidecar_routes_to_needs_review(tmp_path, cfg):
    f = audio(tmp_path)
    f.with_suffix(".json").write_text("{not json")
    out = process_file(f, cfg, FakeTranscriber(make_env([])), email=False,
                       archive="move")
    assert out.status == "needs_review"
    nr = cfg.repo_root / "needs_review"
    assert (nr / f.name).exists() and (nr / f.with_suffix(".json").name).exists()

def test_sidecar_vocab_map_string_value_rejected(tmp_path, cfg):
    f = audio(tmp_path)
    f.with_suffix(".json").write_text('{"vocab_map": {"make": "swish", "miss": ["clank"]}}')
    out = process_file(f, cfg, FakeTranscriber(make_env([])), email=False, archive="move")
    assert out.status == "needs_review"
    assert any("vocab_map" in flag and "make" in flag for flag in out.flags)

def test_sidecar_vocab_map_missing_miss_key_rejected(tmp_path, cfg):
    f = audio(tmp_path)
    f.with_suffix(".json").write_text('{"vocab_map": {"make": ["bucket"]}}')
    out = process_file(f, cfg, FakeTranscriber(make_env([])), email=False, archive="move")
    assert out.status == "needs_review"
    assert any("missing" in flag and "miss" in flag for flag in out.flags)

def test_sidecar_vocab_map_bogus_canonical_key_rejected(tmp_path, cfg):
    f = audio(tmp_path)
    f.with_suffix(".json").write_text(
        '{"vocab_map": {"mak": ["bucket"], "miss": ["clank"]}}')
    out = process_file(f, cfg, FakeTranscriber(make_env([])), email=False, archive="move")
    assert out.status == "needs_review"
    assert any("mak" in flag for flag in out.flags)

def test_explicit_vocab_name_beats_sidecar(tmp_path, cfg):
    f = audio(tmp_path)
    f.with_suffix(".json").write_text('{"vocab_map": {"make": ["bucket"], "miss": ["clank"]}}')
    env = make_env([("make", 5.0, 5.3)], duration=30.0)
    out = process_file(f, cfg, FakeTranscriber(env), email=False,
                       vocab_name="make_miss", cached_env=env, repair_enabled=False)
    assert out.status == "ok" and [r["result"] for r in out.rows] == ["make"]

def test_narrative_persisted_and_replay_reuses_it(tmp_path, cfg, monkeypatch):
    from hoops.render import Narrative
    from hoops.pipeline import process_file, replay_session
    n = Narrative("Ice in the veins", "One cold stretch, then done.", "come on", 9.0)
    monkeypatch.setattr("hoops.narrative.generate_narrative", lambda *a, **k: n)
    monkeypatch.setattr("hoops.mailer.send", lambda *a, **k: None)
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=True, out_root=tmp_path / "sessions")
    sdir = out.session_dir
    saved = json.loads((sdir / "narrative.json").read_text())
    assert saved == {"headline": "Ice in the veins",
                     "recap": "One cold stretch, then done.",
                     "quote": "come on", "quote_t_s": 9.0}
    assert "Ice in the veins" in (sdir / "report.html").read_text()
    replay_session(sdir, cfg)
    assert "Ice in the veins" in (sdir / "report.html").read_text()   # not lost

def test_report_is_interactive_and_embeds_audio(tmp_path, cfg):
    from hoops.pipeline import process_file
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, out_root=tmp_path / "sessions")
    html = (out.session_dir / "report.html").read_text()
    assert "const DATA =" in html
    assert "data:audio/mp4;base64," in html            # audio was archived then embedded

def test_replay_without_audio_or_narrative_degrades(tmp_path, cfg):
    from hoops.pipeline import process_file, replay_session
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, out_root=tmp_path / "sessions")
    (out.session_dir / "audio.m4a").unlink()
    replay_session(out.session_dir, cfg)
    html = (out.session_dir / "report.html").read_text()
    assert "audio unavailable" in html.lower()
    assert "const DATA =" in html

def test_pipeline_writes_sidecars_and_uncorroborated(tmp_path, cfg, monkeypatch):
    canned_ac = {"envelope": [0.1], "envelope_hz": 14.35, "events": []}
    def fake_ac(sdir, audio, params):
        (sdir / "acoustics.json").write_text(json.dumps(canned_ac)); return canned_ac
    canned_fu = {"shots": [], "extra_events": [],
                 "summary": {"n_calls": 2, "n_paired": 1, "pairing_rate": 0.5,
                             "n_impact_missing": 1, "n_ambiguous": 0,
                             "n_call_missing": 0, "n_warmup": 0,
                             "median_latency_s": 1.2, "latencies_s": [1.2]}}
    def fake_fu(sdir, rows, events, params):
        (sdir / "fusion.json").write_text(json.dumps(canned_fu)); return canned_fu
    monkeypatch.setattr("hoops.pipeline.write_acoustics", fake_ac)
    monkeypatch.setattr("hoops.pipeline.write_fusion", fake_fu)
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    assert out.status == "ok"
    assert (out.session_dir / "acoustics.json").exists()
    assert (out.session_dir / "fusion.json").exists()
    assert out.stats["uncorroborated_calls"] == 1

def test_pipeline_survives_acoustics_failure(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr("hoops.pipeline.write_acoustics", lambda *a: None)
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    assert out.status == "ok"
    assert "uncorroborated_calls" not in out.stats
    assert not (out.session_dir / "fusion.json").exists()   # fusion got events=None

def test_replay_removes_stale_sidecars_when_stages_yield_none(tmp_path, cfg, monkeypatch):
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    for name in ("impacts.json", "acoustics.json", "fusion.json"):
        (out.session_dir / name).write_text("{}")            # plant stale sidecars
    monkeypatch.setattr("hoops.pipeline.write_acoustics", lambda *a: None)
    replay_session(out.session_dir, cfg)
    for name in ("impacts.json", "acoustics.json", "fusion.json"):
        assert not (out.session_dir / name).exists()

def test_gudata_success_writes_sidecar_no_flag(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr("hoops.pipeline.push_stage",
        lambda *a: ({"session_id": "s1", "observation_ids": [], "count": 5}, None))
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    assert out.status == "ok"
    assert json.loads((out.session_dir / "gudata_push.json").read_text())["session_id"] == "s1"
    assert not any("gudata" in f for f in out.flags)

def test_gudata_failure_is_flagged_and_never_blocks_email(tmp_path, cfg, monkeypatch):
    calls = {}
    monkeypatch.setattr("hoops.pipeline.push_stage", lambda *a: (None, "connection refused"))
    monkeypatch.setattr("hoops.narrative.generate_narrative", lambda *a, **k: None)
    monkeypatch.setattr("hoops.mailer.send", lambda msg, c: calls.setdefault("sent", True))
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=True, archive="copy")
    assert out.status == "ok"
    assert "gudata push failed: connection refused" in out.flags
    assert "gudata push failed" in (out.session_dir / "report.html").read_text()
    assert calls.get("sent") is True                      # email still went out
    assert not (out.session_dir / "gudata_push.json").exists()

def test_gudata_disabled_by_default_makes_no_call(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr("hoops.gudata.post_json",
                        lambda *a, **k: pytest.fail("HTTP called with gudata disabled"))
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    assert out.status == "ok" and not (out.session_dir / "gudata_push.json").exists()

def test_session_json_persists_vocab_and_replay_uses_it(tmp_path, cfg):
    f = audio(tmp_path)
    env = make_env([("make", 5.0, 5.3), ("miss", 12.0, 12.3)], duration=30.0)
    out = process_file(f, cfg, FakeTranscriber(env), email=False,
                       vocab_name="make_miss", cached_env=env, repair_enabled=False)
    assert out.status == "ok"
    stats = read_session_json(out.session_dir)
    assert stats["vocab_name"] == "make_miss"
    assert stats["vocab_map"] == {"make": "make", "miss": "miss"}
    # replay with NO vocab arg must reuse the persisted make_miss mapping,
    # even though the config default is swish_brick
    r = replay_session(out.session_dir, cfg)
    assert [row["result"] for row in r.rows] == ["make", "miss"]
    assert read_session_json(out.session_dir)["vocab_name"] == "make_miss"

class SeqTranscriber:
    """Main response first, then one canned clip response per gap span."""
    model_id = "fake"
    def __init__(self, responses): self.responses = list(responses)
    def transcribe(self, path, prompt): return self.responses.pop(0)

def test_gap_repair_recovers_calls(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)
    cfg.gap_repair["enabled"] = True
    # dev03.m4a is ~41.5s; main transcript ends at 24.3 -> tail gap ~17s
    main = make_env([("brick", 5.0, 5.3), ("swish", 12.0, 12.3),
                     ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)],
                    duration=41.5)["response"]
    clip = {"words": [{"word": "swish", "start": 8.0, "end": 8.3}]}  # ~30.3s session time
    f = audio(tmp_path)
    out = process_file(f, cfg, SeqTranscriber([main, clip]),
                       email=False, archive="copy", repair_enabled=False)
    assert out.status == "ok"
    assert len(out.rows) == 5
    assert out.stats["gap_repair_recovered"] == 1
    assert any("recovered by transcript gap repair" in fl for fl in out.flags)
    env = json.loads((out.session_dir / "transcript.json").read_text())
    assert env["gap_repair"]["n_recovered"] == 1
    assert env["gap_repair"]["edge_margin_s"] == cfg.isolation_high

def test_gap_repair_disabled_no_stage(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy", repair_enabled=False)
    assert "gap_repair_recovered" not in out.stats
    env = json.loads((out.session_dir / "transcript.json").read_text())
    assert "gap_repair" not in env

def test_gap_repair_errors_flagged(tmp_path, cfg, monkeypatch):
    def broken(audio, t0, t1, dest): raise RuntimeError("no codec")
    monkeypatch.setattr("hoops.gap_repair.extract_clip", broken)
    cfg.gap_repair["enabled"] = True
    main = make_env([("brick", 5.0, 5.3), ("swish", 12.0, 12.3),
                     ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)],
                    duration=41.5)["response"]
    f = audio(tmp_path)
    out = process_file(f, cfg, SeqTranscriber([main]), email=False,
                       archive="copy", repair_enabled=False)
    assert out.status == "ok"                       # never blocks the report
    assert out.stats["gap_repair_recovered"] == 0
    assert any(fl.startswith("gap repair error:") for fl in out.flags)

def test_replay_preserves_gap_repair_stats(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)
    cfg.gap_repair["enabled"] = True
    main = make_env([("brick", 5.0, 5.3), ("swish", 12.0, 12.3),
                     ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)],
                    duration=41.5)["response"]
    clip = {"words": [{"word": "swish", "start": 8.0, "end": 8.3}]}
    f = audio(tmp_path)
    out = process_file(f, cfg, SeqTranscriber([main, clip]),
                       email=False, archive="copy", repair_enabled=False)
    r = replay_session(out.session_dir, cfg)
    assert r.stats["gap_repair_recovered"] == 1
    assert any("recovered by transcript gap repair" in fl for fl in r.flags)

def _archived_session(tmp_path, cfg, env_words, duration):
    """Build a real archived session dir by processing, then strip it back
    to the artifacts retranscribe needs."""
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(env_words, duration=duration)),
                       email=False, archive="copy", repair_enabled=False)
    assert out.status == "ok"
    return out.session_dir

DENSE = [("brick", float(t), float(t) + 0.3) for t in range(1, 40, 5)]  # no gaps in 41.5s
HOLED = [("brick", 5.0, 5.3), ("swish", 12.0, 12.3),
         ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)]                  # tail gap ~17s

def test_retranscribe_skips_no_gaps(tmp_path, cfg):
    from hoops.pipeline import retranscribe_session
    sdir = _archived_session(tmp_path, cfg, DENSE, 41.5)
    before = (sdir / "transcript.json").read_text()
    class NeverCalled:
        def transcribe(self, path, prompt): raise AssertionError("no API call allowed")
    r = retranscribe_session(sdir, cfg, NeverCalled())
    assert r.status == "skipped_no_gaps"
    assert (sdir / "transcript.json").read_text() == before

def test_retranscribe_skips_already_repaired(tmp_path, cfg):
    import json as _json
    from hoops.pipeline import retranscribe_session
    sdir = _archived_session(tmp_path, cfg, HOLED, 41.5)
    env = _json.loads((sdir / "transcript.json").read_text())
    env["gap_repair"] = {"spans": [], "n_recovered": 0, "truncated": False,
                         "errors": [], "trigger_gap_s": 10.0, "pad_s": 2.0}
    (sdir / "transcript.json").write_text(_json.dumps(env))
    class NeverCalled:
        def transcribe(self, path, prompt): raise AssertionError("no API call allowed")
    r = retranscribe_session(sdir, cfg, NeverCalled())
    assert r.status == "skipped_repaired"

def test_retranscribe_retries_errored_repair(tmp_path, cfg, monkeypatch):
    import json as _json
    from hoops.pipeline import retranscribe_session
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)
    sdir = _archived_session(tmp_path, cfg, HOLED, 41.5)
    env = _json.loads((sdir / "transcript.json").read_text())
    env["gap_repair"] = {"spans": [], "n_recovered": 0, "truncated": False,
                         "errors": ["span [24.3, 41.5]: api down"],
                         "trigger_gap_s": 10.0, "pad_s": 2.0, "edge_margin_s": 0.4}
    (sdir / "transcript.json").write_text(_json.dumps(env))
    clip = {"words": [{"word": "swish", "start": 8.0, "end": 8.3}]}
    r = retranscribe_session(sdir, cfg, FakeTranscriber({"response": clip}))
    assert r.status == "ok"
    env2 = _json.loads((sdir / "transcript.json").read_text())
    assert env2["gap_repair"]["errors"] == []
    assert env2["gap_repair"]["n_recovered"] == 1

def test_retranscribe_retries_truncated_repair(tmp_path, cfg, monkeypatch):
    import json as _json
    from hoops.pipeline import retranscribe_session
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)
    sdir = _archived_session(tmp_path, cfg, HOLED, 41.5)
    env = _json.loads((sdir / "transcript.json").read_text())
    env["gap_repair"] = {"spans": [], "n_recovered": 0, "truncated": True,
                         "errors": [],
                         "trigger_gap_s": 10.0, "pad_s": 2.0, "edge_margin_s": 0.4}
    (sdir / "transcript.json").write_text(_json.dumps(env))
    clip = {"words": [{"word": "swish", "start": 8.0, "end": 8.3}]}
    r = retranscribe_session(sdir, cfg, FakeTranscriber({"response": clip}))
    assert r.status == "ok"

def test_retranscribe_skips_missing_audio(tmp_path, cfg):
    from hoops.pipeline import retranscribe_session
    sdir = _archived_session(tmp_path, cfg, HOLED, 41.5)
    (sdir / "audio.m4a").unlink()
    r = retranscribe_session(sdir, cfg, FakeTranscriber(make_env([])))
    assert r.status == "skipped_no_audio"

def test_retranscribe_repairs_and_replays(tmp_path, cfg, monkeypatch):
    import json as _json
    from hoops.pipeline import retranscribe_session
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)
    sdir = _archived_session(tmp_path, cfg, HOLED, 41.5)
    n_before = len(_json.loads((sdir / "transcript.json").read_text())
                   ["response"]["words"])
    clip = {"words": [{"word": "swish", "start": 8.0, "end": 8.3}]}
    r = retranscribe_session(sdir, cfg, FakeTranscriber({"response": clip}))
    assert r.status == "ok"
    assert len(r.rows) == n_before + 1                       # recovered call landed
    assert r.stats["gap_repair_recovered"] == 1
    env = _json.loads((sdir / "transcript.json").read_text())
    assert env["gap_repair"]["n_recovered"] == 1
