import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle for lean production images.
  output: "standalone",
  reactStrictMode: true,
  // Pin the tracing root to this app so an unrelated lockfile elsewhere on the
  // machine can't be inferred as the workspace root.
  outputFileTracingRoot: import.meta.dirname,
};

export default nextConfig;
