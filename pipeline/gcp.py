"""GCP bindings for the nightly job: raw copy -> text, and the `model_calls` sink."""

import json
from datetime import datetime
from typing import Any

from google.cloud import storage  # type: ignore[attr-defined]

from services.fetcher.fetcher import _extract
from weft_core.gcp import bigquery_client
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
            "MATCH (v:ReportVersion {report_id: ?}) "
            "RETURN v.n AS n, v.fetched_at AS fetched_at, v.text_hash AS text_hash ORDER BY v.n",
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
    client = bigquery_client(project)

    def sink(call: ModelCall) -> None:
        if errs := client.insert_rows_json(f"{project}.{dataset}.model_calls", [as_row(call)]):
            raise RuntimeError(f"model_calls insert failed: {errs}")

    return sink


class BqWarehouse:
    """`weft_core.autoclean.Warehouse` on BigQuery. `{ds}` in the SQL is the dataset."""

    def __init__(self, project: str, dataset: str = "weft") -> None:
        self._client = bigquery_client(project)
        self._ds = f"{project}.{dataset}"

    def _job(self, sql: str, params: dict[str, Any]):  # type: ignore[no-untyped-def]
        from google.cloud import bigquery

        def typed(k: str, v: Any) -> bigquery.ScalarQueryParameter:
            kind = (
                "TIMESTAMP"
                if isinstance(v, datetime)
                else "INT64"
                if isinstance(v, int)
                else "STRING"
            )
            return bigquery.ScalarQueryParameter(k, kind, v)

        cfg = bigquery.QueryJobConfig(query_parameters=[typed(k, v) for k, v in params.items()])
        return self._client.query(sql.replace("{ds}", self._ds), job_config=cfg)

    def query(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(r) for r in self._job(sql, params).result()]

    def execute(self, sql: str, params: dict[str, Any]) -> int:
        job = self._job(sql, params)
        job.result()
        return int(job.num_dml_affected_rows or 0)


def pubsub_publish(project: str):  # type: ignore[no-untyped-def]
    from google.cloud import pubsub_v1  # type: ignore[attr-defined]

    publisher = pubsub_v1.PublisherClient()

    def publish(topic: str, message: dict[str, Any]) -> None:
        publisher.publish(
            publisher.topic_path(project, topic), json.dumps(message).encode()
        ).result()

    return publish
