import { ListingDetailLoader } from "@/components/ListingDetailLoader";
import { getListing } from "@/lib/api";

// Server component: pre-fetch active listings for SSR; the loader falls back to
// a client-side, authenticated fetch for an owner's private (draft) listing.
export default async function ListingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const listing = await getListing(id);
  return <ListingDetailLoader id={id} initial={listing} />;
}
