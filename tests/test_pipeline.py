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
