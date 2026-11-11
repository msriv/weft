// Firebase Authentication over its REST API, proxied so the API key stays on the server and the
// local Firebase emulator (FIREBASE_AUTH_EMULATOR_HOST) works with no browser-side config.
const emu = (): string | undefined => process.env.FIREBASE_AUTH_EMULATOR_HOST;
const URLS: Record<string, [host: string, path: string]> = {
  signin: ["identitytoolkit.googleapis.com", "/v1/accounts:signInWithPassword"],
  signup: ["identitytoolkit.googleapis.com", "/v1/accounts:signUp"],
  refresh: ["securetoken.googleapis.com", "/v1/token"],
};

export async function POST(req: Request, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  const target = URLS[action];
  if (!target) return new Response("not found", { status: 404 });
  const [host, path] = target;
  // the emulator serves each Google host under its own path prefix
  const base = emu() ? `http://${emu()}/${host}` : `https://${host}`;
  const url = `${base}${path}?key=${process.env.FIREBASE_API_KEY ?? "local"}`;
  const body = await req.json();
  const r = await fetch(url, {
    method: "POST", cache: "no-store",
    headers: { "content-type": action === "refresh" ? "application/x-www-form-urlencoded" : "application/json" },
    body: action === "refresh" ? new URLSearchParams({ grant_type: "refresh_token", refresh_token: body.refreshToken }).toString()
      : JSON.stringify({ email: body.email, password: body.password, returnSecureToken: true }),
  });
  const j = await r.json();
  if (!r.ok) return Response.json({ error: j?.error?.message ?? "auth failed" }, { status: r.status });
  // sign-in/up and refresh name the same fields differently
  return Response.json({ idToken: j.idToken ?? j.id_token, refreshToken: j.refreshToken ?? j.refresh_token, email: j.email ?? body.email, expiresIn: Number(j.expiresIn ?? j.expires_in ?? 3600) });
}
