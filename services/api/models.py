"""Response models for the public read routes (#177). They document the JSON that
`weft_core/readmodel.py` returns; the routes do not validate against them (the `responses=`
argument only feeds the OpenAPI schema), so a model can lag the code but never break a reply.
`web/lib/api.openapi.json` and `web/lib/api.gen.ts` are generated from these; tests/test_openapi.py
and the web job fail when either is stale, and `web/lib/types.check.ts` fails when a hand-written
type in `web/lib/types.ts` no longer has the same fields."""

from typing import Any, Literal

from pydantic import BaseModel


class SourceLabel(BaseModel):
    id: str
    name: str
    homepage: str
    type: str
    country: str | None
    perspective: str
    state_run: Literal["unverified", "state-run", "not state-run"]
    state_run_source: str | None
    owner_id: str | None
    ownership_source: str | None
    paywalled: bool
    healthy: bool
    weight: float | None
    weight_insufficient: bool


class Issuer(SourceLabel):
    is_party: bool


class Party(BaseModel):
    party: str
    cited: bool
    citation: str | None


class StoryCard(BaseModel):
    id: str
    title: str
    beat: str
    beat_name: str | None = None
    status: Literal["developing", "quiet"]
    reports: int
    events: int
    sources: int
    perspectives: list[str]
    anomalies: int
    provisional_anomalies: int
    last_report_at: str | None
    parties: list[Party]


class EvidenceRef(BaseModel):
    id: str
    outlet: str
    perspective: str
    published_at: str | None


class Anomaly(BaseModel):
    id: str
    rule: str
    rule_version: int
    status: Literal["active", "provisional", "withdrawn"]
    subject_kind: str
    subject_id: str
    story_id: str | None
    event_id: str | None
    summary: str
    inputs: dict[str, Any]
    evidence_ids: list[str]
    evidence: list[EvidenceRef] | None = None
    provisional_reason: str | None = None
    detail: dict[str, Any]
    since: str


class GraphNode(BaseModel):
    id: str
    kind: Literal["report_group", "document"]
    event_id: str | None
    at: str | None
    anomalies: list[str]
    perspective: str | None = None
    count: int | None = None
    sources: list[str] | None = None
    report_ids: list[str] | None = None
    title: str | None = None
    doc_kind: str | None = None
    issuer: Issuer | None = None


class GraphEdge(BaseModel):
    kind: Literal["conflict"]
    event_id: str
    groups: list[str]
    between: list[list[str]]
    nli_score: float


class StoryGraphOut(BaseModel):
    story: StoryCard
    as_of: str | None
    summary: list[str]
    perspectives: list[str]
    summary_items: list[dict[str, Any]] | None = None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    anomalies: list[Anomaly]
    events: list[dict[str, Any]]
    short_version: dict[str, Any]
    window: dict[str, Any]


class EventPageOut(BaseModel):
    event: dict[str, Any]
    voices: dict[str, dict[str, Any]]
    perspectives: dict[str, list[dict[str, Any]]]
    claim_groups: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    figures: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    anomalies: list[Anomaly]
    short_version: dict[str, Any] | None
    parties: list[Party]


class WorldOut(BaseModel):
    stories: list[dict[str, Any]]
    places: list[dict[str, Any]] | None = None
    gaps: list[dict[str, Any]]


class TodayOut(BaseModel):
    day: str | None
    since: str
    changes: list[dict[str, Any]]
    new_events: list[dict[str, Any]]
    whats_new: list[dict[str, Any]] | None = None
    new_anomalies: list[Anomaly]
    breaking: list[StoryCard]
    blind_spots: list[dict[str, Any]]
    followed: list[StoryCard]
    directions: str | None = None
