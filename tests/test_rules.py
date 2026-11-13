"""One test per rule, plus every suppression case in the spec (unhealthy feeds, paywalled
sources, credited wire copy). Anomalies are deterministic: same input, same output."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from weft_core import config, rules, weights
from weft_core.rules import Edit, EventInput, Figure, Group, Rep

CFG = config.rules()
T0 = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
NOW = T0 + timedelta(days=10)


def rep(i: str, persp: str = "IL", src: str | None = None, hours: float = 0, **kw: Any) -> Rep:
    return Rep(
        id=i,
        source_id=src or f"s{i}",
        source_name=f"Outlet {src or i}",
        perspective=persp,
        published_at=T0 + timedelta(hours=hours),
        **kw,
    )


def event(
    reps: list[Rep], groups: list[Group] | None = None, figures: list[Figure] | None = None
) -> EventInput:
    return EventInput("e", "st", T0, reps, groups or [], figures or [])


def test_omission_fires_when_a_whole_perspective_lacks_a_common_claim() -> None:
    il = [rep(str(i)) for i in range(9)]
    ir = [rep("a", "IR", "x"), rep("b", "IR", "y"), rep("c", "IR", "y")]
    g = Group("g", "claim", {r.id for r in il})
    (a,) = rules.omission(event(il + ir, [g]), CFG)  # 9 of 12 origins; none of IR's 3
    assert a.rule == "omission" and a.rule_version == CFG["version"]
    assert a.inputs["perspective"] == "IR" and a.inputs["p"] < 0.05
    assert (a.inputs["N"], a.inputs["K"], a.inputs["n_p"]) == (12, 9, 3)
    assert set(a.evidence_ids) >= {"0", "a", "b", "c"}
    assert "true" not in a.summary.lower()  # coverage language only
    assert rules.omission(event(il + ir[:2], [g]), CFG) == [], "2 IR texts: too few to mean much"
    unread = [rep("a", "IR", "x"), rep("b", "IR", "y"), rep("c", "IR", "y", claims_extracted=False)]
    assert rules.omission(event(il + unread, [g]), CFG) == [], "an unread report is not silence"
    wire = [rep(str(i), origin_id="0") for i in range(9)]  # one text republished 9 times
    assert rules.omission(event(wire + ir, [Group("g", "c", {r.id for r in wire})]), CFG) == []
    assert rules.hypergeom_zero(12, 9, 3) == 1 / 220


def test_omission_below_share_or_present_in_every_perspective_does_not_fire() -> None:
    reps = [rep("1"), rep("2"), rep("3", "IR"), rep("4", "IR"), rep("5", "IR")]
    assert rules.omission(event(reps, [Group("g", "c", {"1", "2"})]), CFG) == []  # 40%
    assert (
        rules.omission(event(reps, [Group("g", "c", {"1", "3", "4"})]), CFG) == []
    )  # both carry it


def test_omission_skips_paywalled_sources() -> None:
    # IR's only reports are paywalled: we cannot see their full text, so they cannot "omit"
    reps = [rep("1"), rep("2"), rep("3"), rep("4", "IR", paywalled=True)]
    assert rules.omission(event(reps, [Group("g", "c", {"1", "2", "3"})]), CFG) == []


def test_numbers_differ() -> None:
    f = [
        Figure("f1", "1", "missile", 40, "40 missiles", "g"),
        Figure("f2", "2", "missile", 25, "25 missiles", "g"),
    ]
    (a,) = rules.numbers_differ(event([rep("1"), rep("2")], figures=f), CFG)
    assert a.evidence_ids == ["f2", "f1"] and a.inputs["difference"] > 0.2
    close = [Figure("f1", "1", "missile", 40, "", "g"), Figure("f2", "2", "missile", 36, "", "g")]
    assert rules.numbers_differ(event([rep("1"), rep("2")], figures=close), CFG) == []  # 10%
    # different claims ("12 people killed" vs "300 people evacuated") are never compared
    apart = [Figure("f1", "1", "people", 12, "", "g1"), Figure("f2", "2", "people", 300, "", "g2")]
    assert rules.numbers_differ(event([rep("1"), rep("2")], figures=apart), CFG) == []
    years = [
        Figure("f1", "1", "election", 2024, "", "g"),
        Figure("f2", "2", "election", 1990, "", "g"),
    ]
    assert rules.numbers_differ(event([rep("1"), rep("2")], figures=years), CFG) == []
    same = [Figure("f1", "1", "missile", 40, "", "g"), Figure("f2", "1", "missile", 10, "", "g")]
    assert rules.numbers_differ(event([rep("1")], figures=same), CFG) == []  # one report only


TEXT = "The ministry announced that the northern port will remain closed to all shipping until further notice following the incident"


def test_copied_text_and_its_suppressions() -> None:
    reps = [rep(str(i), src=f"s{i}", hours=i, text=TEXT) for i in range(3)]
    (a,) = rules.copied_text(event(reps), CFG)
    assert len(a.evidence_ids) == 3
    # credited wire copy is not copied text
    credited = [Rep(**{**r.__dict__, "text": TEXT + " (Reuters)"}) for r in reps]
    assert rules.copied_text(event(credited), CFG) == []
    # same owner: only two distinct owners remain
    owned = [Rep(**{**r.__dict__, "owner_id": "grp"}) for r in reps[:2]] + [reps[2]]
    assert rules.copied_text(event(owned), CFG) == []
    # outside the 12 hour window
    late = [reps[0], reps[1], Rep(**{**reps[2].__dict__, "published_at": T0 + timedelta(hours=30)})]
    assert rules.copied_text(event(late), CFG) == []
    # different text
    other = [
        reps[0],
        reps[1],
        Rep(**{**reps[2].__dict__, "text": "Something else entirely different"}),
    ]
    assert rules.copied_text(event(other), CFG) == []


def silence_reps(quiet_healthy: bool = True, quiet_n: int = 3) -> list[Rep]:
    now = T0
    out = [rep(f"p{i}", src="quiet", hours=-60 + i, healthy=quiet_healthy) for i in range(quiet_n)]
    out += [rep(f"o{i}", src="other", hours=-90 + 3 * i) for i in range(8)]  # prior window
    out += [rep(f"n{i}", src="other", hours=-40 + 3 * i) for i in range(11)]  # recent window
    assert now
    return out


def test_silence_fires_and_is_suppressed_for_unhealthy_feeds() -> None:
    (a,) = rules.silence("st", silence_reps(), T0, CFG)
    assert a.subject_id == "quiet" and a.inputs["recent"] == 11
    assert a.summary.startswith("Weft holds no report from")
    assert rules.silence("st", silence_reps(quiet_healthy=False), T0, CFG) == []


def test_silence_needs_enough_coverage_and_a_steady_outlet() -> None:
    assert rules.silence("st", silence_reps(quiet_n=2), T0, CFG) == []  # outlet below 3
    thin = [r for r in silence_reps() if not r.id.startswith(("o5", "o6", "o7"))]
    assert rules.silence("st", thin, T0, CFG) == []  # prior window below 10


def test_silence_does_not_fire_when_the_story_itself_went_quiet() -> None:
    reps = [r for r in silence_reps() if not r.id.startswith("n")] + [
        rep("n0", src="other", hours=-10)
    ]
    assert rules.silence("st", reps, T0, CFG) == []


def test_silent_edit_and_correction_note() -> None:
    r = rep("1")
    v0, v1 = T0, T0 + timedelta(hours=1)
    edit = Edit(
        r,
        [
            (v0, "The toll was 12 people. Talks continue."),
            (v1, "The toll was 20 people. Talks continue."),
        ],
    )
    (a,) = rules.silent_edit([edit], CFG)
    assert a.detail["diff"] and "20" in " ".join(a.detail["diff"])
    noted = Edit(
        r,
        [
            (v0, "The toll was 12 people."),
            (v1, "The toll was 20 people. Correction: figure updated."),
        ],
    )
    assert rules.silent_edit([noted], CFG) == []
    same = Edit(r, [(v0, "Same text."), (v1, "Same   text.")])
    assert rules.silent_edit([same], CFG) == []
    wording = Edit(r, [(v0, "Talks continue in the city."), (v1, "Talks go on in the city.")])
    assert rules.silent_edit([wording], CFG) == []  # no figure or attributed claim changed
    live = Edit(
        r,
        [
            (v0, "Live updates: the toll was 12 people."),
            (v1, "Live updates: the toll was 20 people."),
        ],
    )
    assert rules.silent_edit([live], CFG) == []


def test_loaded_wording_and_unattributed_are_off_by_default_but_work() -> None:
    assert CFG["rules"]["loaded_wording"]["enabled"] is False
    assert CFG["rules"]["unattributed"]["enabled"] is False
    reps = [
        rep(str(i), "IL", text="the regime strikes regime forces regime today") for i in range(3)
    ]
    reps += [rep(str(i + 9), "IR", text="the army strikes forces today again") for i in range(3)]
    on = {
        **CFG,
        "rules": {
            **CFG["rules"],
            "loaded_wording": {
                **CFG["rules"]["loaded_wording"],
                "enabled": True,
                "min_weighted_log_odds": 1.0,
            },
        },
    }
    terms = {a.detail["term"] for a in rules.loaded_wording(event(reps), on)}
    assert "regime" in terms
    g = Group(
        "g",
        "c",
        {"1", "2", "3"},
        [
            {"report_id": "1", "text": "Troops crossed the river."},
            {"report_id": "2", "text": "The ministry said troops crossed the river."},
            {"report_id": "3", "text": "According to officials, troops crossed the river."},
        ],
    )
    (a,) = rules.unattributed(event([rep("1")], [g]), CFG | {"rules": CFG["rules"]})
    assert a.detail["bare"][0]["report_id"] == "1"
    assert rules.log_odds(Counter({"a": 5}), Counter({"a": 5}))["a"] == 0


def test_provisional_until_enough_sources_perspectives_and_time() -> None:
    reps = [rep("1"), rep("2"), rep("3", "IR")]
    f = [Figure("f1", "1", "m", 40, "", "g"), Figure("f2", "2", "m", 10, "", "g")]
    (a,) = rules.evaluate_event(event(reps, figures=f), CFG, NOW)
    assert a.status == "provisional"  # 3 sources < 5
    many = [rep(str(i), "IL" if i % 2 else "IR") for i in range(1, 7)]
    (b,) = rules.evaluate_event(event(many, figures=f), CFG, NOW)
    assert b.status == "active"
    (c,) = rules.evaluate_event(event(many, figures=f), CFG, T0 + timedelta(hours=2))
    assert c.status == "provisional"  # under 6 hours since first report


def test_same_input_same_anomaly_id() -> None:
    f = [Figure("f1", "1", "m", 40, "", "g"), Figure("f2", "2", "m", 10, "", "g")]
    e = event([rep("1"), rep("2")], figures=f)
    assert rules.numbers_differ(e, CFG)[0].id == rules.numbers_differ(e, CFG)[0].id


def test_weights() -> None:
    good = {
        "names_sources": 0.8,
        "links_documents": None,
        "corrects_openly": 1.0,
        "silent_edits": 0.0,
        "copied_wording": 0.0,
        "opinion_share": 0.2,
    }
    w, insufficient = weights.compute(good, "news", 50, CFG)
    assert not insufficient and 0.9 < w <= 1.0
    bad = {**good, "silent_edits": 1.0, "copied_wording": 1.0}
    assert weights.compute(bad, "news", 50, CFG)[0] < w
    assert weights.compute(good, "blog", 50, CFG)[0] < w  # blogs weighted lower, never hidden
    assert weights.compute(good, "news", 3, CFG) == (CFG["weights"]["neutral"], True)


def test_names_source_needs_a_speech_verb_or_quote() -> None:
    from weft_core.rules import NAMES_SOURCE

    assert not NAMES_SOURCE.search("The minister visited the border on Tuesday.")
    assert NAMES_SOURCE.search("The minister said troops would stay.")
    assert NAMES_SOURCE.search("“We will stay,” the minister told reporters.")


def test_numbers_differ_reads_hedges_as_intervals_and_compares_close_in_time() -> None:
    reps = [rep("1"), rep("2", "IR"), rep("3", "IR", hours=12)]

    def fig(i: str, r: str, v: float, h: str | None = None) -> Figure:
        return Figure(i, r, "missile", v, f"{v:g} missiles", "g", h)

    assert rules.numbers_differ(event(reps, figures=[fig("a", "1", 40), fig("b", "2", 52)]), CFG)
    # "at least 40" and 52 do not disagree
    hedged = [fig("a", "1", 40, "at_least"), fig("b", "2", 52)]
    assert rules.numbers_differ(event(reps, figures=hedged), CFG) == []
    # 12 hours apart: a rising toll, not a disagreement
    assert (
        rules.numbers_differ(event(reps, figures=[fig("a", "1", 40), fig("c", "3", 52)]), CFG) == []
    )
    # one text republished: not two independent figures
    copy = [rep("1"), rep("2", "IR", origin_id="1")]
    assert (
        rules.numbers_differ(event(copy, figures=[fig("a", "1", 40), fig("b", "2", 52)]), CFG) == []
    )
    lo, hi = Figure("x", "1", "q", 100, "", None, "about").interval
    assert round(lo) == 90 and round(hi) == 110


def test_figure_revised_needs_a_later_report_from_the_same_outlet_without_correction() -> None:
    reps = [rep("1", src="o"), rep("2", src="o", hours=3)]
    figs = [
        Figure("a", "1", "dead", 12, "12 dead", "g"),
        Figure("b", "2", "dead", 30, "30 dead", "g"),
    ]
    (a,) = rules.figure_revised(event(reps, figures=figs), CFG)
    assert a.evidence_ids == ["a", "b"] and "no correction note" in a.summary
    noted = [rep("1", src="o"), rep("2", src="o", hours=3, correction_note="Updated toll.")]
    assert rules.figure_revised(event(noted, figures=figs), CFG) == []
    others = [rep("1", src="o"), rep("2", src="p", hours=3)]
    assert rules.figure_revised(event(others, figures=figs), CFG) == []


def claim(r: str, speaker: str | None, kind: str) -> dict[str, Any]:
    return {"report_id": r, "text": "t", "speaker": speaker, "speaker_kind": kind}


def test_anonymous_sourcing_and_unattributed_read_attribution_spans() -> None:
    reps = [rep("1"), rep("2"), rep("3", "IR")]
    g = Group(
        "g",
        "40 missiles were launched",
        {"1", "2", "3"},
        [
            claim("1", "Aldoria's army", "named"),
            claim("2", "Gen. Voss", "named"),
            claim("3", "officials", "anonymous"),
        ],
    )
    (a,) = rules.anonymous_sourcing(event(reps, [g]), CFG)
    assert a.inputs["named_origins"] == 2 and a.inputs["anonymous_origins"] == 1
    assert "unnamed sources" in a.summary
    # "officials said" is an attribution for the unattributed rule, not a bare claim
    assert rules.unattributed(event(reps, [g]), CFG) == []


def test_single_origin_names_the_one_speaker_and_their_party_status() -> None:
    reps = [rep(str(i)) for i in range(5)]
    cl = [claim(str(i), "The Aldoria defence ministry", "named") for i in range(4)]
    cl.append(claim("4", "Kessar Times", "named"))
    g = Group("g", "jets were shot down", {r.id for r in reps}, cl)
    ev = event(reps, [g])
    ev.parties = ["Aldoria", "Veymar"]
    (a,) = rules.single_origin(ev, CFG)
    assert a.inputs["share"] == 0.8 and a.inputs["party"] == "Aldoria"
    assert "a party to this story" in a.summary and "true" not in a.summary.lower()
    ev.groups[0].claims[3] = claim("3", "Kessar Times", "named")  # 3 of 5: below 80%
    assert rules.single_origin(ev, CFG) == []


def test_conflicting_accounts_needs_independent_texts_on_both_sides() -> None:
    reps = [rep("1"), rep("2"), rep("3", "IR"), rep("4", "IR")]
    a = Group(
        "a", "the port was hit", {"1", "2"}, [claim("1", None, "none"), claim("2", None, "none")]
    )
    b = Group(
        "b",
        "the port was not hit",
        {"3", "4"},
        [claim("3", None, "none"), claim("4", None, "none")],
    )
    ev = event(reps, [a, b])
    ev.conflicts = [("a", "b", 0.95)]
    (x,) = rules.conflicting_accounts(ev, CFG)
    assert x.summary.startswith("Reports conflict on:") and x.inputs["fisher_p"]["IL"] == 1 / 3
    ev.reports[3] = rep("4", "IR", origin_id="3")  # side b is one text republished
    assert rules.conflicting_accounts(ev, CFG) == []
    assert rules.fisher_2x2(3, 0, 0, 3) == 0.1


def test_attribution_spans_split_speaker_cue_and_content() -> None:
    from weft_core import attribution

    s = "Aldoria's defence ministry said on Friday that 40 missiles were launched."
    a = attribution.extract(s)
    assert a["speaker"] == "Aldoria's defence ministry" and a["speaker_kind"] == "named"
    c0, c1 = a["content_span"]
    assert s[c0:c1] == "40 missiles were launched"
    b = attribution.extract("Forty missiles were launched, officials said.")
    assert b["speaker_kind"] == "anonymous" and b["stance"] == "assert"
    assert attribution.extract("Veymar denied losing any jets.")["stance"] == "deny"
    assert attribution.extract("Missiles struck the port overnight.")["speaker_kind"] == "none"
    assert attribution.normalise("The Aldoria defence ministry") == "aldoria defence ministry"


def test_quote_differs_fires_between_faithful_and_unrelated() -> None:
    q = {
        "figure_id": "f",
        "report_id": "1",
        "text": "we will reopen the Kessar port next week",
        "speaker": "Arlen Voss",
        "statement_id": "s",
        "statement": "We will reopen the Kessar port soon.",
        "actor": "Minister Voss",
        "issuer": "Aldoria ministry",
        "edit_ratio": 0.25,
    }
    ev = event([rep("1")])
    ev.quotes = [q]
    (a,) = rules.quote_differs(ev, CFG)
    assert "issued by Aldoria ministry" in a.summary and a.evidence_ids == ["1", "s"]
    ev.quotes = [q | {"edit_ratio": 0.05}]  # word for word: nothing to flag
    assert rules.quote_differs(ev, CFG) == []
    ev.quotes = [q | {"speaker": "Kessar Times"}]  # another speaker
    assert rules.quote_differs(ev, CFG) == []


def test_one_outlets_own_sites_share_an_owner_key() -> None:
    from weft_core.outlets import site_owner

    assert site_owner("https://edition.cnn.com") == site_owner("https://www.cnn.com/")
    assert site_owner("https://www.bbc.co.uk") == "site:bbc.co.uk"
    assert site_owner("https://a.example") != site_owner("https://b.example")
    assert site_owner(None) is None
