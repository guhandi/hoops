import json, re
import anthropic
from .render import Narrative
from .repair import extract_json
from .transcribe import envelope_text

_SYSTEM = """You are a beat writer filing a very short recap of a tiny basketball game:
one person shooting at a closet hoop until they make three in a row. Dry and specific,
not enthusiastic. Rules, all hard:
- NO digits or numerals anywhere. Numbers you receive are context only; the email
  template injects all figures.
- NO comparative or historical claims (no "best", "fastest yet", "this week"). You see
  one session and nothing else.
- Recap: at most three sentences. Within-session dynamics only.
- quote: an EXACT verbatim substring of the transcript, with its start time.
- Context may include almost_closeouts (two-in-a-row make runs that got broken
  before the closeout) and uncorroborated_calls (calls where no ball-impact
  sound was heard — feel free to tease, gently, that the mic has doubts).
  Reference them only in words, never digits.
Return ONLY JSON: {"headline": str, "recap": str, "quote": str, "quote_t_s": float}"""

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()

def generate_narrative(stats: dict, env: dict, model: str) -> Narrative | None:
    try:
        client = anthropic.Anthropic()
        payload = (f"Session stats (context only, do not restate numbers): "
                   f"{json.dumps({k: stats.get(k) for k in ['shots_to_three', 'makes', 'misses', 'longest_make_streak', 'longest_miss_streak', 'median_gap_s', 'session_len_s', 'notes', 'almost_closeouts', 'closed_out', 'uncorroborated_calls']})}\n\n"
                   f"Transcript: {envelope_text(env)}")
        msg = client.messages.create(model=model, max_tokens=500, system=_SYSTEM,
                                     messages=[{"role": "user", "content": payload}])
        data = extract_json(msg.content[0].text)
        if not isinstance(data, dict):
            return None
        headline, recap = str(data["headline"]), str(data["recap"])
        quote = str(data["quote"])
        if re.search(r"\d", headline + recap):
            return None
        if len(re.findall(r"[.!?]+", recap)) > 3:
            return None
        if _norm(quote) not in _norm(envelope_text(env)):
            return None
        t = data.get("quote_t_s")
        return Narrative(headline=headline, recap=recap, quote=quote,
                         quote_t_s=float(t) if t is not None else None)
    except Exception:
        return None
