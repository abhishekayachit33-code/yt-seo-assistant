import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits .next/standalone with a self-contained server.js and only the
  // node_modules actually reached at runtime. Without this the runtime image
  // has to carry the full dependency tree (~365 packages) to start.
  output: "standalone",
};

export default nextConfig;
