// Reader-facing messages for failures. Raw codes ("EMAIL_NOT_FOUND") are never shown.
const AUTH: [RegExp, string][] = [
  [/EMAIL_NOT_FOUND|INVALID_PASSWORD|INVALID_LOGIN_CREDENTIALS/, "That email and password do not match an account."],
  [/EMAIL_EXISTS/, "An account with that email already exists. Try signing in."],
  [/WEAK_PASSWORD/, "Choose a password of at least 6 characters."],
  [/INVALID_EMAIL|MISSING_EMAIL/, "Enter a valid email address."],
  [/MISSING_PASSWORD/, "Enter your password."],
  [/TOO_MANY_ATTEMPTS/, "Too many attempts. Wait a few minutes and try again."],
  [/USER_DISABLED/, "This account has been disabled."],
];
export function authMessage(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err ?? "");
  return AUTH.find(([re]) => re.test(raw))?.[1] ?? "Could not sign in. Check your connection and try again.";
}

export function askMessage(status: number): string {
  if (status === 429) return "You have asked a lot of questions in a short time. Wait a minute and ask again.";
  if (status === 0) return "Could not reach Weft. Check your connection and try again.";
  return "Could not answer that. Try again.";
}

/** Citation numbers run across the whole answer, in order of first use, so [2] is one source throughout. */
export function citeNumbers(sentences: { cites: string[] }[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const s of sentences) for (const c of s.cites) if (!m.has(c)) m.set(c, m.size + 1);
  return m;
}
