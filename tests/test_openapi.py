"""The committed OpenAPI file (and the TypeScript generated from it) must match the response
models; run `python -m services.api.openapi && (cd web && npm run gen:types)` after changing one."""

import json

from services.api import openapi


def test_committed_openapi_matches_the_response_models() -> None:
    committed = openapi.PATH.read_text()
    assert committed == openapi.text(), "stale: python -m services.api.openapi && npm run gen:types"


def test_documented_routes_name_their_models() -> None:
    paths = json.loads(openapi.PATH.read_text())["paths"]
    for route, model in (
        ("/v1/stories/{story_id}", "StoryGraphOut"),
        ("/v1/events/{event_id}", "EventPageOut"),
        ("/v1/today", "TodayOut"),
        ("/v1/world", "WorldOut"),
    ):
        ok = paths[route]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert model in json.dumps(ok), route
