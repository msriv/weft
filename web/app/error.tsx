"use client";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <>
      <p className="kicker">Something went wrong</p>
      <h1>Weft could not load this page</h1>
      <p className="muted">The data service did not answer. Nothing was lost; try again in a moment.</p>
      <button onClick={reset}>Try again</button>
    </>
  );
}
