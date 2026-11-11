import type { NextConfig } from "next";

/**
 * Production: a fully static export (`out/`) served by the FastAPI backend on
 * the same origin, so one process on your own machine serves everything.
 * Development: `next dev` proxies /api to the FastAPI dev server.
 */
const isProd = process.env.NODE_ENV === "production";
const apiTarget = process.env.II_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  ...(isProd
    ? { output: "export" as const }
    : {
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${apiTarget}/api/:path*` }];
        },
      }),
};

export default nextConfig;
