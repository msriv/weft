import type { Metadata } from "next";

export const metadata: Metadata = { title: "About the Weft crawler", description: "How Weft's crawler behaves and how to opt out." };

export default function Bot() {
  return (
    <>
      <p className="kicker">For site owners</p>
      <h1>About the Weft crawler</h1>
      <p>
        Weft collects public reports, official documents and public proceedings so readers can see who reported what, when and
        from where. The crawler identifies itself as <code>WeftBot</code>.
      </p>
      <ul>
        <li>It reads <code>robots.txt</code> before fetching and re-reads it at least daily. It honours <code>Crawl-delay</code>.</li>
        <li>It makes one request at a time to a host and backs off when asked (<code>429</code>, <code>503</code>, <code>Retry-After</code>).</li>
        <li>It does not get around paywalls or login walls.</li>
        <li>It stores summaries and links, not full articles. Raw copies are private and deleted after 30 days.</li>
      </ul>
      <h2 style={{ marginTop: 24 }}>Opt out</h2>
      <p>
        Add <code>User-agent: WeftBot</code> and <code>Disallow: /</code> to your <code>robots.txt</code>. Weft stops fetching from your
        site on its next check.
      </p>
    </>
  );
}
