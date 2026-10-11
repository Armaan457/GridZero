import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // /compare runs three multi-day simulations and can exceed the 30s proxy default.
    proxyTimeout: 300_000,
  },
  async rewrites() {
    return [{ source: "/engine/:path*", destination: "http://127.0.0.1:8000/:path*" }];
  },
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
};

export default nextConfig;
