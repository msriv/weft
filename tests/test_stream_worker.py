import base64
import json
from typing import Any

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
