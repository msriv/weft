import Link from "next/link";
import { api } from "@/lib/api";

// Shown only when the API serves directions (detective flag on, D22).
export default async function DirectionsLink() {
  const on = await api<{ domains: unknown[] }>("/v1/directions").catch(() => null);
  return on ? <Link href="/directions">Directions</Link> : null;
}
