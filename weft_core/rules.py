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
from typing import Any

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


@dataclass
class Group:
    id: str
    label: str
    report_ids: set[str]
    claims: list[dict[str, Any]] = field(default_factory=list)  # {report_id, text}


@dataclass
class Figure:
    id: str
    report_id: str
    quantity: str
    value: float
    text: str
    group: str | None = None  # claim group of the sentence the figure sits in


@dataclass
class EventInput:
    id: str
    story_id: str
    first_seen: datetime
    reports: list[Rep]
    groups: list[Group]
    figures: list[Figure]


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


def _eligible(reps: list[Rep], skip_paywalled: bool) -> list[Rep]:
    return [r for r in reps if not (skip_paywalled and r.paywalled)]


def omission(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    c = cfg["rules"]["omission"]
    reps = _eligible(ev.reports, c["exclude_paywalled_sources"])
    ids = {r.id for r in reps}
    persp: dict[str, list[Rep]] = defaultdict(list)
    for r in reps:
        if r.perspective != "unattributed":
            persp[r.perspective].append(r)
    out = []
    for g in ev.groups:
        have = g.report_ids & ids
        share = len(have) / len(ids) if ids else 0.0
        if share < c["min_share_of_event_reports"]:
            continue
        for p, prs in sorted(persp.items()):
            if c["absent_from_whole_perspective"] and not any(r.id in have for r in prs):
                out.append(
                    _a(
                        "omission",
                        cfg,
                        subject_kind="claim_group",
                        subject_id=g.id,
                        story_id=ev.story_id,
                        event_id=ev.id,
                        summary=f"{len(have)} of {len(ids)} reports ({share:.0%}) carry this claim "
                        f"group; none of the {len(prs)} reports from {p} do.",
                        inputs={
                            "threshold": c["min_share_of_event_reports"],
                            "share": share,
                            "perspective": p,
                        },
                        evidence_ids=sorted(have) + [r.id for r in prs],
                        key=p,
                        detail={
                            "label": g.label,
                            "carrying": sorted(have),
                            "perspective_reports": [r.id for r in prs],
                        },
                    )
                )
    return out


def numbers_differ(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    """Figures for the same quantity inside one claim group, so "12 people killed" is never
    compared with "300 people evacuated". Figures outside any group, and years, are skipped."""
    c = cfg["rules"]["numbers_differ"]
    by_q: dict[tuple[str, str], list[Figure]] = defaultdict(list)
    for f in ev.figures:
        if f.group and not (1900 <= f.value <= 2100 and f.value.is_integer()):
            by_q[(f.group, f.quantity)].append(f)
    out = []
    for (g, q), fs in sorted(by_q.items()):
        lo, hi = min(fs, key=lambda f: f.value), max(fs, key=lambda f: f.value)
        if lo.report_id == hi.report_id or hi.value <= 0:
            continue
        diff = (hi.value - lo.value) / hi.value
        if diff > c["min_relative_difference"]:
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
                        "threshold": c["min_relative_difference"],
                        "difference": diff,
                        "claim_group": g,
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


def unattributed(ev: EventInput, cfg: dict[str, Any]) -> list[Anomaly]:
    c = cfg["rules"]["unattributed"]
    out = []
    for g in ev.groups:
        att = [x for x in g.claims if is_attributed(x["text"])]
        bare = [x for x in g.claims if not is_attributed(x["text"])]
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
