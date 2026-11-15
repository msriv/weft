import { ago, date } from "@/lib/format";

/** A date as words in a <time> element. The exact time is in `title` and `dateTime`. `relative` shows "3 h ago". */
export default function Time({ iso, relative }: { iso: string | null; relative?: boolean }) {
  if (!iso) return null;
  const exact = new Date(iso).toUTCString().replace("GMT", "UTC");
  return <time dateTime={iso} title={exact}>{relative ? ago(iso) : date(iso)}</time>;
}
