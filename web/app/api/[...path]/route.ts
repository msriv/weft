// Same-origin proxy to the Weft API, so the browser needs no CORS and API_URL is read at run time.
const API = () => process.env.API_URL ?? "http://localhost:8080";

async function proxy(req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const url = new URL(req.url);
  const headers = new Headers();
  for (const h of ["content-type", "authorization"]) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  // The API limits callers by address. It trusts this one only with the shared secret, so a
  // direct caller cannot forge it. Cloud Run appends the real peer last in x-forwarded-for.
  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",").at(-1)?.trim();
  if (ip && process.env.PROXY_SECRET) {
    headers.set("x-weft-client-ip", ip);
    headers.set("x-weft-proxy", process.env.PROXY_SECRET);
  }
  const hasBody = !["GET", "HEAD"].includes(req.method);
  const r = await fetch(`${API()}/${path.join("/")}${url.search}`, {
    method: req.method, headers, body: hasBody ? await req.arrayBuffer() : undefined, cache: "no-store",
  });
  return new Response(r.body, { status: r.status, headers: { "content-type": r.headers.get("content-type") ?? "application/json" } });
}
export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
