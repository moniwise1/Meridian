import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Lean, self-contained build output for Docker - see frontend/Dockerfile.
  output: "standalone",
};

export default nextConfig;
