// Server-side fetch of the Weft API. Never cached: what a page shows must match the graph.
const API = process.env.API_URL ?? "http://localhost:8080";

export async function api<T>(path: string): Promise<T | null> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`API ${path}: ${r.status}`);
  return (await r.json()) as T;
}
