import type { NextConfig } from "next";

// Static export so the UI can be served from GitHub Pages. The repo sub-path is set by CI.
const nextConfig: NextConfig = {
  output: "export",
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
