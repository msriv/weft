"""Small text helpers shared by the stream and nightly paths. No models here."""

import hashlib
import math
import re
from collections.abc import Iterable, Sequence

_WORD = re.compile(r"\w+", re.UNICODE)
_SENT = re.compile(r'(?<=[.!?])["”’)]*\s+(?=["“‘(]*[A-Z0-9])')
PRIME = (1 << 61) - 1
N_PERM = 64


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def sentences(text: str) -> list[tuple[int, int]]:
    """Character spans (start, end) of sentences. text[start:end] is the sentence."""
    spans, pos = [], 0
    for m in _SENT.finditer(text):
        spans.append((pos, m.start() + len(m.group(0).rstrip())))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def shingles(text: str, k: int = 5) -> set[str]:
    w = words(text)
    return {" ".join(w[i : i + k]) for i in range(max(len(w) - k + 1, 1))} if w else set()


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _h(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


def minhash(sh: Iterable[str]) -> list[int]:
    """64-permutation MinHash signature (fixed permutations, so signatures are comparable)."""
    hs = [_h(s) for s in sh] or [0]
    return [min((_h(f"a{i}") % PRIME * x + _h(f"b{i}")) % PRIME for x in hs) for i in range(N_PERM)]


def minhash_similarity(a: Sequence[int], b: Sequence[int]) -> float:
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb) if na and nb else 0.0
