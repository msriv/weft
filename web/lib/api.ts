// Server-side fetch of the Weft API. Public pages reuse a response for 30 s (the API caches for
// the same time and the graph changes in minutes). Pass `fresh` for admin and per-reader calls.
const API = process.env.API_URL ?? "http://localhost:8080";

export async function api<T>(path: string, fresh = false): Promise<T | null> {
  const r = await fetch(`${API}${path}`, fresh ? { cache: "no-store" } : { next: { revalidate: 30 } });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`API ${path}: ${r.status}`);
  return (await r.json()) as T;
}
