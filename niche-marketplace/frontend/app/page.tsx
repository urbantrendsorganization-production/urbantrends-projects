import { BrowseBar } from "@/components/browse/BrowseBar";
import { BrowseResults } from "@/components/browse/BrowseResults";
import { FilterForm } from "@/components/browse/FilterForm";
import { getCategories, getListings } from "@/lib/api";
import { buildListingQuery, toSearchParams } from "@/lib/browse";

// Search results are inherently per-request; never prerender.
export const dynamic = "force-dynamic";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const source = toSearchParams(await searchParams);
  const query = buildListingQuery(source);
  const [categories, feed] = await Promise.all([
    getCategories(),
    getListings(query),
  ]);
  const queryKey = query.toString();

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <div className="lg:grid lg:grid-cols-[240px_1fr] lg:gap-8">
        <aside className="hidden lg:block">
          <div className="sticky top-20">
            <FilterForm categories={categories} />
          </div>
        </aside>

        <div className="space-y-6">
          <BrowseBar categories={categories} />
          <BrowseResults
            key={queryKey}
            initial={feed.results}
            initialCursor={feed.nextCursor}
            query={queryKey}
          />
        </div>
      </div>
    </main>
  );
}
