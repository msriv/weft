from datetime import UTC, datetime
from email.utils import format_datetime

import httpx
from fastapi.testclient import TestClient

from services.api.app import create_app
from weft_core import discovery, store
from weft_core.polite import PoliteClient

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def gkg(domain: str, n: int, text: str = "iran israel strike") -> str:
    row = ["id", "d", "1", domain, "", "", "", text, "", "", "", "", "", ""]
    out = []
    for i in range(n):
        row[4] = f"https://{domain}/a{i}"
        out.append("\t".join(row))
    return "\n".join(out)


RSS = (
    '<rss version="2.0"><channel><item><title>t</title><link>https://good.example/a</link>'
    f"<pubDate>{format_datetime(NOW)}</pubDate></item></channel></rss>"
)
STALE = RSS.replace(format_datetime(NOW), "Mon, 01 Jan 2024 00:00:00 +0000")


def handler(req: httpx.Request) -> httpx.Response:
    host, path = req.url.host, req.url.path
    if path == "/robots.txt":
        return httpx.Response(404)
    if host == "good.example":
        if path == "/":
            return httpx.Response(
                200,
                text='<title>Good News</title><link rel="alternate" type="application/rss+xml" href="/f.xml">',
            )
        return httpx.Response(200, content=RSS) if path == "/f.xml" else httpx.Response(404)
    if host == "stale.example":
        return (
            httpx.Response(200, text="<title>Stale</title>")
            if path == "/"
            else (httpx.Response(200, content=STALE) if path == "/feed" else httpx.Response(404))
        )
    return httpx.Response(404)


def setup() -> tuple[store.Neo4jDb, PoliteClient]:
    db = store.local_db()
    store.init(db)
    discovery.seed_beats(db)
    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None)
    return db, http


def test_registers_only_verified_live_feeds_with_unverified_ownership() -> None:
    db, http = setup()
    text = "\n".join([gkg("good.example", 3), gkg("stale.example", 3), gkg("thin.example", 1)])
    found = discovery.discover(db, http, text, NOW)
    assert found == {"good.example": ["https://good.example/f.xml"]}
    [src] = store.active_sources(db)
    assert src["name"] == "Good News"
    assert not {"state_run", "owner_id", "country"} & src.keys()  # unverified, not guessed
    # stale feed is remembered as rejected, so it is not probed again
    assert {"good.example", "stale.example"} <= store.known_domains(db)
    assert "thin.example" not in store.known_domains(db)


def test_non_matching_articles_ignored() -> None:
    db, http = setup()
    assert discovery.discover(db, http, gkg("good.example", 5, "cooking recipes"), NOW) == {}


def test_robots_block_registers_nothing() -> None:
    db, _ = setup()

    def blocked(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, text="User-agent: *\nDisallow: /")
            if req.url.path == "/robots.txt"
            else handler(req)
        )

    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(blocked)), sleep=lambda _: None)
    assert discovery.discover(db, http, gkg("good.example", 3), NOW) == {}


def test_story_toggle_gates_public_list() -> None:
    db = store.local_db()
    store.init(db)
    store.add_beat(db, "b", "Beat", ["x"])
    store.create_story(db, "s1", "b", "A story")
    c = TestClient(create_app(db, "secret"))
    assert c.get("/stories").json() == []  # private by default
    assert c.put("/admin/stories/s1/public", json={"public": True}).status_code == 401
    ok = c.put(
        "/admin/stories/s1/public",
        json={"public": True},
        headers={"Authorization": "Bearer secret"},
    )
    assert ok.status_code == 200
    assert [s["id"] for s in c.get("/stories").json()] == ["s1"]
    off = {"Authorization": "Bearer secret"}
    c.put("/admin/stories/s1/public", json={"public": False}, headers=off)
    assert c.get("/stories").json() == []
    assert (
        c.put("/admin/stories/nope/public", json={"public": True}, headers=off).status_code == 404
    )


def test_live_sources_see_late_registration() -> None:
    db = store.local_db()
    store.init(db)
    live = store.LiveSources(db)
    assert "a-example" not in live
    store.register_source(
        db,
        domain="a.example",
        name="A",
        homepage="https://a.example/",
        feeds=["https://a.example/f"],
        via="t",
    )
    assert live["a-example"]["feeds"] == ["https://a.example/f"]


def test_latest_gkg_reads_several_slots_and_skips_missing() -> None:
    import io
    import zipfile

    import httpx

    from weft_core.discovery import GDELT_LAST, latest_gkg

    def zipped(text: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", text)
        return buf.getvalue()

    base = "http://data.gdeltproject.org/gdeltv2/"
    served = {
        "20261112120000": "a",  # 12:15 is listed but not served yet
        "20261112114500": "b",
        "20261112113000": "c",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == GDELT_LAST:
            return httpx.Response(200, text=f"1 x {base}20261112121500.gkg.csv.zip\n")
        stamp = str(req.url).removeprefix(base)[:14]
        return (
            httpx.Response(200, content=zipped(served[stamp]))
            if stamp in served
            else (httpx.Response(404))
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert latest_gkg(http, 2).split("\n") == ["a", "b"]
    assert latest_gkg(http) == "a"
