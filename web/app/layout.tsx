import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Weft",
  description: "Who reported what, when, and from where. Weft never claims what is true.",
  manifest: "/manifest.webmanifest",
};

const LINKS: [string, string][] = [
  ["/", "Today"], ["/world", "World"], ["/stories", "Stories"], ["/sources", "Sources"],
  ["/ask", "Ask"], ["/method", "How we weigh"], ["/admin", "Admin"],
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter:wght@400;500&family=IBM+Plex+Mono:wght@400;500&display=swap"
        />
        <meta name="theme-color" content="#060708" />
      </head>
      <body>
        <nav className="nav" aria-label="Main">
          <Link href="/" className="brand">Weft</Link>
          {LINKS.map(([href, label]) => <Link key={href} href={href}>{label}</Link>)}
        </nav>
        <main className="wrap">{children}</main>
      </body>
    </html>
  );
}
