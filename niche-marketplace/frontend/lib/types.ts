export type Health = {
  status: string;
  version: string;
  services: { database: string; redis: string };
};

/** The authenticated user's own profile (from /users/me/). */
export type Me = {
  id: number;
  email: string;
  display_name: string;
  avatar: string | null;
  location: string;
  phone: string;
  is_verified: boolean;
  joined_at: string;
};

/** Another user's public profile (from /users/<id>/). */
export type PublicProfile = {
  id: number;
  name: string;
  display_name: string;
  avatar: string | null;
  location: string;
  joined_at: string;
};

// --- Catalog -------------------------------------------------------------

export type AttributeType = "string" | "number" | "boolean" | "enum";

/** One field definition from a category's attribute schema. */
export type AttributeField = {
  key: string;
  label: string;
  type: AttributeType;
  required?: boolean;
  options?: string[];
};

export type Category = {
  id: number;
  name: string;
  slug: string;
  parent: number | null;
  depth: number;
  /** Effective schema: own fields merged over ancestors'. */
  attribute_schema: AttributeField[];
};

export type ListingStatus = "draft" | "active" | "reserved" | "sold" | "expired";

export type Condition = "new" | "like_new" | "good" | "fair" | "for_parts";

export type ListingImage = {
  id: number;
  image: string;
  thumbnail: string | null;
  order: number;
};

/** Seller card embedded in a listing. */
export type ListingSeller = {
  id: number;
  name: string;
  avatar: string | null;
  location: string;
};

export type Listing = {
  id: number;
  seller: ListingSeller;
  category: Category;
  title: string;
  description: string;
  price: string;
  currency: string;
  condition: Condition;
  condition_display: string;
  location: string;
  status: ListingStatus;
  attributes: Record<string, string | number | boolean>;
  images: ListingImage[];
  created_at: string;
  published_at: string | null;
};

/** DRF LimitOffset pagination envelope. */
export type Paginated<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};
