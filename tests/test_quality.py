from typing import Any

import httpx
import pytest

from services.fetcher.fetcher import fetch_item
from tests.test_fetcher import HTML, SRC, MemStore, client
from weft_core import config, quality

Q = config.pipeline()["quality"]
ART = " ".join(f"The council met on day {i} and voted on the harbour budget." for i in range(8))


def chk(
    text: str, title: str = "Harbour budget vote", feed: str | None = "Harbour budget vote"
) -> Any:
    return quality.check(text, title, feed, "Example News", "en", Q)


def test_article_passes() -> None:
    assert chk(ART) is None


@pytest.mark.parametrize(
    "text,reason",
    [
        ("Short.", "thin"),
        ("Please subscribe to continue reading this article.", "stub"),
        (" ".join(["Enable JavaScript to view this page. We use cookies."] * 8), "stub"),
    ],
)
def test_thin_and_stub(text: str, reason: str) -> None:
    assert chk(text) == reason


def test_title_checks() -> None:
    assert chk(ART, title="Example News") == "title"
    assert chk(ART, title="Cats and dogs", feed="Harbour budget vote") == "title"
    assert chk(ART, title="Harbour budget", feed=None) is None


class QStore(MemStore):
    def __init__(self) -> None:
        super().__init__()
        self.outcomes: list[bool] = []

    def note_outcome(self, source_id: str, stub: bool, cfg: dict[str, Any]) -> None:
        self.outcomes.append(stub)


def test_ingest_rejects_stub_without_storing() -> None:
    store = QStore()
    page = "<html><head><title>Port closed</title></head><body><article><p>Subscribe to continue reading.</p></article></body></html>"
    msg = {"source_id": "x", "url": "https://x.test/a", "title": "Port closed"}
    r = fetch_item(msg, SRC, client(httpx.Response(200, text=page)), store, qcfg=Q)
    assert r.status in ("thin", "stub") and r.message is None and not store.rows
    assert store.outcomes == [True]


def test_ingest_stores_article_and_counts_it() -> None:
    store = QStore()
    msg = {"source_id": "x", "url": "https://x.test/story/1", "title": "Port closed"}
    assert (
        fetch_item(msg, SRC, client(httpx.Response(200, text=HTML)), store, qcfg=Q).status
        == "stored"
    )
    assert store.outcomes == [False]


def test_boilerplate_rejected() -> None:
    class B(QStore):
        def boilerplate(self, h: str, url: str, limit: int) -> bool:
            return True

    msg = {"source_id": "x", "url": "https://x.test/story/1", "title": "Port closed"}
    s = B()
    assert (
        fetch_item(msg, SRC, client(httpx.Response(200, text=HTML)), s, qcfg=Q).status
        == "boilerplate"
    )
    assert not s.rows
