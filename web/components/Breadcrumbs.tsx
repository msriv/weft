import Link from "next/link";

export type Crumb = { label: string; href?: string };

/** Where this page sits: Stories › story › event. The last crumb is the current page. */
export default function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="crumbs">
      <ol>
        {items.map((c, i) => (
          <li key={i} aria-current={i === items.length - 1 ? "page" : undefined}>
            {c.href && i < items.length - 1 ? <Link href={c.href}>{c.label}</Link> : <span>{c.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}
