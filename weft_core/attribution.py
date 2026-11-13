"""Who said what (#101): split a claim sentence into speaker, cue and content spans.

With a spaCy pipeline (real NLP mode) the dependency parse finds the cue verb, its subject (the
speaker) and its clausal complement (the content). Without one, fixed patterns cover the common
news shapes: "X said (that) Y", "Y, X said", "according to X, Y" and "Y, according to X".
CPU only, no model call. Offsets are into the sentence; callers shift them by the claim's start
(rule 3).

`speaker_kind` is "named" when the speaker carries a proper name, "anonymous" for unnamed
officials and sources, and "none" when the sentence has no attribution at all. `stance` is
"deny" for denial cues, else "assert".
"""

import re
from typing import Any

CUES = (
    "said",
    "says",
    "say",
    "told",
    "tells",
    "claimed",
    "claims",
    "claim",
    "denied",
    "denies",
    "deny",
    "announced",
    "announces",
    "stated",
    "states",
    "added",
    "insisted",
    "rejected",
    "confirmed",
    "reported",
)
DENY = {"denied", "denies", "deny", "rejected"}
LEMMAS = {
    "say",
    "tell",
    "claim",
    "deny",
    "announce",
    "state",
    "add",
    "insist",
    "reject",
    "confirm",
    "report",
}
_CUE = "|".join(CUES)
ANONYMOUS = re.compile(
    r"^(?:an?|the|two|three|several|some|many|other)?\s*(?:\w+\s+){0,3}?"
    r"(?:officials?|sources?|spokes(?:man|woman|person)|diplomats?|people|insiders?|aides?|"
    r"analysts?|witnesses|residents|reports?|authorities|military|government|ministry)\b"
    r"(?:\s+(?:familiar|close|with|who|in|of|from)\b.*)?$",
    re.IGNORECASE,
)
_NAME = re.compile(r"\b[A-Z][a-z]+")
_LEAD = re.compile(r"^(?:But|And|However|Meanwhile|Earlier|Later|On \w+),?\s+")

# speaker first: "Iran's foreign ministry said on Friday that ..."
_FIRST = re.compile(
    rf"^(?P<speaker>[^,;:\"“]{{2,80}}?)\s+(?P<cue>{_CUE})\b"
    r"(?:\s+(?:on|late|early)\s+\w+)?(?:\s+(?:reporters|journalists|\w+ media|[A-Z]\w+))?"
    r"(?:\s+that)?[,:]?\s+(?P<content>.+)$",
)
# content first: "Forty missiles were launched, officials said."
_LAST = re.compile(
    rf"^(?P<content>.+?)[,;]?\s*[”\"]?,?\s+(?P<speaker>[^,;\"“”]{{2,80}}?)\s+(?P<cue>{_CUE})\b"
    r"(?:\s+on\s+\w+)?\s*[.!]?$"
)
# inverted: "..., said Defence Minister X."
_INV = re.compile(
    rf"^(?P<content>.+?)[,;]?\s*[”\"]?,?\s+(?P<cue>{_CUE})\s+(?P<speaker>[^,;\"“”]{{2,80}}?)\s*[.!]?$"
)
_ACC_FIRST = re.compile(
    r"^(?P<cue>according to)\s+(?P<speaker>[^,]{2,80}),\s*(?P<content>.+)$", re.IGNORECASE
)
_ACC_LAST = re.compile(
    r"^(?P<content>.+?),?\s+(?P<cue>according to)\s+(?P<speaker>[^,.]{2,80})\.?$", re.IGNORECASE
)


_TRIM = set(" .,;:\"“”'")


def kind_of(speaker: str) -> str:
    s = _LEAD.sub("", speaker.strip())
    if ANONYMOUS.match(s):
        # "Israeli officials" names a side, not a person: still anonymous for sourcing
        return "anonymous"
    return "named" if _NAME.search(s) else "anonymous"


def _span(m: re.Match[str], g: str) -> tuple[int, int]:
    return m.start(g), m.end(g)


def extract(sentence: str, parser: Any = None) -> dict[str, Any]:
    """Attribution of one sentence. Spans are (start, end) into `sentence`, or None."""
    if parser is not None:
        got = _parse(sentence, parser)
        if got:
            return got
    for pat in (_ACC_FIRST, _ACC_LAST, _FIRST, _LAST, _INV):
        m = pat.match(sentence.strip())
        if not m:
            continue
        lead = len(sentence) - len(sentence.lstrip())
        sp = tuple(x + lead for x in _span(m, "speaker"))
        a, b = (x + lead for x in _span(m, "content"))
        while a < b and sentence[a] in _TRIM:
            a += 1
        while b > a and sentence[b - 1] in _TRIM:
            b -= 1
        ct = (a, b)
        speaker = m.group("speaker")
        if len(speaker.split()) > 10:
            continue
        cue = m.group("cue").lower()
        return {
            "speaker": speaker.strip(),
            "speaker_span": list(sp),
            "cue": cue,
            "content_span": list(ct),
            "speaker_kind": kind_of(speaker),
            "stance": "deny" if cue in DENY else "assert",
        }
    return none(sentence)


def none(sentence: str) -> dict[str, Any]:
    return {
        "speaker": None,
        "speaker_span": None,
        "cue": None,
        "content_span": [0, len(sentence)],
        "speaker_kind": "none",
        "stance": "assert",
    }


def _parse(sentence: str, parser: Any) -> dict[str, Any] | None:
    doc = parser(sentence)
    for tok in doc:
        if (
            tok.lemma_.lower() == "accord"
            and tok.i + 1 < len(doc)
            and doc[tok.i + 1].lower_ == "to"
        ):
            obj = [c for c in doc[tok.i + 1].children if c.dep_ == "pobj"]
            if obj:
                sp = obj[0]
                speaker = doc[sp.left_edge.i : sp.right_edge.i + 1]
                rest_start = speaker.end_char
                head = tok.head
                content = doc[head.left_edge.i : head.right_edge.i + 1]
                return _out(sentence, speaker, "according to", content, rest_start)
        if tok.lemma_.lower() not in LEMMAS or tok.pos_ not in ("VERB", "AUX"):
            continue
        subj = [c for c in tok.children if c.dep_ in ("nsubj", "nsubjpass")]
        comp = [c for c in tok.children if c.dep_ in ("ccomp", "xcomp", "dobj", "parataxis")]
        if not subj or not comp:
            # "Y, X said": the content is the head clause and the cue is its parataxis/ccomp
            if subj and tok.dep_ in ("parataxis", "ccomp") and tok.head is not tok:
                h = tok.head
                content = doc[h.left_edge.i : tok.left_edge.i]
                s = subj[0]
                return _out(sentence, doc[s.left_edge.i : s.right_edge.i + 1], tok.lower_, content)
            continue
        s, c = subj[0], comp[0]
        return _out(
            sentence,
            doc[s.left_edge.i : s.right_edge.i + 1],
            tok.lower_,
            doc[c.left_edge.i : c.right_edge.i + 1],
        )
    return None


def _out(sentence: str, speaker: Any, cue: str, content: Any, _: int = 0) -> dict[str, Any] | None:
    text = content.text.strip(" ,.;:")
    if not text:
        return None
    start = sentence.find(text, content.start_char)
    return {
        "speaker": speaker.text,
        "speaker_span": [speaker.start_char, speaker.end_char],
        "cue": cue,
        "content_span": [start, start + len(text)],
        "speaker_kind": kind_of(speaker.text),
        "stance": "deny" if cue in DENY else "assert",
    }


def normalise(speaker: str | None) -> str:
    """Speaker key for counting: lower case, without leading articles, titles and possessives."""
    if not speaker:
        return ""
    s = _LEAD.sub("", speaker.strip()).lower()
    s = re.sub(r"^(?:the|a|an)\s+", "", s)
    s = re.sub(
        r"\b(?:mr|ms|mrs|dr|prime minister|president|minister|spokesman|spokeswoman)\b\.?", "", s
    )
    return re.sub(r"\s+", " ", s.replace("’s", "'s")).strip(" ,")
