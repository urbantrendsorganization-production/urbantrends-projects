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
