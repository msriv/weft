"""Small-model adapters that run on our own CPUs (D7): embeddings, language ID, entities.

Each is a Protocol with a dependency-free default (deterministic, used in tests and local dev)
and a real implementation that imports its heavy library lazily. Pick with WEFT_NLP=real|light.
The light versions are not good enough for production quality; they exist so every stage can run
end to end without downloading models.
"""

import hashlib
import itertools
import math
import os
import re
from typing import Any, ClassVar, Protocol

import httpx

from weft_core.textutil import words

DIM = 1024  # BGE-M3
STOP_EN = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "and",
        "is",
        "are",
        "was",
        "were",
        "for",
        "on",
        "that",
        "with",
        "as",
        "by",
        "at",
        "from",
        "it",
        "be",
        "has",
        "have",
    ]
)


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class LangId(Protocol):
    def detect(self, text: str) -> str: ...


class Entities(Protocol):
    def extract(self, text: str) -> list[tuple[str, str]]:
        """(name, kind) with kind in person | place | org | other."""
        ...


class HashEmbedder:
    """Signed feature hashing of unigrams and bigrams, L2-normalised."""

    def embed(self, text: str) -> list[float]:
        w = [x for x in words(text) if x not in STOP_EN]
        v = [0.0] * DIM
        for f in w + [" ".join(p) for p in itertools.pairwise(w)]:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            v[h % DIM] += 1.0 if (h >> 63) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


class BgeM3Embedder:
    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self._m = SentenceTransformer("BAAI/bge-m3")

    def embed(self, text: str) -> list[float]:
        return [float(x) for x in self._m.encode(text, normalize_embeddings=True)]


class StopwordLangId:
    """English or 'und'. Enough while English is the only launch language."""

    def detect(self, text: str) -> str:
        w = words(text)
        return "en" if w and sum(x in STOP_EN for x in w) / len(w) > 0.15 else "und"


class GlotLangId:
    def __init__(self, model_path: str) -> None:
        import fasttext

        self._m = fasttext.load_model(model_path)

    def detect(self, text: str) -> str:
        # List input: fasttext's single-string path calls np.array(copy=False), which NumPy 2 rejects.
        labels, _ = self._m.predict([" ".join(text.split())])
        label = str(labels[0][0])  # e.g. __label__eng_Latn
        code = label.removeprefix("__label__")[:3]
        return {"eng": "en"}.get(code, code)


_CAP = re.compile(r"\b([A-Z][\w'’.-]+(?:\s+(?:of|the|al|bin|de|van|von)?\s*[A-Z][\w'’.-]+){0,3})")
NOT_ENT = {"The", "A", "An", "In", "On", "At", "He", "She", "It", "They", "This", "That", "But"}


class RegexEntities:
    """Capitalised phrases. Kind is always 'other'."""

    def extract(self, text: str) -> list[tuple[str, str]]:
        seen: dict[str, str] = {}
        for m in _CAP.finditer(text):
            name = m.group(1).strip(" .,-")
            if name and name not in NOT_ENT and len(name) > 2:
                seen.setdefault(name, "other")
        return list(seen.items())


class SpacyEntities:
    KINDS: ClassVar[dict[str, str]] = {
        "PERSON": "person",
        "GPE": "place",
        "LOC": "place",
        "ORG": "org",
        "NORP": "org",
    }

    def __init__(self, model: str = "en_core_web_sm") -> None:
        import spacy

        self._nlp = spacy.load(model)

    def extract(self, text: str) -> list[tuple[str, str]]:
        out = {e.text: self.KINDS[e.label_] for e in self._nlp(text).ents if e.label_ in self.KINDS}
        return list(out.items())


class Nli(Protocol):
    def contradiction(self, premise: str, hypothesis: str) -> float:
        """Probability that the two sentences contradict each other."""
        ...

    def entailment(self, premise: str, hypothesis: str) -> float:
        """Probability that the premise entails the hypothesis."""
        ...


class LexicalNli:
    """Dev stand-in: contradiction when one sentence negates what the other says, or when they
    share most words but differ in a number. Not for production."""

    NEG: ClassVar[set[str]] = {
        "not",
        "no",
        "never",
        "denied",
        "denies",
        "deny",
        "false",
        "without",
        "none",
    }

    def contradiction(self, premise: str, hypothesis: str) -> float:
        a, b = set(words(premise)), set(words(hypothesis))
        if len(a & b) / max(len(a | b), 1) < 0.4:
            return 0.0
        return 0.9 if (a ^ b) & self.NEG else 0.0

    def entailment(self, premise: str, hypothesis: str) -> float:
        a, b = set(words(premise)), set(words(hypothesis))
        if not b or (a ^ b) & self.NEG:
            return 0.0
        return len(a & b) / len(b)  # share of the hypothesis's words the premise carries


class MdebertaNli:
    def __init__(self) -> None:
        from transformers import pipeline

        self._p = pipeline(
            "text-classification",
            model="MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
            top_k=None,
        )

    def contradiction(self, premise: str, hypothesis: str) -> float:
        out = self._p({"text": premise, "text_pair": hypothesis})
        flat = out[0] if isinstance(out[0], list) else out
        return float(next((x["score"] for x in flat if x["label"] == "contradiction"), 0.0))

    def entailment(self, premise: str, hypothesis: str) -> float:
        out = self._p({"text": premise, "text_pair": hypothesis})
        flat = out[0] if isinstance(out[0], list) else out
        return float(next((x["score"] for x in flat if x["label"] == "entailment"), 0.0))


class WikidataLinker:
    """Exact-label match against Wikidata search; cached by the caller in `entity_links`."""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def link(self, name: str) -> str | None:
        r = self._http.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "format": "json",
                "limit": 1,
            },
        )
        r.raise_for_status()
        hits: list[dict[str, Any]] = r.json().get("search", [])
        return (
            str(hits[0]["id"])
            if hits and hits[0].get("label", "").lower() == name.lower()
            else None
        )


class Nlp:
    """The bundle the workers take."""

    def __init__(self, embedder: Embedder, langid: LangId, entities: Entities, nli: Nli) -> None:
        self.embedder, self.langid, self.entities, self.nli = embedder, langid, entities, nli


def default_nlp() -> Nlp:
    if os.environ.get("WEFT_NLP", "light") == "real":
        return Nlp(
            BgeM3Embedder(),
            GlotLangId(os.environ["GLOTLID_MODEL"]),
            SpacyEntities(),
            MdebertaNli(),
        )
    return Nlp(HashEmbedder(), StopwordLangId(), RegexEntities(), LexicalNli())
