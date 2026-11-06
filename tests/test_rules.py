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
    reps = [rep("1"), rep("2"), rep("3", "IL"), rep("4", "IR"), rep("5", "IR")]
    g = Group("g", "claim", {"1", "2", "3", "4"})
    assert rules.omission(event(reps, [g]), CFG) == [], "carried by 4 of 5 but IR has report 4"
    g2 = Group("g", "claim", {"1", "2", "3"})  # 3 of 5 = 60%, none from IR
    (a,) = rules.omission(event(reps, [g2]), CFG)
    assert a.rule == "omission" and a.rule_version == CFG["version"]
    assert a.inputs["perspective"] == "IR" and set(a.evidence_ids) >= {"1", "2", "3", "4", "5"}
    assert "true" not in a.summary.lower()  # coverage language only


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
        Figure("f1", "1", "missile", 40, "40 missiles"),
        Figure("f2", "2", "missile", 25, "25 missiles"),
    ]
    (a,) = rules.numbers_differ(event([rep("1"), rep("2")], figures=f), CFG)
    assert a.evidence_ids == ["f2", "f1"] and a.inputs["difference"] > 0.2
    close = [Figure("f1", "1", "missile", 40, ""), Figure("f2", "2", "missile", 36, "")]
    assert rules.numbers_differ(event([rep("1"), rep("2")], figures=close), CFG) == []  # 10%
    same = [Figure("f1", "1", "missile", 40, ""), Figure("f2", "1", "missile", 10, "")]
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


def silence_reps(quiet_healthy: bool = True) -> list[Rep]:
    now = T0
    out = [rep(f"p{i}", src="quiet", hours=-60 + i, healthy=quiet_healthy) for i in range(2)]
    out += [rep(f"o{i}", src="other", hours=-90 + 5 * i) for i in range(6)]  # prior window
    out += [rep(f"n{i}", src="other", hours=-40 + 5 * i) for i in range(6)]  # recent window
    assert now
    return out


def test_silence_fires_and_is_suppressed_for_unhealthy_feeds() -> None:
    (a,) = rules.silence("st", silence_reps(), T0, CFG)
    assert a.subject_id == "quiet" and a.inputs["recent"] == 6
    assert rules.silence("st", silence_reps(quiet_healthy=False), T0, CFG) == []


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
    f = [Figure("f1", "1", "m", 40, ""), Figure("f2", "2", "m", 10, "")]
    (a,) = rules.evaluate_event(event(reps, figures=f), CFG, NOW)
    assert a.status == "provisional"  # 3 sources < 5
    many = [rep(str(i), "IL" if i % 2 else "IR") for i in range(1, 7)]
    (b,) = rules.evaluate_event(event(many, figures=f), CFG, NOW)
    assert b.status == "active"
    (c,) = rules.evaluate_event(event(many, figures=f), CFG, T0 + timedelta(hours=2))
    assert c.status == "provisional"  # under 6 hours since first report


def test_same_input_same_anomaly_id() -> None:
    f = [Figure("f1", "1", "m", 40, ""), Figure("f2", "2", "m", 10, "")]
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
