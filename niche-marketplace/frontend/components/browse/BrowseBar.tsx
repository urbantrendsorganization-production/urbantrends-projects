"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Select } from "@/components/ui";
import { SORT_OPTIONS } from "@/lib/browse";
import type { Category } from "@/lib/types";

import { FilterForm } from "./FilterForm";

export function BrowseBar({ categories }: { categories: Category[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const roots = categories.filter((c) => c.parent === null);
  const selectedId = params.get("category");
  const selected = categories.find((c) => String(c.id) === selectedId);
  const activeRoot = selected ? rootOf(selected, categories) : null;
  const children = activeRoot
    ? categories.filter((c) => c.parent === activeRoot.id)
    : [];

  const push = (next: URLSearchParams) => {
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  };

  const selectCategory = (id: number | null) => {
    const next = new URLSearchParams(params.toString());
    // A different category means a different attribute schema — drop stale
    // attribute facets and the cursor.
    for (const key of [...next.keys()]) {
      if (key.startsWith("attr_")) next.delete(key);
    }
    next.delete("cursor");
    if (id === null) next.delete("category");
    else next.set("category", String(id));
    push(next);
  };

  const submitSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = new FormData(event.currentTarget).get("q");
    const next = new URLSearchParams(params.toString());
    if (typeof value === "string" && value.trim()) next.set("q", value.trim());
    else next.delete("q");
    next.delete("cursor");
    push(next);
  };

  const setSort = (value: string) => {
    const next = new URLSearchParams(params.toString());
    next.set("sort", value);
    next.delete("cursor");
    push(next);
  };

  const activeFilterCount = countFacets(params);

  return (
    <div className="space-y-4">
      <form onSubmit={submitSearch} className="flex gap-2">
        <div className="relative flex-1">
          <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-400">
            ⌕
          </span>
          <input
            name="q"
            type="search"
            defaultValue={params.get("q") ?? ""}
            placeholder="Search listings…"
            className="h-11 w-full rounded-xl border border-neutral-300 bg-white pl-9 pr-3.5 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
          />
        </div>
        {/* Filters button — opens the drawer on mobile only. */}
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          className="inline-flex h-11 shrink-0 items-center gap-1.5 rounded-xl border border-neutral-300 bg-white px-4 text-sm font-semibold text-neutral-700 hover:bg-neutral-50 lg:hidden"
        >
          Filters
          {activeFilterCount ? (
            <span className="rounded-full bg-brand px-1.5 text-xs text-white">
              {activeFilterCount}
            </span>
          ) : null}
        </button>
      </form>

      {/* Category navigation. */}
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
        <Chip active={!selectedId} onClick={() => selectCategory(null)}>
          All
        </Chip>
        {roots.map((root) => (
          <Chip
            key={root.id}
            active={activeRoot?.id === root.id}
            onClick={() => selectCategory(root.id)}
          >
            {root.name}
          </Chip>
        ))}
      </div>
      {children.length ? (
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
          {children.map((child) => (
            <Chip
              key={child.id}
              small
              active={String(child.id) === selectedId}
              onClick={() => selectCategory(child.id)}
            >
              {child.name}
            </Chip>
          ))}
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <p className="text-sm text-neutral-500">
          {selected ? selected.name : "All listings"}
        </p>
        <label className="flex items-center gap-2 text-sm text-neutral-500">
          <span className="hidden sm:inline">Sort</span>
          <Select
            value={params.get("sort") ?? "newest"}
            onChange={(e) => setSort(e.target.value)}
            className="h-10 w-auto"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </label>
      </div>

      {drawerOpen ? (
        <Drawer onClose={() => setDrawerOpen(false)}>
          <FilterForm categories={categories} onApply={() => setDrawerOpen(false)} />
        </Drawer>
      ) : null}
    </div>
  );
}

function rootOf(category: Category, all: Category[]): Category {
  let node = category;
  while (node.parent !== null) {
    const parent = all.find((c) => c.id === node.parent);
    if (!parent) break;
    node = parent;
  }
  return node;
}

function countFacets(params: URLSearchParams): number {
  let count = 0;
  const seen = new Set<string>();
  for (const [key, value] of params.entries()) {
    if (!value) continue;
    if (["q", "sort", "cursor", "category"].includes(key)) continue;
    if (key === "condition") {
      if (!seen.has("condition")) {
        seen.add("condition");
        count += 1;
      }
      continue;
    }
    count += 1;
  }
  return count;
}

function Chip({
  active,
  small,
  onClick,
  children,
}: {
  active?: boolean;
  small?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`shrink-0 whitespace-nowrap rounded-full border px-3.5 ${
        small ? "py-1 text-xs" : "py-1.5 text-sm"
      } font-medium transition ${
        active
          ? "border-brand bg-brand text-white"
          : "border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400"
      }`}
    >
      {children}
    </button>
  );
}

function Drawer({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="absolute inset-y-0 right-0 flex w-[85%] max-w-sm flex-col bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
          <h2 className="text-sm font-semibold">Filters</h2>
          <button
            onClick={onClose}
            className="text-neutral-400 hover:text-neutral-700"
            aria-label="Close filters"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
