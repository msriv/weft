import type { MetadataRoute } from "next";

// Disallow all until the owner decides the site is public (SITE_INDEXABLE=on).
export default function robots(): MetadataRoute.Robots {
  return process.env.SITE_INDEXABLE === "on"
    ? { rules: { userAgent: "*", allow: "/", disallow: ["/admin", "/api"] } }
    : { rules: { userAgent: "*", disallow: "/" } };
}
