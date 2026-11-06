"use client";
import { useEffect, useState } from "react";
import { loadPrefs, savePrefs } from "@/lib/prefs";

export default function FollowButton({ beat }: { beat: string }) {
  const [on, setOn] = useState(false);
  useEffect(() => setOn(loadPrefs().follows.includes(beat)), [beat]);
  return (
    <button
      aria-pressed={on}
      onClick={() => {
        const p = loadPrefs();
        p.follows = on ? p.follows.filter((b) => b !== beat) : [...p.follows, beat];
        savePrefs(p);
        setOn(!on);
      }}
    >
      {on ? "Following" : "Follow"}
    </button>
  );
}
