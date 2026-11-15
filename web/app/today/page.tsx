import TodayView from "@/components/TodayView";
import { Kicker } from "@/components/bits";
import { api } from "@/lib/api";
import { meta } from "@/lib/meta";
import type { StoryCard } from "@/lib/types";

export const metadata = meta("Today", "What is new in the stories Weft tracks.");

export default async function TodayPage() {
  const all = await api<StoryCard[]>("/v1/stories");
  return (
    <>
      <Kicker>Today</Kicker>
      <h1>What is new</h1>
      <p>Who reported what, when, and from where. Weft shows coverage; it never says what is true.</p>
      <TodayView stories={all ?? []} />
    </>
  );
}
