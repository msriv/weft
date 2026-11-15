import Link from "next/link";
import { perspectiveName } from "@/lib/format";
import type { Side } from "@/lib/story";

const Col = ({ s }: { s: Side }) => (
  <div>
    <p className="m0">{s.claim}</p>
    <p className="muted fs12 my4">
      {s.perspectives.length ? `Carried by ${s.perspectives.map(perspectiveName).join(", ")}` : "Perspectives not recorded"}
      {s.outlets.length ? ` · ${s.outlets.join(", ")}` : ""}
    </p>
  </div>
);

/** One conflict as two columns, claim A against claim B, with a link to the event. Reports
 * disagree here; Weft does not say which is right. */
export default function Conflict({ a, b, href }: { a: Side; b: Side; href: string }) {
  return (
    <div className="card anomaly conflict">
      <div className="kicker anomaly">Reports conflict on</div>
      <div className="conflict-cols">
        <Col s={a} />
        <div className="muted conflict-vs" aria-hidden="true">versus</div>
        <Col s={b} />
      </div>
      <Link href={href}>Open this event</Link>
    </div>
  );
}
