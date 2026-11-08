import type { NextConfig } from "next";

// Python backend (FastAPI). Proxied so the session cookie stays same-origin.
const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      { source: "/auth/me", destination: `${BACKEND}/auth/me` },
      { source: "/auth/logout", destination: `${BACKEND}/auth/logout` },
      { source: "/api/:path*", destination: `${BACKEND}/api/:path*` },
    ];
  },
};

export default nextConfig;
