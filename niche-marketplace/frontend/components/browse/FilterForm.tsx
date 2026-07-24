"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button, Select, TextInput } from "@/components/ui";
import { CONDITIONS } from "@/lib/catalog";
import type { Category } from "@/lib/types";

/**
 * The faceted filter controls: price range, condition, location, and the
 * category-specific attribute facets. Every change is reflected in the URL, so
 * filters are shareable/bookmarkable and the server re-renders the grid.
 *
 * Rendered twice — as a persistent sidebar on desktop and inside the mobile
 * drawer — hence the optional ``onApply`` to close the drawer after a change.
 */
export function FilterForm({
  categories,
  onApply,
}: {
  categories: Category[];
  onApply?: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const selectedCategory = categories.find(
    (c) => String(c.id) === params.get("category"),
  );
  // Only enum/boolean attributes make good facets (a bounded set of choices);
  // free-text/number attributes are left to keyword search and price.
  const attributeFacets = (selectedCategory?.attribute_schema ?? []).filter(
    (field) => field.type === "enum" || field.type === "boolean",
  );

  const [priceMin, setPriceMin] = useState(params.get("price_min") ?? "");
  const [priceMax, setPriceMax] = useState(params.get("price_max") ?? "");
  const [location, setLocation] = useState(params.get("location") ?? "");

  const commit = (next: URLSearchParams) => {
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
    onApply?.();
  };

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    commit(next);
  };

  const toggleCondition = (value: string) => {
    const next = new URLSearchParams(params.toString());
    const current = next.getAll("condition");
    next.delete("condition");
    const updated = current.includes(value)
      ? current.filter((c) => c !== value)
      : [...current, value];
    updated.forEach((c) => next.append("condition", c));
    commit(next);
  };

  const applyText = () => {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of [
      ["price_min", priceMin],
      ["price_max", priceMax],
      ["location", location],
    ] as const) {
      if (value.trim()) next.set(key, value.trim());
      else next.delete(key);
    }
    commit(next);
  };

  const activeConditions = params.getAll("condition");

  return (
    <div className="space-y-6 text-sm">
      <Section title="Price (KES)">
        <div className="flex items-center gap-2">
          <TextInput
            inputMode="numeric"
            placeholder="Min"
            value={priceMin}
            onChange={(e) => setPriceMin(e.target.value)}
            className="h-10"
          />
          <span className="text-neutral-400">–</span>
          <TextInput
            inputMode="numeric"
            placeholder="Max"
            value={priceMax}
            onChange={(e) => setPriceMax(e.target.value)}
            className="h-10"
          />
        </div>
      </Section>

      <Section title="Condition">
        <div className="space-y-1.5">
          {CONDITIONS.map((c) => (
            <label key={c.value} className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={activeConditions.includes(c.value)}
                onChange={() => toggleCondition(c.value)}
                className="h-4 w-4 rounded border-neutral-300 text-brand focus:ring-brand/30"
              />
              <span className="text-neutral-700">{c.label}</span>
            </label>
          ))}
        </div>
      </Section>

      <Section title="Location">
        <TextInput
          placeholder="e.g. Nairobi"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          className="h-10"
        />
      </Section>

      {attributeFacets.length ? (
        <Section title={`${selectedCategory?.name} details`}>
          <div className="space-y-3">
            {attributeFacets.map((field) => {
              const key = `attr_${field.key}`;
              const value = params.get(key) ?? "";
              if (field.type === "enum" && field.options) {
                return (
                  <Facet key={field.key} label={field.label}>
                    <Select
                      value={value}
                      onChange={(e) => setParam(key, e.target.value || null)}
                      className="h-10"
                    >
                      <option value="">Any</option>
                      {field.options.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </Select>
                  </Facet>
                );
              }
              if (field.type === "boolean") {
                return (
                  <Facet key={field.key} label={field.label}>
                    <Select
                      value={value}
                      onChange={(e) => setParam(key, e.target.value || null)}
                      className="h-10"
                    >
                      <option value="">Any</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </Select>
                  </Facet>
                );
              }
              return null;
            })}
          </div>
        </Section>
      ) : null}

      <Button onClick={applyText} className="w-full">
        Apply filters
      </Button>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
        {title}
      </h3>
      {children}
    </div>
  );
}

function Facet({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-neutral-500">{label}</span>
      {children}
    </label>
  );
}
