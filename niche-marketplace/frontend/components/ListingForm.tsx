"use client";

import { useMemo, useState } from "react";

import { Button, Field, Select, Textarea, TextInput } from "@/components/ui";
import { CONDITIONS, categoryOptions } from "@/lib/catalog";
import type { AttributeField, Category } from "@/lib/types";

export type ListingFormValues = {
  category: number | "";
  title: string;
  description: string;
  price: string;
  currency: string;
  condition: string;
  location: string;
  attributes: Record<string, string | number | boolean>;
};

const EMPTY: ListingFormValues = {
  category: "",
  title: "",
  description: "",
  price: "",
  currency: "KES",
  condition: "good",
  location: "",
  attributes: {},
};

/** Coerce a raw form value into the type the API expects for an attribute. */
function coerce(field: AttributeField, raw: string | boolean): string | number | boolean {
  if (field.type === "boolean") return Boolean(raw);
  if (field.type === "number") return raw === "" ? "" : Number(raw);
  return raw as string;
}

export function ListingForm({
  categories,
  initial,
  submitLabel,
  submitting,
  onSubmit,
  children,
}: {
  categories: Category[];
  initial?: Partial<ListingFormValues>;
  submitLabel: string;
  submitting: boolean;
  onSubmit: (values: ListingFormValues) => void;
  children?: React.ReactNode;
}) {
  const [values, setValues] = useState<ListingFormValues>({
    ...EMPTY,
    ...initial,
    attributes: { ...EMPTY.attributes, ...initial?.attributes },
  });

  const options = useMemo(() => categoryOptions(categories), [categories]);
  const selectedCategory = categories.find((c) => c.id === values.category);
  const schema = selectedCategory?.attribute_schema ?? [];

  const set = <K extends keyof ListingFormValues>(key: K, value: ListingFormValues[K]) =>
    setValues((v) => ({ ...v, [key]: value }));

  const setAttr = (field: AttributeField, raw: string | boolean) =>
    setValues((v) => ({
      ...v,
      attributes: { ...v.attributes, [field.key]: coerce(field, raw) },
    }));

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Drop empty attribute values so optional fields don't fail validation.
    const attributes = Object.fromEntries(
      Object.entries(values.attributes).filter(([, v]) => v !== "" && v !== undefined),
    );
    onSubmit({ ...values, attributes });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Field label="Category">
        <Select
          required
          value={values.category}
          onChange={(e) => set("category", e.target.value ? Number(e.target.value) : "")}
        >
          <option value="">Select a category…</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>

      <Field label="Title">
        <TextInput
          required
          maxLength={140}
          value={values.title}
          onChange={(e) => set("title", e.target.value)}
          placeholder="e.g. iPhone 13, 128GB, unlocked"
        />
      </Field>

      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-2">
          <Field label="Price">
            <TextInput
              required
              type="number"
              min="0"
              step="0.01"
              value={values.price}
              onChange={(e) => set("price", e.target.value)}
              placeholder="0.00"
            />
          </Field>
        </div>
        <Field label="Currency">
          <TextInput
            value={values.currency}
            onChange={(e) => set("currency", e.target.value.toUpperCase())}
            maxLength={3}
          />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Condition">
          <Select value={values.condition} onChange={(e) => set("condition", e.target.value)}>
            {CONDITIONS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Location">
          <TextInput
            value={values.location}
            onChange={(e) => set("location", e.target.value)}
            placeholder="City, area"
          />
        </Field>
      </div>

      <Field label="Description">
        <Textarea
          rows={4}
          value={values.description}
          onChange={(e) => set("description", e.target.value)}
          placeholder="Condition, specs, why you're selling…"
        />
      </Field>

      {schema.length > 0 ? (
        <fieldset className="space-y-4 rounded-xl border border-neutral-200 p-4">
          <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-neutral-500">
            {selectedCategory?.name} details
          </legend>
          {schema.map((field) => (
            <AttributeInput
              key={field.key}
              field={field}
              value={values.attributes[field.key]}
              onChange={(raw) => setAttr(field, raw)}
            />
          ))}
        </fieldset>
      ) : null}

      {children}

      <Button type="submit" disabled={submitting} className="w-full">
        {submitting ? "Saving…" : submitLabel}
      </Button>
    </form>
  );
}

function AttributeInput({
  field,
  value,
  onChange,
}: {
  field: AttributeField;
  value: string | number | boolean | undefined;
  onChange: (raw: string | boolean) => void;
}) {
  const label = field.label + (field.required ? " *" : "");

  if (field.type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-sm font-medium text-neutral-700">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 rounded border-neutral-300 text-brand focus:ring-brand"
        />
        {label}
      </label>
    );
  }

  if (field.type === "enum") {
    return (
      <Field label={label}>
        <Select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          <option value="">Select…</option>
          {(field.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </Select>
      </Field>
    );
  }

  return (
    <Field label={label}>
      <TextInput
        type={field.type === "number" ? "number" : "text"}
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
        required={field.required}
      />
    </Field>
  );
}
