"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  api,
  type Branch,
  type Product,
  type Role,
  type User,
} from "@/lib/onboardkit";

const ROLES: Role[] = ["agent", "reviewer", "admin"];

export default function AdminPage() {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [b, p, u] = await Promise.all([
        api<Branch[]>("branches"),
        api<Product[]>("products"),
        api<User[]>("users"),
      ]);
      setBranches(b);
      setProducts(p);
      setUsers(u);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load.");
    }
  }, []);

  useEffect(() => {
    // Fetch-on-mount: `load` sets state only after its awaited requests resolve.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const branchName = (id: string | null) =>
    id ? (branches.find((b) => b.id === id)?.name ?? "—") : "—";

  async function mutate(path: string, method: string, body: unknown) {
    setError(null);
    try {
      await api(path, { method, body: JSON.stringify(body) });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed.");
    }
  }

  return (
    <main className="mx-auto max-w-5xl space-y-8 p-6">
      <header className="flex items-center justify-between">
        <div>
          <Link href="/queue" className="text-sm text-primary hover:underline">
            ← Back to queue
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">Admin</h1>
        </div>
        <Link href="/reports" className="text-sm text-primary hover:underline">
          Reports →
        </Link>
      </header>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {/* Branches */}
      <Section title="Branches">
        <Table head={["Name", "Code", "Created"]}>
          {branches.map((b) => (
            <tr key={b.id} className="border-t">
              <Td>{b.name}</Td>
              <Td>{b.code}</Td>
              <Td muted>{new Date(b.created_at).toLocaleDateString()}</Td>
            </tr>
          ))}
        </Table>
        <CreateForm
          fields={[
            { name: "name", placeholder: "Name" },
            { name: "code", placeholder: "Code" },
          ]}
          onSubmit={(v) => mutate("branches", "POST", v)}
        />
      </Section>

      {/* Products */}
      <Section title="Products">
        <Table head={["Code", "Name", "Active", ""]}>
          {products.map((p) => (
            <tr key={p.id} className="border-t">
              <Td>{p.code}</Td>
              <Td>{p.name}</Td>
              <Td muted>{p.is_active ? "Yes" : "No"}</Td>
              <Td>
                <button
                  className="text-primary hover:underline"
                  onClick={() =>
                    mutate(`products/${p.id}`, "PATCH", { is_active: !p.is_active })
                  }
                >
                  {p.is_active ? "Deactivate" : "Activate"}
                </button>
              </Td>
            </tr>
          ))}
        </Table>
        <CreateForm
          fields={[
            { name: "code", placeholder: "Code" },
            { name: "name", placeholder: "Name" },
          ]}
          onSubmit={(v) => mutate("products", "POST", v)}
        />
      </Section>

      {/* Users */}
      <Section title="Users">
        <Table head={["Name", "Email", "Role", "Branch", "Active", ""]}>
          {users.map((u) => (
            <tr key={u.id} className="border-t">
              <Td>{u.full_name}</Td>
              <Td muted>{u.email}</Td>
              <Td>{u.role}</Td>
              <Td muted>{branchName(u.branch_id)}</Td>
              <Td muted>{u.is_active ? "Yes" : "No"}</Td>
              <Td>
                <button
                  className="text-primary hover:underline"
                  onClick={() =>
                    mutate(`users/${u.id}`, "PATCH", { is_active: !u.is_active })
                  }
                >
                  {u.is_active ? "Disable" : "Enable"}
                </button>
              </Td>
            </tr>
          ))}
        </Table>
        <UserCreateForm branches={branches} onSubmit={(v) => mutate("users", "POST", v)} />
      </Section>
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-lg font-medium">{title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-left text-muted-foreground">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="px-4 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Td({ children, muted }: { children: React.ReactNode; muted?: boolean }) {
  return <td className={`px-4 py-2 ${muted ? "text-muted-foreground" : ""}`}>{children}</td>;
}

function CreateForm({
  fields,
  onSubmit,
}: {
  fields: { name: string; placeholder: string }[];
  onSubmit: (values: Record<string, string>) => Promise<void>;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const filled = fields.every((f) => (values[f.name] ?? "").trim().length > 0);

  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        await onSubmit(values);
        setValues({});
      }}
    >
      {fields.map((f) => (
        <input
          key={f.name}
          className="rounded-md border px-3 py-1.5 text-sm"
          placeholder={f.placeholder}
          value={values[f.name] ?? ""}
          onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
        />
      ))}
      <Button type="submit" size="sm" disabled={!filled}>
        Add
      </Button>
    </form>
  );
}

function UserCreateForm({
  branches,
  onSubmit,
}: {
  branches: Branch[];
  onSubmit: (values: Record<string, unknown>) => Promise<void>;
}) {
  const empty = {
    full_name: "",
    phone: "",
    email: "",
    password: "",
    role: "agent" as Role,
    branch_id: "",
  };
  const [v, setV] = useState(empty);
  const filled =
    v.full_name.trim() && v.phone.trim() && v.email.trim() && v.password.trim();

  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        await onSubmit({
          full_name: v.full_name,
          phone: v.phone,
          email: v.email,
          password: v.password,
          role: v.role,
          branch_id: v.branch_id || null,
        });
        setV(empty);
      }}
    >
      <input
        className="rounded-md border px-3 py-1.5 text-sm"
        placeholder="Full name"
        value={v.full_name}
        onChange={(e) => setV({ ...v, full_name: e.target.value })}
      />
      <input
        className="rounded-md border px-3 py-1.5 text-sm"
        placeholder="Phone (+254…)"
        value={v.phone}
        onChange={(e) => setV({ ...v, phone: e.target.value })}
      />
      <input
        className="rounded-md border px-3 py-1.5 text-sm"
        placeholder="Email"
        value={v.email}
        onChange={(e) => setV({ ...v, email: e.target.value })}
      />
      <input
        type="password"
        className="rounded-md border px-3 py-1.5 text-sm"
        placeholder="Password"
        value={v.password}
        onChange={(e) => setV({ ...v, password: e.target.value })}
      />
      <select
        className="rounded-md border px-3 py-1.5 text-sm"
        value={v.role}
        onChange={(e) => setV({ ...v, role: e.target.value as Role })}
      >
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
      <select
        className="rounded-md border px-3 py-1.5 text-sm"
        value={v.branch_id}
        onChange={(e) => setV({ ...v, branch_id: e.target.value })}
      >
        <option value="">No branch</option>
        {branches.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name}
          </option>
        ))}
      </select>
      <Button type="submit" size="sm" disabled={!filled}>
        Add user
      </Button>
    </form>
  );
}
