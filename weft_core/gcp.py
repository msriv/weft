"""GCP client factories. `BIGQUERY_EMULATOR_HOST` (set only by docker-compose.yml) points the
BigQuery client at a local emulator; the other GCP clients read their own emulator env vars."""

import os

from google.cloud import bigquery


def bigquery_client(project: str) -> bigquery.Client:
    host = os.environ.get("BIGQUERY_EMULATOR_HOST")
    if not host:
        return bigquery.Client(project=project)
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials

    return bigquery.Client(
        project=project,
        client_options=ClientOptions(api_endpoint=host),
        credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
    )
