// Fails `tsc` when a hand-written type in types.ts and the API's response model (generated into
// api.gen.ts from services/api/models.py) no longer have the same field names (#177).
import type { components } from "./api.gen";
import type * as T from "./types";

type S = components["schemas"];
type Same<A, B> = [Exclude<keyof A, keyof B>, Exclude<keyof B, keyof A>] extends [never, never] ? true : false;
type Assert<X extends true> = X;

export type FieldChecks = [
  Assert<Same<T.SourceLabel, S["SourceLabel"]>>,
  Assert<Same<T.Issuer, S["Issuer"]>>,
  Assert<Same<T.Party, S["Party"]>>,
  Assert<Same<T.StoryCard, S["StoryCard"]>>,
  Assert<Same<T.Anomaly, S["Anomaly"]>>,
  Assert<Same<T.GraphNode, S["GraphNode"]>>,
  Assert<Same<T.GraphEdge, S["GraphEdge"]>>,
  Assert<Same<T.StoryGraph, S["StoryGraphOut"]>>,
  Assert<Same<T.EventPage, S["EventPageOut"]>>,
  Assert<Same<T.World, S["WorldOut"]>>,
  Assert<Same<T.Today, S["TodayOut"]>>,
];
