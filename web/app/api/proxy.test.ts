import { afterEach, describe, expect, it, vi } from "vitest";
import { POST as auth } from "./auth/[action]/route";
import { GET, POST } from "./[...path]/route";

afterEach(() => vi.unstubAllGlobals());

const stub = () => {
  const f = vi.fn(async (..._a: unknown[]) => new Response('{"ok":1}', { status: 201, headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", f);
  return f;
};

describe("api proxy", () => {
  it("passes content-type and authorization, drops other headers, keeps the query", async () => {
    const f = stub();
    const r = await GET(new Request("http://x/api/v1/stories?sort=recent", { headers: { authorization: "Bearer t", cookie: "s=1", "x-other": "1" } }), { params: Promise.resolve({ path: ["v1", "stories"] }) });
    expect(r.status).toBe(201);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/v1\/stories\?sort=recent$/);
    const h = init.headers as Headers;
    expect(h.get("authorization")).toBe("Bearer t");
    expect(h.get("cookie")).toBeNull();
    expect(h.get("x-other")).toBeNull();
  });
  it("forwards a body on POST", async () => {
    const f = stub();
    await POST(new Request("http://x/api/v1/ask", { method: "POST", body: '{"q":"a"}', headers: { "content-type": "application/json" } }), { params: Promise.resolve({ path: ["v1", "ask"] }) });
    const init = (f.mock.calls as unknown as [string, RequestInit][])[0][1];
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(ArrayBuffer);
  });
});

describe("auth proxy", () => {
  it("returns 404 for an unknown action without calling out", async () => {
    const f = stub();
    const r = await auth(new Request("http://x/api/auth/nope", { method: "POST", body: "{}" }), { params: Promise.resolve({ action: "nope" }) });
    expect(r.status).toBe(404);
    expect(f).not.toHaveBeenCalled();
  });
  it("maps a sign-in response to the app's fields", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ idToken: "i", refreshToken: "r", email: "a@b.c", expiresIn: "60" })));
    const r = await auth(new Request("http://x", { method: "POST", body: JSON.stringify({ email: "a@b.c", password: "pw" }) }), { params: Promise.resolve({ action: "signin" }) });
    expect(await r.json()).toEqual({ idToken: "i", refreshToken: "r", email: "a@b.c", expiresIn: 60 });
  });
});
