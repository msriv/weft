import { api } from "./api";
import type { StoryCard } from "./types";

/** The story's title for a breadcrumb, from the public story list. Falls back to a plain word. */
export async function storyTitle(id: string): Promise<string> {
  const all = await api<StoryCard[]>("/v1/stories").catch(() => null);
  return all?.find((s) => s.id === id)?.title ?? "Story";
}
