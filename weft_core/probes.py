"""Health endpoints for Cloud Run probes and the compose healthcheck (#165)."""

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from weft_core.store import Db


def add_probes(app: FastAPI, db: Db | None) -> None:
    """`/healthz`: the process is up. `/readyz`: the graph answers (always ready without one)."""

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/readyz")
    def readyz() -> Any:
        try:
            if db is not None:
                db.execute("RETURN 1 AS ok")
        except Exception:  # noqa: BLE001 - any failure means not ready
            return JSONResponse({"ok": False}, status_code=503)
        return {"ok": True}
