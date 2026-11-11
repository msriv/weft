"""Reader accounts: Firebase Authentication ID tokens, preferences in Firestore (spec: accounts sit
apart from the story graph). Both talk plain HTTPS, so the Firebase emulator suite works with the
same code: `FIREBASE_AUTH_EMULATOR_HOST` and `FIRESTORE_EMULATOR_HOST` are set only by
docker-compose.yml."""

import base64
import json
import os
from typing import Any, Protocol

import httpx


class Prefs(Protocol):
    def get(self, uid: str) -> dict[str, Any]: ...
    def put(self, uid: str, prefs: dict[str, Any]) -> None: ...


def verify_token(token: str, project: str) -> str | None:
    """Firebase user id for a valid ID token, else None."""
    try:
        if os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"):
            # emulator tokens are unsigned (alg none); local runs only
            claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
            ok = claims.get("aud") == project
        else:
            from google.auth.transport import requests as grequests
            from google.oauth2 import id_token

            claims = id_token.verify_firebase_token(  # type: ignore[no-untyped-call]
                token, grequests.Request(), audience=project
            )
            ok = claims is not None
        return str(claims["sub"]) if ok else None
    except (ValueError, KeyError, IndexError):
        return None


class FirestorePrefs:
    """One document per reader, `users/{uid}`, with the preferences as one JSON string field."""

    def __init__(self, project: str, http: httpx.Client | None = None) -> None:
        host = os.environ.get("FIRESTORE_EMULATOR_HOST")
        base = f"http://{host}" if host else "https://firestore.googleapis.com"
        self._url = f"{base}/v1/projects/{project}/databases/(default)/documents/users"
        self._local = bool(host)
        self._http = http or httpx.Client(timeout=15)

    def _headers(self) -> dict[str, str]:
        if self._local:
            return {"Authorization": "Bearer owner"}
        import google.auth
        from google.auth.transport import requests as grequests

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/datastore"])
        creds.refresh(grequests.Request())  # type: ignore[no-untyped-call]
        return {"Authorization": f"Bearer {creds.token}"}

    def get(self, uid: str) -> dict[str, Any]:
        r = self._http.get(f"{self._url}/{uid}", headers=self._headers())
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        loaded = json.loads(r.json()["fields"]["prefs"]["stringValue"])
        return loaded if isinstance(loaded, dict) else {}

    def put(self, uid: str, prefs: dict[str, Any]) -> None:
        body = {"fields": {"prefs": {"stringValue": json.dumps(prefs)}}}
        r = self._http.patch(f"{self._url}/{uid}", json=body, headers=self._headers())
        r.raise_for_status()
