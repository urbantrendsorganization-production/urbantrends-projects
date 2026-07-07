// Shared types + helpers for the reviewer console. Mirrors the backend DTOs
// (CLAUDE.md §7). Hand-written for now; the OpenAPI-generated client lands later.

export type Status =
  | "draft"
  | "submitted"
  | "under_review"
  | "approved"
  | "rejected"
  | "returned_for_correction";

export type ApplicationSummary = {
  id: string;
  client_id: string;
  agent_id: string;
  branch_id: string;
  product_code: string;
  status: Status;
  otp_verified: boolean;
  consent_given: boolean;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Paginated<T> = {
  data: T[];
  meta: { page: number; per_page: number; total: number };
};

export type ClientDetail = {
  id: string;
  full_name: string;
  phone: string | null;
  national_id_number: string | null;
  kra_pin: string | null;
  date_of_birth: string | null;
  address: string | null;
  next_of_kin: unknown;
  client_number: string | null;
};

export type DocumentDetail = {
  id: string;
  doc_type: string;
  content_type: string;
  size_bytes: number;
  processed: boolean;
  url: string;
  thumbnail_url: string | null;
  uploaded_at: string;
};

export type EventDetail = {
  from_status: string | null;
  to_status: string;
  reason: string | null;
  created_at: string;
};

export type ApplicationDetail = {
  application: ApplicationSummary;
  client: ClientDetail;
  documents: DocumentDetail[];
  events: EventDetail[];
};

const LABELS: Record<Status, string> = {
  draft: "Draft",
  submitted: "Submitted",
  under_review: "Under review",
  approved: "Approved",
  rejected: "Rejected",
  returned_for_correction: "Returned",
};

const CLASSES: Record<Status, string> = {
  draft: "bg-muted text-muted-foreground",
  submitted: "bg-blue-100 text-blue-800",
  under_review: "bg-amber-100 text-amber-900",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
  returned_for_correction: "bg-orange-100 text-orange-900",
};

export function statusLabel(s: Status): string {
  return LABELS[s] ?? s;
}

export function statusClass(s: Status): string {
  return CLASSES[s] ?? "bg-muted text-muted-foreground";
}

// --- Admin (Phase 4) ---

export type Role = "agent" | "reviewer" | "admin";

export type Branch = {
  id: string;
  name: string;
  code: string;
  created_at: string;
};

export type Product = {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
  created_at: string;
};

export type User = {
  id: string;
  branch_id: string | null;
  full_name: string;
  phone: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string;
};

// --- Reports (Phase 4) ---

export type AgentStat = {
  agent_id: string;
  agent_name: string;
  total: number;
  approved: number;
};

export type BranchStat = {
  branch_id: string;
  branch_name: string;
  total: number;
};

export type RejectionReason = { reason: string; count: number };

export type ReportSummary = {
  per_agent: AgentStat[];
  per_branch: BranchStat[];
  rejection_reasons: RejectionReason[];
  avg_time_to_approval_secs: number | null;
};

/** Human-readable duration from seconds (used for time-to-approval). */
export function humanDuration(secs: number | null): string {
  if (secs == null) return "—";
  const h = Math.floor(secs / 3600);
  const m = Math.round((secs % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${Math.round(secs)}s`;
}

/** Fetch JSON from the authenticated proxy; throws with the API message on error. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/proxy/${path}`, { cache: "no-store", ...init });
  if (res.status === 401) {
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Session expired.");
  }
  const body = (await res.json().catch(() => null)) as unknown;
  if (!res.ok) {
    const message =
      (body as { error?: { message?: string } })?.error?.message ?? "Request failed.";
    throw new Error(message);
  }
  return body as T;
}
