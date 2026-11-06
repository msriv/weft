"""Cloud Tasks binding for delayed re-fetches."""

import json
from datetime import datetime

from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2


class CloudTasksQueue:
    def __init__(
        self, project: str, region: str, queue: str, service_account: str, base_url: str
    ) -> None:
        self._c = tasks_v2.CloudTasksClient()
        self._parent = self._c.queue_path(project, region, queue)
        self._sa, self._url = service_account, base_url.rstrip("/") + "/refetch"

    def __call__(self, body: dict[str, object], when: datetime) -> None:
        ts = timestamp_pb2.Timestamp()
        ts.FromDatetime(when)
        self._c.create_task(
            parent=self._parent,
            task={  # type: ignore[arg-type]
                "schedule_time": ts,
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": self._url,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(body).encode(),
                    "oidc_token": {"service_account_email": self._sa},
                },
            },
        )
