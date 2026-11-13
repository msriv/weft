"""Beat relevance from a profile (#107). Placeholder names only."""

from weft_core import discovery, relevance, store
from weft_core.store import local_db

BEAT = {"id": "b", "patterns": [r"\bkessar\b"], "exclude": [r"\bfootball\b"]}
PROF = {"centroid": [1.0, 0.0], "entities": {"aldoria navy": 3.0, "kessar strait": 2.0}, "n": 20}


def test_regex_alone_until_a_profile_exists_and_exclusions_always_win() -> None:
    assert relevance.score(BEAT, None, "Kessar port closed", [1.0, 0.0], set()) == 1.0
    assert relevance.score(BEAT, None, "Port closed", [1.0, 0.0], set()) == 0.0
    assert relevance.score(BEAT, PROF, "Kessar football final", [1.0, 0.0], set()) == 0.0


def test_profile_admits_on_topic_text_without_the_term_and_holds_weak_regex_hits() -> None:
    # on topic, no beat term: text and entities carry it past the accept line
    on = relevance.score(BEAT, PROF, "Navy ships seen", [1.0, 0.0], {"Aldoria Navy"})
    assert on >= relevance.ACCEPT
    # the term alone in unrelated text lands below accept: held as a maybe, not trusted
    weak = relevance.score(BEAT, PROF, "Kessar bakery opens", [0.0, 1.0], set())
    assert weak < relevance.ACCEPT
    beat, s = relevance.best([BEAT], {"b": PROF}, "Navy ships seen", [1.0, 0.0], {"Aldoria Navy"})
    assert beat is BEAT and s == on


def test_profiles_round_trip_and_maybes_collect_owner_labels() -> None:
    db = local_db()
    store.init(db)
    relevance.save(db, "b", PROF, "2026-11-13T00:00:00+00:00")
    assert relevance.load(db)["b"]["entities"] == PROF["entities"]
    relevance.record_maybe(db, "r1", "b", 0.4, "2026-11-13T00:00:00+00:00")
    assert [m["report_id"] for m in relevance.maybes(db)] == ["r1"]
    relevance.label_maybe(db, "r1", "b", True, "2026-11-13T01:00:00+00:00")
    assert relevance.maybes(db) == []
    relevance.save(db, "b", None, "2026-11-13T00:00:00+00:00")
    assert relevance.load(db) == {}


def test_discovery_ranks_domains_by_mean_relevance_times_days_seen() -> None:
    db = local_db()
    store.init(db)
    day1, day2 = "2026-11-12T00:00:00+00:00", "2026-11-13T00:00:00+00:00"
    store.add_candidate_hits(db, "many.example", "b", 6, day2, 3.0)  # many hits, weak, one day
    store.add_candidate_hits(db, "steady.example", "b", 3, day1, 3.0)
    store.add_candidate_hits(db, "steady.example", "b", 3, day2, 3.0)  # strong, two days
    assert store.candidates(db, "b", 3, 5) == ["steady.example", "many.example"]
    fields = ["id", "d", "1", "x.example", "https://x.example/a", "", "", "kessar"]
    fields += ["", "", "", "Aldoria Navy", "", "kessar strait"]
    rows = list(discovery.parse_gkg("\t".join(fields)))
    assert rows[0][3] == {"aldoria navy", "kessar strait"}
    hits = discovery.candidate_domains(rows, BEAT, set(), PROF)
    assert hits["x.example"]["https://x.example/a"] >= relevance.ACCEPT
