import type { Metadata } from "next";
import Link from "next/link";
import DirectionsLink from "@/components/DirectionsLink";
import { IBM_Plex_Mono, Inter, Instrument_Serif } from "next/font/google";
import "./globals.css";

// Rendered per request: the build has no API to read. api() still reuses responses for 30 s.
export const dynamic = "force-dynamic";
const serif = Instrument_Serif({ subsets: ["latin"], weight: "400", variable: "--font-serif", display: "swap" });
const sans = Inter({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-sans", display: "swap" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Weft", template: "%s · Weft" },
  description: "Who reported what, when, and from where. Weft never claims what is true.",
  manifest: "/manifest.webmanifest",
};

const LINKS: [string, string][] = [
  ["/", "Globe"], ["/today", "Today"], ["/world", "Threads"], ["/stories", "Stories"], ["/sources", "Sources"],
  ["/ask", "Ask"], ["/method", "How we weigh"], ["/admin", "Admin"],
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable} ${mono.variable}`}>
      <head>
        <meta name="theme-color" content="#060708" />
      </head>
      <body>
        <nav className="nav" aria-label="Main">
          <Link href="/" className="brand">Weft</Link>
          {LINKS.map(([href, label]) => <Link key={href} href={href}>{label}</Link>)}
          <DirectionsLink />
        </nav>
        <main className="wrap">{children}</main>
      </body>
    </html>
  );
}
