import Link from "next/link";

export default function NotFound() {
  return (
    <>
      <p className="kicker">Not found</p>
      <h1>No public page here</h1>
      <p className="muted">This address does not exist, or the story has not been published.</p>
      <Link href="/stories">Back to all stories</Link>
    </>
  );
}
