"use client";
import { useEffect, useState } from "react";
import { Empty, StoryRow } from "@/components/bits";
import { loadPrefs } from "@/lib/prefs";
import type { StoryCard } from "@/lib/types";

export default function FollowedBranches({ stories }: { stories: StoryCard[] }) {
  const [follows, setFollows] = useState<string[] | null>(null);
  useEffect(() => setFollows(loadPrefs().follows), []);
  if (follows === null) return null;
  const mine = stories.filter((s) => follows.includes(s.beat));
  return mine.length ? <>{mine.map((s) => <StoryRow key={s.id} s={s} />)}</> : <Empty>You follow no stories yet. Open a story and choose Follow.</Empty>;
}
