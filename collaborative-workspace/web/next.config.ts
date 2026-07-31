import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    // Pin the workspace root. Without this Turbopack walks up looking for a lockfile and
    // can land outside the monorepo entirely.
    root: path.resolve(process.cwd()),
  },
};

export default nextConfig;
