"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import Status from "@/components/Status";
import { loadPrefs, savePrefs } from "@/lib/prefs";

const TOLD = "weft:follow-told";

/** Follows the story's beat. The first time, it says what following does and where it is kept. */
export default function FollowButton({ beat, name }: { beat: string; name?: string }) {
  const [on, setOn] = useState(false);
  const [told, setTold] = useState(false);
  useEffect(() => setOn(loadPrefs().follows.includes(beat)), [beat]);
  const what = name ? ` ${name}` : "";
  return (
    <>
      <button
        aria-pressed={on}
        onClick={() => {
          const p = loadPrefs();
          p.follows = on ? p.follows.filter((b) => b !== beat) : [...p.follows, beat];
          savePrefs(p);
          setOn(!on);
          if (!on && !localStorage.getItem(TOLD)) { localStorage.setItem(TOLD, "1"); setTold(true); } else setTold(false);
        }}
      >
        {on ? `Following${what}` : `Follow${what}`}
      </button>
      <Status kind="ok">{told && "Following. New events in these stories appear first on Today. Kept in this browser unless you sign in."}</Status>
      {on && <Link href="/today" className="fs13">Today</Link>}
      {on && <Link href="/welcome" className="fs13">Following and preferences</Link>}
    </>
  );
}
