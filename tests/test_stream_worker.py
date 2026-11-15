import base64
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.stream_worker.app import create_app
from services.stream_worker.worker import Deps, classify_type, process
from weft_core import config, discovery, graph, store
from weft_core.nlp import HashEmbedder, LexicalNli, Nlp, RegexEntities, StopwordLangId
from weft_core.perspectives import perspective_of
from weft_core.store import Neo4jDb, local_db
from weft_core.textutil import minhash, minhash_similarity, sentences, shingles


def setup() -> tuple[Neo4jDb, Deps, list[dict[str, Any]]]:
    db = local_db()
    graph.init(db)
    discovery.seed_beats(db)
    for dom in ("a.il", "b.ir", "c.com"):
        store.register_source(
            db, domain=dom, name=dom, homepage=f"https://{dom}", feeds=["f"], via="t"
        )
    sent: list[dict[str, Any]] = []
    nlp = Nlp(HashEmbedder(), StopwordLangId(), RegexEntities(), LexicalNli())
    return db, Deps(db, nlp, config.pipeline(), sent.append), sent


def msg(i: str, src: str, title: str, lede: str, when: str) -> dict[str, Any]:
    return {
        "item_id": i,
        "source_id": src,
        "url": f"https://x/{i}",
        "title": title,
        "summary": lede,
        "published_at": when,
    }


def test_attach_and_new_event() -> None:
    db, d, sent = setup()
    t = "Iran fires missiles at Israel, Tehran says it targeted military bases"
    assert (
        process(
            msg(
                "1",
                "a-il",
                t,
                "Israel air defences intercepted missiles from Iran overnight.",
                "2026-11-06T01:00:00+00:00",
            ),
            d,
        )
        == "new_event"
    )
    assert (
        process(
            msg(
                "2",
                "b-ir",
                t,
                "Israel air defences intercepted missiles from Iran overnight.",
                "2026-11-06T02:00:00+00:00",
            ),
            d,
        )
        == "attached"
    )
    other = "Iran and Israel trade accusations at the United Nations about a shipping incident"
    assert (
        process(
            msg(
                "3",
                "c-com",
                other,
                "A different matter entirely concerning ships and diplomats.",
                "2026-11-06T03:00:00+00:00",
            ),
            d,
        )
        == "new_event"
    )
    r1, r2 = graph.get(db, "reports", "1"), graph.get(db, "reports", "2")
    assert r1 and r2 and r1["event_id"] == r2["event_id"] and r1["story_id"] == "iran-israel-war"
    assert (r1["perspective"], r2["perspective"]) == ("IL", "IR")
    assert (
        db.execute("MATCH (n:Copy) RETURN count(n) AS n")[0]["n"] == 1
    )  # identical text: copy candidate
    assert process(msg("2", "b-ir", t, "x", "2026-11-06T02:00:00+00:00"), d) == "duplicate"
    assert [m["status"] for m in sent] == ["new_event", "attached", "new_event"]
    assert graph.get(db, "events", r1["event_id"])["n_reports"] == 2  # type: ignore[index]


def test_no_beat_report_is_kept_without_story() -> None:
    db, d, _ = setup()
    assert (
        process(
            msg("9", "c-com", "Local bakery wins award", "Bread.", "2026-11-06T01:00:00+00:00"), d
        )
        == "no_beat"
    )
    r = graph.get(db, "reports", "9")
    assert r and r["story_id"] is None and r["event_id"] is None


def test_india_cec_beat_matches_name_and_impeachment_wording() -> None:
    db, d, _ = setup()
    a = process(
        msg(
            "a",
            "c-com",
            "Opposition moves to impeach Chief Election Commissioner",
            "Notice submitted in Parliament.",
            "2026-11-06T01:00:00+00:00",
        ),
        d,
    )
    b = process(
        msg(
            "b",
            "c-com",
            "Gyanesh Kumar responds to notice",
            "The commissioner said nothing.",
            "2026-11-06T02:00:00+00:00",
        ),
        d,
    )
    assert a != "no_beat" and b != "no_beat"
    assert graph.get(db, "reports", "a")["story_id"] == "india-cec-impeachment"  # type: ignore[index]
    parties = db.execute(
        "MATCH (n:StoryParty {story_id: 'india-cec-impeachment'}) "
        "RETURN n.party AS party, n.citation AS citation"
    )
    assert parties and all(p["citation"] is None for p in parties)  # proposed, unverified


def test_classify_type_rules() -> None:
    assert classify_type("https://x/opinion/a", "", "t", "l", None) == "op-ed"
    assert classify_type("https://x/analysis/a", "", "t", "l", None) == "analysis"
    assert classify_type("https://x/a", "World", "t", "l", None) == "news"


def test_perspective_of() -> None:
    assert perspective_of({"homepage": "https://www.timesofisrael.co.il/x"}) == "IL"
    assert perspective_of({"homepage": "https://bbc.co.uk"}) == "GB"
    assert perspective_of({"homepage": "https://reuters.com"}) == "unattributed"
    assert perspective_of({"homepage": "https://reuters.com", "country": "us"}) == "US"


def test_textutil() -> None:
    t = "Iran said it fired. Israel denied that claim! Nobody else commented."
    assert [t[s:e] for s, e in sentences(t)] == [
        "Iran said it fired.",
        "Israel denied that claim!",
        "Nobody else commented.",
    ]
    a = shingles("one two three four five six seven eight nine ten eleven twelve")
    assert minhash_similarity(minhash(a), minhash(a)) == 1.0
    assert (
        minhash_similarity(
            minhash(a), minhash(shingles("completely different words in this sentence here now ok"))
        )
        < 0.2
    )


def test_push_endpoint_drops_malformed() -> None:
    _, d, sent = setup()
    c = TestClient(create_app(d))
    bad = c.post("/", json={"message": {"data": base64.b64encode(b"{}").decode()}})
    good = c.post(
        "/",
        json={
            "message": {
                "data": base64.b64encode(
                    json.dumps(
                        msg("z", "c-com", "Nothing", "Nothing.", "2026-11-06T01:00:00+00:00")
                    ).encode()
                ).decode()
            }
        },
    )
    assert bad.status_code == good.status_code == 204 and len(sent) == 1


def test_glot_langid_works_with_numpy_2(tmp_path: Any) -> None:
    """fasttext's single-string predict breaks on NumPy 2; detect must not use it."""
    import pytest

    fasttext = pytest.importorskip("fasttext")  # only in the `ml` dependency group
    from weft_core.nlp import GlotLangId

    data = tmp_path / "train.txt"
    data.write_text("__label__eng_Latn the cat is here\n__label__fra_Latn le chat est ici\n")
    path = str(tmp_path / "m.bin")
    fasttext.train_supervised(str(data), epoch=5, verbose=0).save_model(path)
    assert GlotLangId(path).detect("the cat\nis here") == "en"


def test_beat_terms_catch_core_reports_and_skip_lookalikes() -> None:
    from weft_core.beats import matching

    beats = [{"id": b[0], "patterns": b[2], "exclude": b[3]} for b in discovery.BEATS]
    cases = {
        "IDF strikes Tehran missile sites": ["iran-israel-war"],
        "Kyiv hit by drone barrage; Zelensky urges allies": ["ukraine-russia-war"],
        "Ohio Senate race: Brown leads Moreno": ["us-senate-democrats"],
        "Opposition moves to impeach Chief Election Commissioner": ["india-cec-impeachment"],
        "Texas state Senate Democrats walk out": [],
        "Philippine Senate votes on budget": [],
        "Election Commission removes 3 lakh names from Bihar voter roll": [],
        "Oil prices jump. Traders watch Iran after Israel warning": [],
    }
    for text, want in cases.items():
        assert [b["id"] for b in matching(beats, text)] == want, text


def test_seed_never_overwrites_an_admin_edited_beat() -> None:
    db = local_db()
    discovery.seed_beats(db)
    store.add_beat(db, "iran-israel-war", "Iran-Israel war", ["mine"])
    db.execute("MATCH (n:Beat {id: 'iran-israel-war'}) SET n.edited=1")
    discovery.seed_beats(db)
    [b] = [b for b in store.beats(db) if b["id"] == "iran-israel-war"]
    assert b["patterns"] == ["mine"]


def test_only_on_beat_reports_suggest_portals() -> None:
    db, d, _ = setup()
    off = msg("o", "c-com", "Local bakery wins award", "Bread.", "2026-11-06T01:00:00+00:00")
    on = msg(
        "p", "c-com", "Israel and Iran trade strikes", "Missiles.", "2026-11-06T01:00:00+00:00"
    )
    process({**off, "gov_domains": ["bakery.gov.xx"]}, d)
    process({**on, "gov_domains": ["mfa.gov.il"]}, d)
    got = {r["domain"] for r in db.execute("MATCH (n:PortalCandidate) RETURN n.domain AS domain")}
    assert got == {"mfa.gov.il"}


def test_attach_score_weighs_rare_entities_and_vetoes_beat_wide_ones() -> None:
    from collections import Counter

    from weft_core import clustering

    df = Counter({"Aldoria": 30, "Veymar": 30, "Kessar": 2, "Port Halen": 1})
    idf = clustering.idf_table(df, 30)
    ev = {"centroid": [1.0, 0.0], "first_seen": "2026-11-06T00:00:00+00:00", "n_reports": 2,
          "entity_counts": {"Aldoria": 2, "Kessar": 2}}  # fmt: skip
    cfg = config.pipeline()["stream"]
    rare = clustering.score(
        [1.0, 0.0], {"Aldoria", "Kessar"}, "2026-11-06T01:00:00+00:00", ev, cfg, idf, veto=True
    )
    common = clustering.score(
        [1.0, 0.0], {"Aldoria", "Veymar"}, "2026-11-06T01:00:00+00:00", ev, cfg, idf, veto=True
    )
    assert rare > 0.5 and common == 0.0  # only beat-wide entities shared: vetoed
    later = clustering.absorb(ev, [0.0, 1.0], {"Kessar"}, "2026-11-06T05:00:00+00:00")
    assert (
        later["entity_counts"]["Kessar"] == 3 and later["last_seen"] == "2026-11-06T05:00:00+00:00"
    )


T = "Iran fires missiles at Israel, Tehran says it targeted military bases"
L = "Israel air defences intercepted missiles from Iran overnight."


def double_current(db: Neo4jDb) -> list[dict[str, Any]]:
    """Ids that have more than one current version (must always be empty)."""
    return db.execute(
        "MATCH (n) WHERE n.id IS NOT NULL AND n.valid_to IS NULL AND n.valid_from IS NOT NULL "
        "WITH labels(n)[0] AS l, n.id AS id, count(n) AS c WHERE c > 1 RETURN l, id, c"
    )


def test_failure_after_the_event_write_leaves_the_graph_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, d, sent = setup()
    process(msg("1", "a-il", T, L, "2026-11-06T01:00:00+00:00"), d)
    real = graph.put

    def boom(db_: Any, table: str, row: dict[str, Any], at: str | None = None) -> None:
        if table == "reports":
            raise RuntimeError("crash between the event and the report")
        real(db_, table, row, at)

    monkeypatch.setattr("services.stream_worker.worker.graph.put", boom)
    with pytest.raises(RuntimeError):
        process(msg("2", "b-ir", T, L, "2026-11-06T02:00:00+00:00"), d)
    monkeypatch.setattr("services.stream_worker.worker.graph.put", real)
    (ev,) = graph.select(db, "events")
    assert ev["n_reports"] == 1 and len(sent) == 1  # nothing written, nothing published
    assert (
        process(msg("2", "b-ir", T, L, "2026-11-06T02:00:00+00:00"), d) == "attached"
    )  # redelivery
    (ev,) = graph.select(db, "events")
    assert ev["n_reports"] == 2 == len(graph.reports_of_event(db, ev["id"]))
    assert double_current(db) == []


def test_parallel_near_identical_reports_make_one_event() -> None:
    db, d, _ = setup()
    srcs = ["a-il", "b-ir", "c-com"]
    with ThreadPoolExecutor(8) as pool:
        out = list(
            pool.map(
                lambda i: process(
                    msg(f"r{i}", srcs[i % 3], T, L, f"2026-11-06T01:{i:02d}:00+00:00"), d
                ),
                range(20),
            )
        )
    assert len(out) == 20
    (ev,) = graph.select(db, "events")
    assert ev["n_reports"] == 20 == len(graph.reports_of_event(db, ev["id"]))
    assert len(graph.select(db, "reports")) == 20
    assert double_current(db) == []


def test_same_message_delivered_twice_at_once_writes_one_report() -> None:
    db, d, sent = setup()
    m = msg("dup", "a-il", T, L, "2026-11-06T01:00:00+00:00")
    with ThreadPoolExecutor(2) as pool:
        out = sorted(pool.map(lambda _: process(m, d), range(2)))
    assert out == ["duplicate", "new_event"]
    assert len(graph.select(db, "reports")) == 1 and len(sent) == 1
    assert double_current(db) == []


def test_one_report_costs_a_bounded_number_of_queries() -> None:
    db, d, _ = setup()
    runs: list[str] = []
    inner = db.execute

    def counted(q: str, a: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        runs.append(q)
        return inner(q, a)

    db.execute = counted  # type: ignore[method-assign,assignment]
    nlp = d.nlp

    def many(text: str) -> list[tuple[str, str]]:
        return [(f"Entity{i}", "X") for i in range(30)]

    nlp.entities.extract = many  # type: ignore[method-assign]
    process(msg("q1", "a-il", T, L, "2026-11-06T01:00:00+00:00"), d)
    assert len(runs) < 40  # 30 entities would be 30+ queries one by one


def test_one_message_among_2000_stored_reports_reads_few_rows() -> None:
    import random

    db, d, _ = setup()
    process(msg("seed", "a-il", T, L, "2026-11-06T00:00:00+00:00"), d)  # makes the story
    rng = random.Random(1)
    rows = [
        {
            "id": f"old{i}",
            "story_id": "iran-israel-war",
            "event_id": f"ev{i % 40}",
            "published_at": "2026-11-06T00:30:00+00:00",
            "valid_from": "x",
            "minhash": json.dumps([rng.randrange(2**61) for _ in range(64)]),
            "embedding": json.dumps([rng.random() for _ in range(64)]),
        }
        for i in range(2000)
    ]
    db.execute("UNWIND ? AS r CREATE (n:Report) SET n = r", (rows,))
    counted = {"rows": 0, "queries": 0}
    inner = db.execute

    def counting(q: str, a: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        out = inner(q, a)
        counted["queries"] += 1
        if ":Report" in q or "(n:Report" in q:
            counted["rows"] += len(out)
        return out

    db.execute = counting  # type: ignore[method-assign,assignment]
    process(msg("new", "b-ir", T + " again", L, "2026-11-06T01:00:00+00:00"), d)
    assert counted["rows"] < 50 and counted["queries"] < 60


def test_a_copy_at_085_jaccard_is_found_through_the_band_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from weft_core.textutil import bands

    db, d, _ = setup()
    sig = minhash(shingles(" ".join(f"word{i}" for i in range(80))))
    other = [v + 1 if i % 7 == 0 else v for i, v in enumerate(sig)]  # 54 of 64 agree: 0.84
    assert 0.84 <= minhash_similarity(sig, other) < 0.86
    db.execute(
        "CREATE (:Report {id: 'stored', valid_from: 'x', published_at: ?, minhash: ?})",
        ("2026-11-06T00:30:00+00:00", json.dumps(other)),
    )
    db.execute(
        "UNWIND ? AS k CREATE (:MinhashBand {report_id: 'stored', band: k, at: ?})",
        (bands(other), "2026-11-06T00:30:00+00:00"),
    )
    monkeypatch.setattr("services.stream_worker.worker.minhash", lambda _: sig)
    process(msg("c2", "b-ir", T, L, "2026-11-06T01:00:00+00:00"), d)
    (row,) = db.execute("MATCH (c:Copy {report_id: 'c2', copy_of: 'stored'}) RETURN c.jaccard AS j")
    assert 0.84 <= row["j"] < 0.86


def test_a_source_registered_after_start_is_seen_without_waiting_for_the_ttl() -> None:
    db, d, _ = setup()
    process(msg("s1", "a-il", T, L, "2026-11-06T01:00:00+00:00"), d)  # warms the cache
    assert process(msg("s2", "d-org", T, L, "2026-11-06T01:10:00+00:00"), d) == "unknown_source"
    store.register_source(
        db, domain="d.org", name="d", homepage="https://d.org", feeds=["f"], via="t"
    )
    assert process(msg("s3", "d-org", T, L, "2026-11-06T01:20:00+00:00"), d) == "attached"


def test_cache_expires_after_the_ttl() -> None:
    from weft_core.cache import TtlCache

    now = [0.0]
    c = TtlCache(60, clock=lambda: now[0])
    n = [0]
    load = lambda: n.__setitem__(0, n[0] + 1) or n[0]
    assert (c.get("k", load), c.get("k", load)) == (1, 1)
    now[0] = 61
    assert c.get("k", load) == 2


def test_push_unknown_source_is_retried_not_dropped() -> None:
    _, d, sent = setup()
    c = TestClient(create_app(d))
    m = msg("y", "no-such-source", "T", "T.", "2026-11-06T01:00:00+00:00")
    r = c.post("/", json={"message": {"data": base64.b64encode(json.dumps(m).encode()).decode()}})
    assert r.status_code == 503 and not sent  # Pub/Sub retries, then dead-letters
