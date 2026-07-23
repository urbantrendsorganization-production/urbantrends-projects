// Shared catalog helpers used by client components.
import { PUBLIC_API_BASE } from "@/lib/config";
import type { Category, Condition, Paginated } from "@/lib/types";

export const CONDITIONS: { value: Condition; label: string }[] = [
  { value: "new", label: "New" },
  { value: "like_new", label: "Like new" },
  { value: "good", label: "Good" },
  { value: "fair", label: "Fair" },
  { value: "for_parts", label: "For parts / not working" },
];

/** Fetch all categories from the browser. */
export async function fetchCategories(): Promise<Category[]> {
  const res = await fetch(`${PUBLIC_API_BASE}/api/v1/categories/?limit=500`);
  if (!res.ok) return [];
  const data = (await res.json()) as Paginated<Category>;
  return data.results;
}

/** Order categories as a tree and indent leaf names for a flat <select>. */
export function categoryOptions(
  categories: Category[],
): { id: number; label: string }[] {
  const byParent = new Map<number | null, Category[]>();
  for (const cat of categories) {
    const list = byParent.get(cat.parent) ?? [];
    list.push(cat);
    byParent.set(cat.parent, list);
  }
  const out: { id: number; label: string }[] = [];
  const walk = (parent: number | null, depth: number) => {
    for (const cat of byParent.get(parent) ?? []) {
      out.push({ id: cat.id, label: `${"— ".repeat(depth)}${cat.name}` });
      walk(cat.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

export function formatPrice(price: string | number, currency: string): string {
  const amount = typeof price === "string" ? Number(price) : price;
  if (Number.isNaN(amount)) return `${currency} ${price}`;
  return `${currency} ${amount.toLocaleString(undefined, {
    maximumFractionDigits: 0,
  })}`;
}
