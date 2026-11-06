"""GCP bindings for the nightly job: raw copy -> text, and the `model_calls` sink."""

from typing import Any

from google.cloud import bigquery, storage  # type: ignore[attr-defined]

from services.fetcher.fetcher import _extract
from weft_core.models import ModelCall, as_row


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


def bq_sink(project: str, dataset: str = "weft"):  # type: ignore[no-untyped-def]
    client = bigquery.Client(project=project)

    def sink(call: ModelCall) -> None:
        if errs := client.insert_rows_json(f"{project}.{dataset}.model_calls", [as_row(call)]):
            raise RuntimeError(f"model_calls insert failed: {errs}")

    return sink
