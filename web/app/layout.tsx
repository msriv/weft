import type { Metadata } from "next";
import Link from "next/link";
import DirectionsLink from "@/components/DirectionsLink";
import Nav from "@/components/Nav";
import { IBM_Plex_Mono, Inter, Instrument_Serif } from "next/font/google";
import "./globals.css";

const serif = Instrument_Serif({ subsets: ["latin"], weight: "400", variable: "--font-serif", display: "swap" });
const sans = Inter({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-sans", display: "swap" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Weft", template: "%s · Weft" },
  description: "Who reported what, when, and from where. Weft never claims what is true.",
  manifest: "/manifest.webmanifest",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable} ${mono.variable}`}>
      <head>
        <meta name="theme-color" content="#060708" />
      </head>
      <body>
        <a className="skip" href="#main">Skip to content</a>
        <Nav><DirectionsLink /></Nav>
        <main id="main" className="wrap">{children}</main>
        <footer className="footer">
          <p className="m0">Weft shows who reported what, when and from where. It collects coverage; it does not say what is true.</p>
          <div className="row">
            <Link href="/method">How we weigh</Link>
            <Link href="/method#corrections">Corrections</Link>
            <Link href="/admin">Admin</Link>
          </div>
        </footer>
      </body>
    </html>
  );
}
