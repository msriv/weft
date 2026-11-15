"use client";
// The Admin link shows only for a signed-in admin; guests and other readers never see it.
import Link from "next/link";
import { useEffect, useState } from "react";
import { adminHeaders } from "@/lib/account";

export default function AdminLink() {
  const [on, setOn] = useState(false);
  useEffect(() => { void adminHeaders().then((h) => setOn(h !== null)); }, []);
  return on ? <Link href="/admin">Admin</Link> : null;
}
