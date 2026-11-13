import Link from "next/link";
import { notFound } from "next/navigation";
import { Kicker } from "@/components/bits";
import { DomainCardView, SpeculationRow } from "@/components/Directions";
import { api } from "@/lib/api";
import type { DomainCard } from "@/lib/types";

export default async function DirectionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const d = await api<DomainCard & { disclaimer: string }>(`/v1/directions/${encodeURIComponent(decodeURIComponent(id))}`);
  if (!d) notFound();
  return (
    <>
      <Link href="/directions">All directions</Link>
      <p role="note"><strong>{d.disclaimer}</strong></p>
      <DomainCardView d={d} />
      <Kicker>Resolved</Kicker>
      {d.resolved.length ? d.resolved.map((p) => <SpeculationRow key={p.id} p={p} />) : <p className="muted">Nothing resolved yet.</p>}
    </>
  );
}
