import Link from "next/link";
import Globe from "@/components/Globe";
import { Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import type { Directions, World } from "@/lib/types";

export default async function Home() {
  const w = (await api<World>("/v1/world")) ?? { stories: [], gaps: [] };
  // empty unless the detective flag is on (D22)
  const dir = await api<Directions>("/v1/directions").catch(() => null);
  const withDirections = [...new Set((dir?.domains ?? []).filter((d) => d.subject_kind === "country").map((d) => d.subject))];
  return (
    <>
      <Kicker>World desk</Kicker>
      <h1>Where the news is</h1>
      <p className="muted">Each story sits on the countries it is about; open one to see where its reports come from. Weft shows coverage; it never says what is true. <Link href="/today">See today&apos;s changes</Link>.</p>
      <Globe world={w} directions={withDirections} />
    </>
  );
}
