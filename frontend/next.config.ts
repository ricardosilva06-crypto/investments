import type { NextConfig } from "next";

/**
 * A fully static app (no server): `next build` writes `out/`, which any static host can serve.
 * On GitHub Pages the site lives under /<repository>, set through NEXT_PUBLIC_BASE_PATH.
 */
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  output: "export",
  basePath: basePath || undefined,
  trailingSlash: true,
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
};

export default nextConfig;
