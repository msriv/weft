"""The anomaly rules engine (rule 2): deterministic code reading config/rules.yaml.

Every function here is pure: inputs in, anomalies out. No model is called. Models only supplied
the claim groups and figures that arrive as inputs. Each anomaly records its rule name, the rule
version, the thresholds it used, and the ids of the evidence. Summaries use coverage language only
(rule 1): they say what reports contain and omit, never what is true.
"""

import difflib
import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

from weft_core.attribution import normalise
from weft_core.textutil import jaccard, sentences, shingles, words

WIRES = (
    "reuters",
    "associated press",
    "ap",
    "afp",
    "pti",
    "press trust of india",
    "ani",
    "ians",
    "xinhua",
    "tass",
    "bloomberg",
)
CORRECTION = re.compile(
    r"\b(correction|corrected|clarification|editor'?s note|this article was updated)\b",
    re.IGNORECASE,
)
ATTRIBUTION = re.compile(
    r"\b(said|says|told|stated|according to|announced|confirmed|denied|reported by|spokes\w+|"
    r"ministry|minister|official|officials|statement)\b|[“\"]",
    re.IGNORECASE,
)


# stricter, for the "names sources" weight: a speech verb or phrase, or a quote. Nouns such as
# "minister" or "statement" alone appear in nearly every political sentence.
NAMES_SOURCE = re.compile(
    r"\b(said|says|told|stated|according to|announced|denied|reported by)\b|[“\"]",
    re.IGNORECASE,
)


def is_attributed(sentence: str) -> bool:
    """A claim sentence names a source: an attribution verb or phrase, a body, or a quote."""
    return bool(ATTRIBUTION.search(sentence))


@dataclass
class Rep:
    id: str
    source_id: str
    source_name: str
    perspective: str
    published_at: datetime
    owner_id: str | None = None
    paywalled: bool = False
    healthy: bool = True
    type: str = "news"
    text: str = ""
    origin_id: str = ""  # independent-text cluster (#98); empty means its own origin
    claims_extracted: bool = True  # False: claim extraction never read it (#106)
    correction_note: str = ""

    @property
    def origin(self) -> str:
        return self.origin_id or self.id


def hypergeom_zero(n_total: int, k_carriers: int, n_draw: int) -> float:
    """P(no carrier among n_draw drawn from n_total holding k_carriers): how surprising it is
    that a perspective with n_draw origins carries none of a group K origins carry."""
    if n_draw > n_total - k_carriers:
        return 0.0
    return math.comb(n_total - k_carriers, n_draw) / math.comb(n_total, n_draw)


@dataclass
class Group:
    id: str
    label: str
    report_ids: set[str]
    # {report_id, text}, plus speaker, speaker_kind and stance when attribution ran (#101)
    claims: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Figure:
    id: str
    report_id: str
    quantity: str
    value: float
    text: str
    group: str | None = None  # claim group of the sentence the figure sits in
    hedge: str | None = None  # at_least / at_most / about (#103)

    @property
    def interval(self) -> tuple[float, float]:
        """ "at least 40" is [40, inf), "up to 40" is [0, 40], "about 40" is 40 plus or minus 10%."""
        v = self.value
        return {
            "at_least": (v, math.inf),
            "at_most": (0.0, v),
            "about": (v * 0.9, v * 1.1),
        }.get(self.hedge or "", (v, v))


@dataclass
class EventInput:
    id: str
    story_id: str
    first_seen: datetime
    reports: list[Rep]
    groups: list[Group]
    figures: list[Figure]
    conflicts: list[tuple[str, str, float]] = field(default_factory=list)  # group a, b, NLI
    parties: list[str] = field(default_factory=list)  # names of the story's parties (rule 7)
    # quote / official statement pairs (#108): figure_id, report_id, text, speaker, statement_id,
    # statement, actor, issuer, edit_ratio
    quotes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Edit:
    report: Rep
    versions: list[tuple[datetime, str]]  # (fetched_at, extracted text), oldest first


@dataclass
class Anomaly:
    rule: str
    rule_version: int
    subject_kind: str
    subject_id: str
    story_id: str
    event_id: str | None
    summary: str
    inputs: dict[str, Any]
    evidence_ids: list[str]
    detail: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    key: str = ""  # tells apart anomalies on one subject: omission's perspective, an edit's time

    @property
    def id(self) -> str:
        key = f"{self.rule}:{self.subject_kind}:{self.subject_id}:{self.event_id}"
        if self.key:
            key += f":{self.key}"
        return hashlib.sha256(key.encode()).hexdigest()[:32]


def _a(rule: str, cfg: dict[str, Any], **kw: Any) -> Anomaly:
    return Anomaly(rule=rule, rule_version=cfg["version"], **kw)


def fisher_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for [[a, b], [c, d]]: the sum of tables at most as likely."""
    r1, r2, c1, n = a + b, c + d, a + c, a + b + c + d

    def p(x: int) -> float:
        return math.comb(r1, x) * math.comb(r2, c1 - x) / math.comb(n, c1)

    obs = p(a)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs * (1 + 1e-9)))


def _eligible(reps: list[Rep], skip_paywalled: bool) -> list[Rep]:
    return [r for r in reps if not (skip_paywalled and r.paywalled)]


def omission(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    """A claim group most independent texts carry, absent from every origin of one perspective,
    where that absence would be unlikely by chance (#100). Counts origins, not reports (#98);
    only reports claim extraction read, with full text, published once the group existed."""
    c = cfg["rules"]["omission"]
    base = [r for r in _eligible(ev.reports, c["exclude_paywalled_sources"]) if r.claims_extracted]
    out = []
    for g in ev.groups:
        carriers = [r for r in base if r.id in g.report_ids]
        if not carriers:
            continue
        since = min(r.published_at for r in carriers)
        reps = [r for r in base if r.published_at >= since]
        origins = {r.origin for r in reps}
        have = {r.origin for r in carriers}
        n, k = len(origins), len(have)
        share = k / n if n else 0.0
        if share < c["min_share_of_event_reports"]:
            continue
        persp: dict[str, list[Rep]] = defaultdict(list)
        for r in reps:
            if r.perspective != "unattributed":
                persp[r.perspective].append(r)
        for p, prs in sorted(persp.items()):
            if any(r.id in g.report_ids for r in prs):
                continue
            n_p = len({r.origin for r in prs})
            n_src = len({r.source_id for r in prs})
            pval = hypergeom_zero(n, k, n_p)
            if n_p < c["min_perspective_origins"] or n_src < c["min_perspective_sources"]:
                continue
            if pval > c["max_p_value"]:
                continue
            out.append(
                _a(
                    "omission",
                    cfg,
                    subject_kind="claim_group",
                    subject_id=g.id,
                    story_id=ev.story_id,
                    event_id=ev.id,
                    summary=f"{k} of {n} independent texts ({share:.0%}) carry this claim group; "
                    f"none of the {n_p} from {p} do.",
                    inputs={
                        "threshold": c["min_share_of_event_reports"],
                        "share": share,
                        "perspective": p,
                        "N": n,
                        "K": k,
                        "n_p": n_p,
                        "p": pval,
                        "origins": sorted(have),
                    },
                    evidence_ids=sorted(r.id for r in carriers) + [r.id for r in prs],
                    key=p,
                    detail={
                        "label": g.label,
                        "carrying": sorted(r.id for r in carriers),
                        "perspective_reports": [r.id for r in prs],
                    },
                )
            )
    return out


def _disjoint(a: Figure, b: Figure) -> bool:
    (a0, a1), (b0, b1) = a.interval, b.interval
    return a1 < b0 or b1 < a0


def numbers_differ(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    """Figures for the same quantity inside one claim group, so "12 people killed" is never
    compared with "300 people evacuated" (#103). Hedges are intervals: "at least 40" and "52"
    agree. Only reports from different origins within `max_hours_apart` are compared, since
    tolls rise over time. Figures outside any group, and years, are skipped."""
    c = cfg["rules"]["numbers_differ"]
    reps = {r.id: r for r in ev.reports}
    min_log = c.get("min_log_ratio", -math.log(1 - c.get("min_relative_difference", 0.2)))
    gap = timedelta(hours=c.get("max_hours_apart", 6))
    by_q: dict[tuple[str, str], list[Figure]] = defaultdict(list)
    for f in ev.figures:
        if (
            f.group
            and f.report_id in reps
            and not (1900 <= f.value <= 2100 and f.value.is_integer())
        ):
            by_q[(f.group, f.quantity)].append(f)
    out = []
    for (g, q), fs in sorted(by_q.items()):
        best: tuple[float, Figure, Figure] | None = None
        for x in range(len(fs)):
            for y in range(x + 1, len(fs)):
                a, b = sorted((fs[x], fs[y]), key=lambda f: f.value)
                ra, rb = reps[a.report_id], reps[b.report_id]
                if ra.origin == rb.origin or abs(ra.published_at - rb.published_at) > gap:
                    continue
                if a.value <= 0 or not _disjoint(a, b):
                    continue
                ratio = math.log(b.value / a.value)
                if ratio >= min_log and (best is None or ratio > best[0]):
                    best = (ratio, a, b)
        if best is None:
            continue
        ratio, lo, hi = best
        diff = (hi.value - lo.value) / hi.value
        out.append(
            _a(
                "numbers_differ",
                cfg,
                subject_kind="quantity",
                subject_id=f"{g}:{q}",
                story_id=ev.story_id,
                event_id=ev.id,
                summary=f"Reports of this event give different figures for '{q}': "
                f"{lo.value:g} and {hi.value:g} ({diff:.0%} apart).",
                inputs={
                    "min_log_ratio": min_log,
                    "max_hours_apart": gap.total_seconds() / 3600,
                    "log_ratio": ratio,
                    "difference": diff,
                    "claim_group": g,
                    "hedges": [lo.hedge, hi.hedge],
                },
                evidence_ids=[lo.id, hi.id],
                detail={
                    "figures": [
                        {"id": f.id, "report_id": f.report_id, "value": f.value, "text": f.text}
                        for f in (lo, hi)
                    ]
                },
            )
        )
    return out


def figure_revised(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    """One outlet gives a figure for a claim group, then a later report of its own gives a value
    outside the first one's interval, and the later report carries no correction note (#103)."""
    reps = {r.id: r for r in ev.reports}
    by_key: dict[tuple[str, str, str], list[Figure]] = defaultdict(list)
    for f in ev.figures:
        if f.group and f.report_id in reps:
            by_key[(reps[f.report_id].source_id, f.group, f.quantity)].append(f)
    out = []
    for (src, g, q), fs in sorted(by_key.items()):
        fs = sorted(fs, key=lambda f: (reps[f.report_id].published_at, f.id))
        for a, b in pairwise(fs):
            ra, rb = reps[a.report_id], reps[b.report_id]
            if ra.id == rb.id or not _disjoint(a, b):
                continue
            if rb.correction_note or CORRECTION.search(rb.text):
                continue
            out.append(
                _a(
                    "figure_revised",
                    cfg,
                    subject_kind="quantity",
                    subject_id=f"{g}:{q}",
                    story_id=ev.story_id,
                    event_id=ev.id,
                    summary=f"{rb.source_name} gave {a.value:g} for '{q}', then {b.value:g} in a "
                    "later report, with no correction note.",
                    inputs={"claim_group": g, "source_id": src},
                    evidence_ids=[a.id, b.id],
                    detail={
                        "figures": [
                            {"id": f.id, "report_id": f.report_id, "value": f.value, "text": f.text}
                            for f in (a, b)
                        ]
                    },
                    key=src,
                )
            )
            break
    return out


def credits(r: Rep, others: list[Rep]) -> bool:
    """The report's text credits a wire or another outlet in the cluster."""
    low = r.text.lower()
    names = [o.source_name.lower() for o in others if o.source_id != r.source_id]
    return any(re.search(rf"\b{re.escape(n)}\b", low) for n in (*WIRES, *names) if n)


def copied_text(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    c = cfg["rules"]["copied_text"]
    reps = [r for r in ev.reports if r.text]
    sh = {r.id: shingles(r.text, c["shingle_words"]) for r in reps}
    window = timedelta(hours=c["window_hours"])
    parent = {r.id: r.id for r in reps}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(reps):
        for b in reps[i + 1 :]:
            if (
                a.source_id != b.source_id
                and abs(a.published_at - b.published_at) <= window
                and jaccard(sh[a.id], sh[b.id]) >= c["min_jaccard"]
            ):
                parent[find(a.id)] = find(b.id)
    clusters: dict[str, list[Rep]] = defaultdict(list)
    for r in reps:
        clusters[find(r.id)].append(r)
    out = []
    for members in clusters.values():
        if c["ignore_credited_wire_copy"]:
            members = [m for m in members if not credits(m, members)]
        if c["require_different_owners"]:
            seen: set[str] = set()
            uniq = []
            for m in members:  # unknown owner never proves a shared owner
                if m.owner_id is None or m.owner_id not in seen:
                    uniq.append(m)
                    seen.add(m.owner_id or "")
            members = uniq
        outlets = {m.source_id for m in members}
        if len(outlets) < c["min_outlets"]:
            continue
        ordered = sorted(members, key=lambda m: m.published_at)
        out.append(
            _a(
                "copied_text",
                cfg,
                subject_kind="reports",
                subject_id=ordered[0].id,
                story_id=ev.story_id,
                event_id=ev.id,
                summary=f"{len(outlets)} outlets published near-identical text within "
                f"{c['window_hours']} hours, without crediting each other.",
                inputs={"min_jaccard": c["min_jaccard"], "min_outlets": c["min_outlets"]},
                evidence_ids=[m.id for m in ordered],
                detail={"published": {m.id: m.published_at.isoformat() for m in ordered}},
            )
        )
    return out


def silence(story_id: str, reports: list[Rep], now: datetime, cfg: dict[str, Any]) -> list[Anomaly]:
    c = cfg["rules"]["silence"]
    quiet = timedelta(hours=c["outlet_quiet_hours"])
    recent = [r for r in reports if now - quiet < r.published_at <= now]
    prior = [r for r in reports if now - 2 * quiet < r.published_at <= now - quiet]
    if len(prior) < c.get("min_prior_reports", 0):
        return []  # too little coverage to call any outlet's absence notable
    change = abs(len(recent) - len(prior)) / len(prior)
    if change > c["story_coverage_within"]:
        return []  # the story itself went quiet or surged: a quiet outlet is not notable
    active = {r.source_id for r in recent}
    out = []
    by_source: dict[str, list[Rep]] = defaultdict(list)
    for r in reports:
        by_source[r.source_id].append(r)
    for sid, rs in sorted(by_source.items()):
        if sid in active or (c["skip_unhealthy_feeds"] and not rs[0].healthy):
            continue
        before = [r for r in rs if now - 2 * quiet < r.published_at <= now - quiet]
        if len(before) < max(1, c.get("min_outlet_reports", 1)):
            continue  # not covering the story steadily before the quiet window
        out.append(
            _a(
                "silence",
                cfg,
                subject_kind="source",
                subject_id=sid,
                story_id=story_id,
                event_id=None,
                summary=f"Weft holds no report from {rs[0].source_name} on this story in the "
                f"last {c['outlet_quiet_hours']} hours ({len(before)} before), while the "
                f"story's coverage held ({len(recent)} reports now, {len(prior)} before).",
                inputs={
                    "quiet_hours": c["outlet_quiet_hours"],
                    "recent": len(recent),
                    "prior": len(prior),
                },
                evidence_ids=[r.id for r in rs[-3:]],
                detail={"source": sid, "recent_reports": len(recent), "prior_reports": len(prior)},
            )
        )
    return out


LIVE = re.compile(
    r"\blive( updates| blog)?\b|\bupdated?\b:?\s*\d|\bdeveloping story\b", re.IGNORECASE
)
# a sentence with a number or an attributed statement: what a silent edit would matter for
SUBSTANTIVE = re.compile(
    r"\d|[\"“”]|\b(said|says|told|according to|announced|denied|claimed|confirmed)\b", re.IGNORECASE
)


def silent_edit(edits: list[Edit], cfg: dict[str, Any]) -> list[Anomaly]:
    c = cfg["rules"]["silent_edit"]
    out = []
    for e in edits:
        for (t0, a), (t1, b) in zip(e.versions, e.versions[1:], strict=False):
            if " ".join(a.split()) == " ".join(b.split()) or CORRECTION.search(b):
                continue
            if LIVE.search(a[:400]) or LIVE.search(b[:400]):
                continue  # live blogs and "updated" stories change by design
            sa = [a[s:x] for s, x in sentences(a)]
            sb = [b[s:x] for s, x in sentences(b)]
            d = [
                ln
                for ln in difflib.unified_diff(sa, sb, lineterm="", n=0)
                if ln[:1] in "+-" and ln[:3] not in ("+++", "---")
            ]
            removed = [ln[1:] for ln in d if ln[:1] == "-"]
            if not any(SUBSTANTIVE.search(ln) for ln in removed):
                continue  # only sentences carrying a figure or an attributed claim count
            out.append(
                _a(
                    "silent_edit",
                    cfg,
                    subject_kind="report",
                    subject_id=e.report.id,
                    story_id="",
                    event_id=None,
                    summary=f"The text of this report changed between {t0:%Y-%m-%d %H:%M} and "
                    f"{t1:%Y-%m-%d %H:%M}, with no correction note on the page.",
                    inputs={"refetch_after": c["refetch_after"]},
                    evidence_ids=[e.report.id],
                    key=t1.isoformat(),
                    detail={"from": t0.isoformat(), "to": t1.isoformat(), "diff": d[:40]},
                )
            )
    return out


# --- v2 rules, disabled in config until tuned -------------------------------------------------


def log_odds(
    a: Counter[str], rest: Counter[str], prior: Counter[str] | None = None, alpha0: float = 500.0
) -> dict[str, float]:
    """Weighted log-odds with an informative Dirichlet prior (Monroe et al., "Fightin' Words").
    Returns a z-score per term for group `a` against `rest`."""
    prior = prior or (a + rest)
    n0 = sum(prior.values()) or 1
    alpha0 = min(alpha0, n0 / 2)  # a tiny corpus must not be swamped by the prior
    na, nb = sum(a.values()), sum(rest.values())
    out = {}
    for w in a:
        aw = alpha0 * prior[w] / n0
        la = math.log((a[w] + aw) / max(na + alpha0 - a[w] - aw, 1e-6))
        lb = math.log((rest[w] + aw) / max(nb + alpha0 - rest[w] - aw, 1e-6))
        var = 1 / (a[w] + aw) + 1 / (rest[w] + aw)
        out[w] = (la - lb) / math.sqrt(var)
    return out


def loaded_wording(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    c = cfg["rules"]["loaded_wording"]
    reps = _eligible(ev.reports, c["exclude_paywalled_sources"])
    by_p: dict[str, Counter[str]] = defaultdict(Counter)
    for r in reps:
        by_p[r.perspective].update(words(r.text))
    out = []
    for p, counts in sorted(by_p.items()):
        rest: Counter[str] = Counter()
        for q, qc in by_p.items():
            if q != p:
                rest.update(qc)
        if not rest:
            continue
        for term, z in sorted(log_odds(counts, rest).items()):
            if z >= c["min_weighted_log_odds"] and len(term) > 3 and counts[term] >= 2:
                out.append(
                    _a(
                        "loaded_wording",
                        cfg,
                        subject_kind="term",
                        subject_id=f"{p}:{term}",
                        story_id=ev.story_id,
                        event_id=ev.id,
                        summary=f"Reports from {p} use '{term}' {counts[term]} times against "
                        f"{rest[term]} in other reports of this event.",
                        inputs={"min_weighted_log_odds": c["min_weighted_log_odds"], "z": z},
                        evidence_ids=[r.id for r in reps if r.perspective == p],
                        detail={
                            "term": term,
                            "perspective": p,
                            "counts": counts[term],
                            "others": rest[term],
                        },
                    )
                )
    return out


def _named_or_attributed(claim: dict[str, Any]) -> bool:
    kind = claim.get("speaker_kind")
    return kind != "none" if kind else is_attributed(claim["text"])


def _origins_by(ev: EventInput, g: Group) -> dict[str, list[dict[str, Any]]]:
    """A claim group's claims keyed by the independent origin of their report."""
    reps = {r.id: r for r in ev.reports}
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for x in g.claims:
        if x["report_id"] in reps:
            out[reps[x["report_id"]].origin].append(x)
    return out


def anonymous_sourcing(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    """Independent reports name who said a claim, while others cite only unnamed sources (#101)."""
    c = cfg["rules"]["anonymous_sourcing"]
    out = []
    for g in ev.groups:
        by_o = _origins_by(ev, g)
        named = [o for o, xs in by_o.items() if any(x.get("speaker_kind") == "named" for x in xs)]
        anon = [
            o
            for o, xs in by_o.items()
            if o not in named and any(x.get("speaker_kind") == "anonymous" for x in xs)
        ]
        if len(named) >= c["min_named_origins"] and len(anon) >= c["min_anonymous_origins"]:
            ids = [x["report_id"] for o in named + anon for x in by_o[o]]
            out.append(
                _a(
                    "anonymous_sourcing",
                    cfg,
                    subject_kind="claim_group",
                    subject_id=g.id,
                    story_id=ev.story_id,
                    event_id=ev.id,
                    summary=f"{len(named)} independent reports name who said this; "
                    f"{len(anon)} cite only unnamed sources.",
                    inputs={k: c[k] for k in ("min_named_origins", "min_anonymous_origins")}
                    | {"named_origins": len(named), "anonymous_origins": len(anon)},
                    evidence_ids=sorted(set(ids)),
                    detail={"label": g.label},
                )
            )
    return out


def single_origin(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    """A claim carried by many independent reports that nearly all attribute it to one speaker
    (#102). Repetition is not corroboration; the summary says who the speaker is and whether
    they are a party to the story (rule 7), and nothing about truth (rule 1)."""
    c = cfg["rules"]["single_origin"]
    out = []
    for g in ev.groups:
        by_o = _origins_by(ev, g)
        if len(by_o) < c["min_origins"]:
            continue
        speakers: Counter[str] = Counter()
        shown: dict[str, str] = {}
        for xs in by_o.values():
            keys = {normalise(x.get("speaker")) for x in xs if x.get("speaker")} - {""}
            for k in keys:
                speakers[k] += 1
                shown.setdefault(
                    k, next(x["speaker"] for x in xs if normalise(x.get("speaker")) == k)
                )
        if not speakers:
            continue
        top, n = speakers.most_common(1)[0]
        share = n / len(by_o)
        if share < c["min_share"]:
            continue
        party = next((p for p in ev.parties if p and p.lower() in top), None)
        who = shown[top] + (", a party to this story" if party else "")
        out.append(
            _a(
                "single_origin",
                cfg,
                subject_kind="claim_group",
                subject_id=g.id,
                story_id=ev.story_id,
                event_id=ev.id,
                summary=f"{len(by_o)} independent reports carry this; {n} attribute it to {who}.",
                inputs={
                    "min_origins": c["min_origins"],
                    "min_share": c["min_share"],
                    "origins": len(by_o),
                    "share": share,
                    "speaker": top,
                    "party": party,
                },
                evidence_ids=sorted({x["report_id"] for xs in by_o.values() for x in xs}),
                detail={"label": g.label, "speaker": shown[top], "party": party},
            )
        )
    return out


def conflicting_accounts(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    """Two claim groups the NLI input marks as contradicting (#99), each carried by enough
    independent texts, with different sets of perspectives behind each side. Fisher's exact p of
    perspective against side is stored as an input, never used to filter."""
    c = cfg["rules"]["conflicting_accounts"]
    groups = {g.id: g for g in ev.groups}
    persp = {r.id: r.perspective for r in ev.reports}
    out = []
    for ga, gb, score in ev.conflicts:
        a, b = groups.get(ga), groups.get(gb)
        if a is None or b is None:
            continue
        oa, ob = _origins_by(ev, a), _origins_by(ev, b)
        if len(oa) < c["min_origins_per_side"] or len(ob) < c["min_origins_per_side"]:
            continue
        pa = {persp[x["report_id"]] for xs in oa.values() for x in xs} - {"unattributed"}
        pb = {persp[x["report_id"]] for xs in ob.values() for x in xs} - {"unattributed"}
        if pa == pb:
            continue

        def count(o: dict[str, list[dict[str, Any]]], p: str) -> int:
            return sum(1 for xs in o.values() if any(persp[x["report_id"]] == p for x in xs))

        fisher = {
            p: fisher_2x2(
                count(oa, p), len(oa) - count(oa, p), count(ob, p), len(ob) - count(ob, p)
            )
            for p in sorted(pa | pb)
        }
        out.append(
            _a(
                "conflicting_accounts",
                cfg,
                subject_kind="conflict",
                subject_id=f"{ga}|{gb}",
                story_id=ev.story_id,
                event_id=ev.id,
                summary=f"Reports conflict on: “{a.label[:160]}” versus “{b.label[:160]}”.",
                inputs={
                    "min_origins_per_side": c["min_origins_per_side"],
                    "nli": score,
                    "origins": [len(oa), len(ob)],
                    "fisher_p": fisher,
                },
                evidence_ids=sorted(
                    {x["report_id"] for o in (oa, ob) for xs in o.values() for x in xs}
                ),
                detail={
                    "sides": [
                        {"label": a.label, "perspectives": sorted(pa)},
                        {"label": b.label, "perspectives": sorted(pb)},
                    ]
                },
            )
        )
    return out


def _same_person(a: str | None, b: str | None) -> bool:
    """Speaker names match when one's last word appears in the other ("Voss", "Arlen Voss")."""
    x, y = normalise(a).split(), normalise(b).split()
    return bool(x and y) and (x[-1] in y or y[-1] in x)


def quote_differs(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    """A report quotes a speaker, an official document of the story records the same speaker,
    and the quote's words differ from the issued text by a share inside the band (#108). Below
    the band is a faithful quote; above it is probably another passage. The summary names the
    issuer of the text (rule 7) and says nothing about which wording is right (rule 1)."""
    c = cfg["rules"]["quote_differs"]
    lo, hi = c["min_edit_ratio"], c["max_edit_ratio"]
    out = []
    for q in ev.quotes:
        if not _same_person(q.get("speaker"), q.get("actor")):
            continue
        if not lo <= q["edit_ratio"] <= hi:
            continue
        out.append(
            _a(
                "quote_differs",
                cfg,
                subject_kind="quote",
                subject_id=q["figure_id"],
                story_id=ev.story_id,
                event_id=ev.id,
                summary=f"This quote of {q['actor']} differs from the text issued by "
                f"{q['issuer']} ({q['edit_ratio']:.0%} of words differ).",
                inputs={"min_edit_ratio": lo, "max_edit_ratio": hi, "edit_ratio": q["edit_ratio"]},
                evidence_ids=[q["report_id"], q["statement_id"]],
                detail={"quote": q["text"], "statement": q["statement"], "issuer": q["issuer"]},
                key=q["statement_id"],
            )
        )
    return out


def unattributed(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    c = cfg["rules"]["unattributed"]
    out = []
    for g in ev.groups:
        att = [x for x in g.claims if _named_or_attributed(x)]
        bare = [x for x in g.claims if not _named_or_attributed(x)]
        if bare and len(att) >= c["min_attributed_versions"]:
            out.append(
                _a(
                    "unattributed",
                    cfg,
                    subject_kind="claim_group",
                    subject_id=g.id,
                    story_id=ev.story_id,
                    event_id=ev.id,
                    summary=f"{len(bare)} report(s) state this claim without naming a source, "
                    f"while {len(att)} other reports of it name one.",
                    inputs={"min_attributed_versions": c["min_attributed_versions"]},
                    evidence_ids=[x["report_id"] for x in bare + att],
                    detail={"label": g.label, "bare": bare, "attributed": att},
                )
            )
    return out


EVENT_RULES = {
    "omission": omission,
    "numbers_differ": numbers_differ,
    "copied_text": copied_text,
    "loaded_wording": loaded_wording,
    "unattributed": unattributed,
    "figure_revised": figure_revised,
    "anonymous_sourcing": anonymous_sourcing,
    "single_origin": single_origin,
    "conflicting_accounts": conflicting_accounts,
    "quote_differs": quote_differs,
}


def evaluate_event(ev: EventInput, cfg: dict[str, Any], now: datetime) -> list[Anomaly]:
    """All enabled per-event rules, each marked provisional or active (D9)."""
    p = cfg["provisional"]
    sources = {r.source_id for r in ev.reports}
    persp = {r.perspective for r in ev.reports if r.perspective != "unattributed"}
    provisional = (
        len(sources) < p["min_sources"]
        or len(persp) < p["min_perspectives"]
        or now - ev.first_seen < timedelta(hours=p["min_hours_since_first_report"])
    )
    out = []
    for name, fn in EVENT_RULES.items():
        if cfg["rules"][name]["enabled"]:
            for a in fn(ev, cfg):
                a.status = "provisional" if provisional else "active"
                out.append(a)
    return out
