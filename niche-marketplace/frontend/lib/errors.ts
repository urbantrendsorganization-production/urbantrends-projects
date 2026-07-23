// Turn the API's {detail, code} error envelope into a human-readable string.
// `detail` may be a string, a field->messages map, or a nested map (e.g.
// {attributes: {brand: "This attribute is required."}}).
export function apiError(data: unknown, fallback = "Something went wrong."): string {
  const detail = (data as { detail?: unknown })?.detail ?? data;
  return flatten(detail, fallback);
}

function flatten(value: unknown, fallback: string): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.length ? flatten(value[0], fallback) : fallback;
  if (value && typeof value === "object") {
    const first = Object.values(value as Record<string, unknown>)[0];
    return first != null ? flatten(first, fallback) : fallback;
  }
  return fallback;
}
