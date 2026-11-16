import AskPanel from "@/components/AskPanel";
import { Kicker } from "@/components/bits";

export default function Ask() {
  return (
    <>
      <Kicker>Ask</Kicker>
      <h1>Ask about the coverage</h1>
      <p className="muted">To ask about one story, open it and use Ask in the bar at the bottom of the page.</p>
      <AskPanel />
    </>
  );
}
