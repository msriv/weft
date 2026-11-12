import Link from "next/link";
import Globe from "@/components/Globe";
import { Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import type { World } from "@/lib/types";

export default async function Home() {
  const w = (await api<World>("/v1/world")) ?? { stories: [], gaps: [] };
  return (
    <>
      <Kicker>World desk</Kicker>
      <h1>Where the reporting comes from</h1>
      <p className="muted">Who reported what, and from where. Weft shows coverage; it never says what is true. <Link href="/today">See today&apos;s changes</Link>.</p>
      <Globe world={w} />
    </>
  );
}
