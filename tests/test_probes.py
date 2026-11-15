from fastapi import FastAPI
from fastapi.testclient import TestClient

from weft_core import graphsize, store
from weft_core.probes import add_probes


class Down:
    def execute(self, query: str, args: tuple[object, ...] = ()) -> list[dict[str, object]]:
        raise ConnectionError("neo4j is down")


def test_healthz_is_up_and_readyz_follows_the_graph() -> None:
    ok, bad = FastAPI(), FastAPI()
    add_probes(ok, store.local_db())
    add_probes(bad, Down())
    assert TestClient(ok).get("/healthz").json() == {"ok": True}
    assert TestClient(ok).get("/readyz").status_code == 200
    assert TestClient(bad).get("/healthz").status_code == 200  # process up, not ready
    assert TestClient(bad).get("/readyz").status_code == 503


def test_graph_size_line(capsys: object) -> None:
    import json

    db = store.local_db()
    store.init(db)
    out = graphsize.log(db)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])  # type: ignore[attr-defined]
    assert line["event"] == "graph_size" and line["nodes"] == out["nodes"]
    assert "by_label" in line
