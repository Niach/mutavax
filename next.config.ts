import type { NextConfig } from "next";

// Proxy all /backend/* to the FastAPI container on the Docker network. Keeps
// the browser on a single origin so self-hosters only expose port 3000.
const INTERNAL_API_URL = process.env.INTERNAL_API_URL ?? "http://backend:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  devIndicators: false,
  async rewrites() {
    return [
      { source: "/backend/:path*", destination: `${INTERNAL_API_URL}/:path*` },
    ];
  },
};

export default nextConfig;
