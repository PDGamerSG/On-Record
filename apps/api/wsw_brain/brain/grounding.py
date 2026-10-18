"""Answer checks shared by meeting and document answers.

Answers are read aloud, so a wrong amount or date cannot be taken back. Two rules, applied per sentence:

- Numbers: every number in a sentence must appear in the evidence that sentence cites, or, for an
  uncited sentence, in any retrieved evidence. Numbers are compared after mapping Indian-script digits
  to ASCII and removing thousands separators (4,999 = 4999, 1,50,000 = 150000).
- Support: a sentence without a valid citation is kept only if it is not a factual claim (a "don't know"
  line or a connective) or shares at least MIN_OVERLAP content words with the retrieved evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..graph.text import STOPWORDS, content_tokens, normalise

MIN_OVERLAP = 3
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_MARKER = re.compile(r"\[(?:[du]):[^\]\s]+\]")
_SENTENCE = re.compile(r"(?<=[.!?।])\s+")  # "।" is the Devanagari danda
# A full stop after these does not end a sentence ("Rs. 4,999", "Dr. Rao", "p. 3").
_ABBREVIATIONS = frozenset(
    {"rs.", "inr.", "dr.", "mr.", "mrs.", "ms.", "no.", "vs.", "e.g.", "i.e.", "etc.", "p.", "pp.", "approx."}
)
_LEADING_MARKERS = re.compile(r"^((?:\[(?:[du]):[^\]\s]+\][\s,]*)+)(.*)$", re.DOTALL)
_NO_ANSWER = re.compile(
    r"\b(?:i (?:do not|don't|could not|couldn't|cannot|can't) (?:know|find|tell|see)"
    r"|(?:do|does|did) not (?:mention|cover|say|show|include|state|record)"
    r"|(?:doesn't|don't|didn't) (?:mention|cover|say|show|include|state|record)"
    r"|no (?:evidence|record|mention|information)|not (?:mentioned|covered|recorded))\b",
    re.IGNORECASE,
)


@dataclass
class Checked:
    """The sentences kept, the ones withheld for lack of support, and numbers missing from the evidence."""

    sentences: list[str]
    withheld: list[str] = field(default_factory=list)
    unsupported_numbers: set[str] = field(default_factory=set)
    number_sentences: list[str] = field(default_factory=list)  # kept sentences with unsupported numbers

    @property
    def text(self) -> str:
        return " ".join(self.sentences).strip()

    def without_unsupported_numbers(self) -> Checked:
        """The same check with the sentences that carry unsupported numbers withheld too."""
        kept = [s for s in self.sentences if s not in self.number_sentences]
        return Checked(kept, [*self.withheld, *self.number_sentences])


def numbers_in(text: str) -> set[str]:
    """Numbers in `text`, citation markers ignored, as ASCII digits without thousands separators."""
    plain = _MARKER.sub(" ", text or "")
    ascii_digits = "".join(str(unicodedata.digit(ch)) if ch.isdigit() else ch for ch in plain)
    return {n.replace(",", "") for n in _NUMBER.findall(ascii_digits)}


def is_claim(sentence: str) -> bool:
    """False for "don't know" lines and short connectives, which need no evidence."""
    plain = _MARKER.sub(" ", sentence)
    if _NO_ANSWER.search(plain.replace("’", "'")):
        return False
    return len([t for t in normalise(plain).split() if t not in STOPWORDS]) >= MIN_OVERLAP


def overlap(sentence: str, evidence: str) -> int:
    """Content words the sentence shares with the evidence."""
    return len(content_tokens(_MARKER.sub(" ", sentence)) & content_tokens(evidence))


def split_sentences(answer: str) -> list[str]:
    """Sentences of an answer, with citation markers written after a full stop kept on that sentence."""
    sentences: list[str] = []
    joined = False  # the previous piece ended with an abbreviation, so this piece continues it
    for piece in _SENTENCE.split((answer or "").strip()):
        if joined:
            sentences[-1] = f"{sentences[-1]} {piece}"
            joined = piece.split()[-1].lower() in _ABBREVIATIONS
            continue
        match = _LEADING_MARKERS.match(piece)
        if match and sentences:
            sentences[-1] = f"{sentences[-1]} {match.group(1).strip()}"
            piece = match.group(2).strip()
        if piece:
            sentences.append(piece)
            joined = piece.split()[-1].lower() in _ABBREVIATIONS
    return sentences


def check_answer(
    answer: str, evidence: dict[str, str], citations: re.Pattern[str] | Iterable[re.Pattern[str]]
) -> Checked:
    """Check each sentence of `answer`. `evidence` maps a citable id ("m1:u00002" or a document chunk id)
    to its text; each pattern in `citations` captures the cited id in group 1."""
    patterns = [citations] if isinstance(citations, re.Pattern) else list(citations)
    everything = " ".join(evidence.values())
    checked = Checked([])
    for sentence in split_sentences(answer):
        ids = [i for pattern in patterns for i in pattern.findall(sentence) if i in evidence]
        source = " ".join(evidence[i] for i in ids) if ids else everything
        missing = numbers_in(sentence) - numbers_in(source)
        if not ids and is_claim(sentence) and overlap(sentence, everything) < MIN_OVERLAP:
            checked.withheld.append(sentence)
            continue
        checked.sentences.append(sentence)
        if missing:
            checked.unsupported_numbers |= missing
            checked.number_sentences.append(sentence)
    return checked
