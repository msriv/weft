"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { signedInAs } from "@/lib/account";
import { SECTIONS, sectionOf } from "@/lib/nav";
import Search from "./Search";

export default function Nav({ children }: { children?: React.ReactNode }) {
  const here = sectionOf(usePathname());
  const [who, setWho] = useState<string | null>(null);
  useEffect(() => setWho(signedInAs()), []);
  return (
    <nav className="nav" aria-label="Main">
      <Link href="/" className="brand">Weft</Link>
      {SECTIONS.map((s) => <Link key={s.href} href={s.href} aria-current={here === s.href ? "page" : undefined}>{s.label}</Link>)}
      {children}
      <span className="nav-right">
        <Search />
        <Link href="/welcome" className="account" aria-label={who ? `Following and preferences (${who})` : "Following and preferences"}>
          {who ? who[0].toUpperCase() : "Following"}
        </Link>
      </span>
    </nav>
  );
}
