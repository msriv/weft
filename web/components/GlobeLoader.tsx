"use client";
// The globe computes its drawing in the browser only, so the server and the browser can never
// disagree about it (no hydration mismatch). Without scripts the page shows a plain story list.
import dynamic from "next/dynamic";
import type { World } from "@/lib/types";

const Globe = dynamic(() => import("./Globe"), { ssr: false, loading: () => <div className="globe-placeholder" role="status">Loading the globe</div> });
export default function GlobeLoader({ world, directions }: { world: World; directions?: string[] }) {
  return <Globe world={world} directions={directions} />;
}
