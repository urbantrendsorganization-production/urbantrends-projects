import { notFound } from "next/navigation";

import { Card } from "@/components/ui";
import { getPublicProfile } from "@/lib/api";

// Public profile — a server component; no auth required to view.
export default async function PublicProfilePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const profile = await getPublicProfile(id);

  if (!profile) notFound();

  const joined = new Date(profile.joined_at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
  });
  const initial = profile.name.charAt(0).toUpperCase();

  return (
    <main className="mx-auto max-w-md px-4 py-12">
      <Card>
        <div className="flex items-center gap-4">
          {profile.avatar ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={profile.avatar}
              alt={profile.name}
              className="h-16 w-16 rounded-full object-cover"
            />
          ) : (
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-brand text-xl font-bold text-white">
              {initial}
            </div>
          )}

          <div>
            <h1 className="text-xl font-bold tracking-tight">{profile.name}</h1>
            {profile.location ? (
              <p className="text-sm text-neutral-500">{profile.location}</p>
            ) : null}
            <p className="text-xs text-neutral-400">Joined {joined}</p>
          </div>
        </div>
      </Card>
    </main>
  );
}
