"""GCP bindings for the nightly job: raw copy -> text, and the `model_calls` sink."""

from datetime import datetime
from typing import Any

from google.cloud import bigquery, storage  # type: ignore[attr-defined]

from services.fetcher.fetcher import _extract
from weft_core.models import ModelCall, as_row
from weft_core.store import Db


class GcsText:
    """Text of a report, re-extracted from its private raw copy. Raw copies expire after 30 days
    (rule 5), so only recent reports can be re-read; older ones return ''."""

    def __init__(self, raw_bucket: str) -> None:
        self._bucket = storage.Client().bucket(raw_bucket)
        self._cache: dict[str, str] = {}

    def text(self, report: dict[str, Any]) -> str:
        rid = report["id"]
        if rid not in self._cache:
            for ext, ctype in (("html", "text/html"), ("pdf", "application/pdf")):
                blob = self._bucket.blob(f"{rid}.{ext}")
                if blob.exists():
                    meta, _ = _extract(blob.download_as_bytes(), report["url"], ctype)
                    self._cache[rid] = meta.get("text") or ""
                    break
            else:
                self._cache[rid] = ""
        return self._cache[rid]


def versions_of(raw_bucket: str, db: Db):  # type: ignore[no-untyped-def]
    """Texts of a report's saved versions, oldest first, consecutive duplicates collapsed."""
    bucket = storage.Client().bucket(raw_bucket)

    def get(report_id: str) -> list[tuple[datetime, str]]:
        out: list[tuple[datetime, str]] = []
        last = None
        for v in db.execute(
            "SELECT n, fetched_at, text_hash FROM report_versions WHERE report_id=? ORDER BY n",
            (report_id,),
        ):
            if v["text_hash"] == last:
                continue
            last = v["text_hash"]
            stem = report_id if v["n"] == 0 else f"{report_id}.v{v['n']}"
            for ext, ctype in (("html", "text/html"), ("pdf", "application/pdf")):
                blob = bucket.blob(f"{stem}.{ext}")
                if blob.exists():
                    meta, _ = _extract(blob.download_as_bytes(), report_id, ctype)
                    out.append((datetime.fromisoformat(v["fetched_at"]), meta.get("text") or ""))
                    break
        return out

    return get


def bq_sink(project: str, dataset: str = "weft"):  # type: ignore[no-untyped-def]
    client = bigquery.Client(project=project)

    def sink(call: ModelCall) -> None:
        if errs := client.insert_rows_json(f"{project}.{dataset}.model_calls", [as_row(call)]):
            raise RuntimeError(f"model_calls insert failed: {errs}")

    return sink
