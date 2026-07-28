import json
import anthropic
from .config import Vocabulary
from .invariants import Violation
from .parse import Call
from .transcribe import envelope_text

def extract_json(text: str):
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                obj, _ = dec.raw_decode(text[i:])
                return obj
            except ValueError:
                continue
    return None

_SYSTEM = """You reconstruct a basketball free-throw call sequence from a noisy transcript.
Hard constraints:
- The session ended the moment three consecutive makes occurred; the sequence must end
  with exactly one run of three consecutive makes, and no earlier run of three.
- Calls come only from this vocabulary (surface -> canonical): {vocab}
- A real call is an isolated utterance; words inside continuous commentary are not calls.
- "scratch that" voids the preceding call.
Return ONLY a JSON array of objects: {{"result": "make"|"miss", "t_s": <float seconds>,
"raw_token": "<surface form>"}} in time order, voided calls omitted. No other text."""

def attempt_repair(env: dict, rows: list[dict], violations: list[Violation],
                   vocab: Vocabulary, model: str) -> list[Call] | None:
    words = env["response"].get("words") or []
    word_dump = " ".join(f"{w['word'].strip()}@{w['start']:.2f}" for w in words)
    user = (f"Transcript words with start times:\n{word_dump}\n\n"
            f"Full text: {envelope_text(env)}\n\n"
            f"Deterministic parse produced {len(rows)} calls but violated: "
            + "; ".join(f"{v.id}: {v.message}" for v in violations)
            + "\nReconstruct the true call sequence.")
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model, max_tokens=1000,
            system=_SYSTEM.format(vocab=json.dumps(vocab.surface_to_canonical)),
            messages=[{"role": "user", "content": user}])
        data = extract_json(msg.content[0].text)
        if not isinstance(data, list) or not data:
            return None
        calls = []
        for d in data:
            if d.get("result") not in ("make", "miss"):
                return None
            calls.append(Call(result=d["result"], raw_token=str(d.get("raw_token", d["result"])),
                              t_s=float(d["t_s"]), isolation_s=0.0, confidence=None))
        return sorted(calls, key=lambda c: c.t_s)
    except Exception:
        return None
