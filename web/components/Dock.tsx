"use client";
import { useEffect, useRef, useState } from "react";
import AskPanel from "./AskPanel";

type Which = "ask" | "speculation";

// Sticky bar at the bottom of a story page. Each tab opens a panel above it; both stay mounted so
// an Ask conversation survives switching tabs. `speculation` is null when detective mode is off.
export default function Dock({ storyId, speculation }: { storyId: string; speculation: React.ReactNode | null }) {
  const [open, setOpen] = useState<Which | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(null);
      bar.current?.querySelector<HTMLButtonElement>(`[data-tab="${open}"]`)?.focus();
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [open]);
  const tabs: [Which, string][] = speculation ? [["ask", "Ask"], ["speculation", "Speculation"]] : [["ask", "Ask"]];
  return (
    <>
      <div className="dock-spacer" aria-hidden="true" />
      <div className="dock">
        <div className="dock-panel" id="dock-panel-ask" role="region" aria-label="Ask about this story" hidden={open !== "ask"}>
          <AskPanel storyId={storyId} compact />
        </div>
        {speculation && (
          <div className="dock-panel" id="dock-panel-speculation" role="region" aria-label="Speculation about this story" hidden={open !== "speculation"}>
            {speculation}
          </div>
        )}
        <div className="dock-bar" ref={bar}>
          {tabs.map(([k, label]) => (
            <button key={k} type="button" data-tab={k} aria-expanded={open === k} aria-controls={`dock-panel-${k}`} onClick={() => setOpen(open === k ? null : k)}>
              {label}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
