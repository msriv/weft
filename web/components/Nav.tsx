"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { signedInAs } from "@/lib/account";
import { SECTIONS, sectionOf } from "@/lib/nav";
import Search from "./Search";

export default function Nav({ children }: { children?: React.ReactNode }) {
  const here = sectionOf(usePathname());
  const [who, setWho] = useState<string | null>(null);
  useEffect(() => setWho(signedInAs()), []);
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const path = usePathname();
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); toggle.current?.focus(); } };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [open]);
  return (
    <nav className="nav" aria-label="Main" data-open={open}>
      <Link href="/" className="brand">Weft</Link>
      <button ref={toggle} type="button" className="nav-toggle" aria-expanded={open} aria-controls="nav-links" onClick={() => setOpen(!open)}>{open ? "Close" : "Menu"}</button>
      <span id="nav-links" className="nav-links">
      {SECTIONS.map((s) => <Link key={s.href} href={s.href} aria-current={here === s.href ? "page" : undefined}>{s.label}</Link>)}
      {children}
      </span>
      <span className="nav-right">
        <Search />
        <Link href="/welcome" className="account" aria-label={who ? `Following and preferences (${who})` : "Following and preferences"}>
          {who ? who[0].toUpperCase() : "Following"}
        </Link>
      </span>
    </nav>
  );
}
