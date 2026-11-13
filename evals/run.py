"""Eval runner. Labelled sets in evals/sets/*.jsonl; model answers are replayed from
evals/recorded/*.json so CI is deterministic. `--live` calls the real model client and rewrites
the recordings, which is what you run after changing a prompt or a model.

The seed sets use fictional placeholder names (Aldoria, Veymar, Ostia). The real labelled set is
written by editors per language (open question in docs/spec.md).
"""

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from pipeline import claims, regroup
from weft_core import ask, graph, translate
from weft_core.models import ModelClient
from weft_core.nlp import default_nlp
from weft_core.store import local_db
from weft_core.textutil import sentences

HERE = Path(__file__).parent


def load(name: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (HERE / "sets" / f"{name}.jsonl").read_text().splitlines() if x]


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}


def chrf(hyp: str, ref: str, n: int = 4) -> float:
    """Character n-gram F-score (chrF, beta=1), averaged over n=1..4."""

    def grams(s: str, k: int) -> dict[str, int]:
        s = s.replace(" ", "")
        out: dict[str, int] = {}
        for i in range(len(s) - k + 1):
            out[s[i : i + k]] = out.get(s[i : i + k], 0) + 1
        return out

    scores = []
    for k in range(1, n + 1):
        h, r = grams(hyp, k), grams(ref, k)
        hit = sum(min(c, r.get(g, 0)) for g, c in h.items())
        p, rc = hit / max(sum(h.values()), 1), hit / max(sum(r.values()), 1)
        scores.append(2 * p * rc / (p + rc) if p + rc else 0.0)
    return sum(scores) / n


def _client(recorded: dict[str, str] | None, current: list[str]) -> ModelClient:
    """Replay client when `recorded` is given, else the live one from the environment."""
    import os

    log: list[Any] = []
    if recorded is None:
        return ModelClient(
            base_url=os.environ["MODEL_BASE_URL"],
            api_key=os.environ["MODEL_API_KEY"],
            model=os.environ["MODEL_NAME"],
            revision=os.environ["MODEL_REVISION"],
            log=log.append,
        )

    def handler(_: httpx.Request) -> httpx.Response:
        body = {"choices": [{"message": {"content": recorded[current[0]]}}]}
        return httpx.Response(200, json=body)

    return ModelClient(
        base_url="http://replay",
        api_key="x",
        model="replay",
        revision="replay",
        log=log.append,
        transport=httpx.MockTransport(handler),
    )


def _model_task(
    name: str, live: bool, call: Callable[[ModelClient, dict[str, Any]], Any]
) -> tuple[list[tuple[dict[str, Any], Any]], dict[str, str]]:
    cases = load(name)
    path = HERE / "recorded" / f"{name}.json"
    current = [""]
    client = _client(None if live else json.loads(path.read_text()), current)
    results = []
    for c in cases:
        current[0] = c["id"]
        results.append((c, call(client, c)))
    return results, {}


def eval_merges(live: bool) -> dict[str, float]:
    res, _ = _model_task("merges", live, lambda m, c: regroup.merge_check(m, c["a"], c["b"]))
    tp = sum(1 for c, got in res if got and c["same"])
    fp = sum(1 for c, got in res if got and not c["same"])
    fn = sum(1 for c, got in res if not got and c["same"])
    return prf(tp, fp, fn)


def eval_claims(live: bool) -> dict[str, float]:
    res, _ = _model_task("claims", live, lambda m, c: claims.extract(m, c["text"]))
    tp = fp = fn = 0
    for c, spans in res:
        all_spans = sentences(c["text"])
        got = {all_spans.index(s) for s in spans}
        gold = set(c["gold"])
        tp, fp, fn = tp + len(got & gold), fp + len(got - gold), fn + len(gold - got)
    return prf(tp, fp, fn)


def eval_nli() -> dict[str, float]:
    nli = default_nlp().nli
    tp = fp = fn = 0
    for c in load("nli"):
        got = nli.contradiction(c["premise"], c["hypothesis"]) >= 0.8
        tp += got and c["contradiction"]
        fp += got and not c["contradiction"]
        fn += (not got) and c["contradiction"]
    return prf(tp, fp, fn)


def eval_attribution() -> dict[str, float]:
    """Speaker kind, stance and content span of the attribution parser (#101). Placeholder
    sentences only; the owner's labelled set (200 real sentences) goes in evals/private/."""
    from weft_core import attribution

    rows = load("attribution")
    kind = stance = span = 0
    for c in rows:
        a = attribution.extract(c["sentence"], default_nlp().parser)
        s0, s1 = a["content_span"]
        kind += a["speaker_kind"] == c["speaker_kind"]
        stance += a["stance"] == c["stance"]
        span += c["sentence"][s0:s1] == c["content"]
    n = len(rows)
    return {"speaker_kind": kind / n, "stance": stance / n, "content_exact": span / n}


def eval_translation(live: bool) -> dict[str, float]:
    db = local_db()
    graph.init(db)
    res, _ = _model_task(
        "translation", live, lambda m, c: translate.translate(db, m, c["source"], c["dst"])
    )
    return {"chrf": sum(chrf(got, c["reference"]) for c, got in res) / len(res)}


def eval_ask(live: bool) -> dict[str, float]:
    """Which recorded answer statements survive the citation and no-verdict checks, vs gold."""

    def call(m: ModelClient, c: dict[str, Any]) -> list[str]:
        ps = [{"id": f"p{i}", "outlet": "O", "perspective": "xx", "text": t, "url": "u",
               "title": "t", "report_id": "r", "start_char": 0, "end_char": 1}
              for i, t in enumerate(c["passages"], 1)]  # fmt: skip
        return [s["text"] for s in ask.answer_from(m, c["question"], ps)["sentences"]]

    res, _ = _model_task("ask", live, call)
    tp = fp = fn = 0
    for c, kept in res:
        got, gold = set(kept), set(c["gold_kept"])
        tp, fp, fn = tp + len(got & gold), fp + len(got - gold), fn + len(gold - got)
    return prf(tp, fp, fn)


def run_all(live: bool = False) -> dict[str, dict[str, float]]:
    return {
        "merges": eval_merges(live),
        "claims": eval_claims(live),
        "nli": eval_nli(),
        "attribution": eval_attribution(),
        "translation": eval_translation(live),
        "ask": eval_ask(live),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="call the real model, not recordings")
    args = ap.parse_args()
    print(json.dumps(run_all(args.live), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
