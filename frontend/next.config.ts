import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow local network devices to access dev resources (HMR, fonts, etc.)
  allowedDevOrigins: ["http://192.168.31.220:3000"],
};

export default nextConfig;
