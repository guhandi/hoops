import math
from dataclasses import dataclass, field
from .config import Vocabulary
from .transcribe import Word

@dataclass
class Call:
    result: str
    raw_token: str
    t_s: float
    isolation_s: float
    confidence: float | None
    voided: bool = False

@dataclass(frozen=True)
class Ambiguous:
    text: str
    t_s: float
    isolation_s: float
    canonical: str

@dataclass
class ParseResult:
    calls: list[Call] = field(default_factory=list)
    ambiguous: list[Ambiguous] = field(default_factory=list)
    note: str | None = None

def _split_note(words: list[Word]) -> tuple[list[Word], str | None]:
    idx = None
    for i, w in enumerate(words):
        if w.text == "note":
            idx = i
    if idx is None:
        return words, None
    tail = [w.raw.strip() for w in words[idx + 1:]]
    return words[:idx], (" ".join(tail) if tail else None)

def _scratch_events(words: list[Word]) -> tuple[set[int], list[float]]:
    consumed, times = set(), []
    for i in range(len(words) - 1):
        if (words[i].text == "scratch" and words[i + 1].text == "that"
                and words[i + 1].start - words[i].end <= 0.75):
            consumed.update({i, i + 1})
            times.append(words[i].start)
    return consumed, times

def _isolation(words: list[Word], i: int) -> float:
    before = words[i].start - words[i - 1].end if i > 0 else math.inf
    after = words[i + 1].start - words[i].end if i < len(words) - 1 else math.inf
    return min(before, after)

def parse_words(words: list[Word], vocab: Vocabulary,
                iso_low: float, iso_high: float) -> ParseResult:
    body, note = _split_note(words)
    consumed, scratch_times = _scratch_events(body)
    calls: list[Call] = []
    ambiguous: list[Ambiguous] = []
    for i, w in enumerate(body):
        if i in consumed:
            continue
        canonical = vocab.surface_to_canonical.get(w.text)
        if canonical is None:
            continue
        iso = _isolation(words, i)
        if iso >= iso_high:
            calls.append(Call(result=canonical, raw_token=w.raw.strip(), t_s=w.start,
                              isolation_s=iso, confidence=w.confidence))
        elif iso > iso_low:
            ambiguous.append(Ambiguous(text=w.text, t_s=w.start,
                                       isolation_s=iso, canonical=canonical))
    for t in scratch_times:
        for c in reversed(calls):
            if c.t_s < t and not c.voided:
                c.voided = True
                break
    return ParseResult(calls=calls, ambiguous=ambiguous, note=note)
