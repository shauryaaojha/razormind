import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Phase 8 replaces this with a client generated from
  // packages/shared-types/openapi.json. Until then the base URL is all the
  // web app knows about the API.
  env: {
    API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  },
};

export default config;
