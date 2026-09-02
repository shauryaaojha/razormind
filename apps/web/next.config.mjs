// Next 14 does not load a TypeScript config; 15 does. Pinning React 18 for
// styled-components v5 (D-55) means pinning Next 14, so this is .mjs.

/** @type {import("next").NextConfig} */
const config = {
  reactStrictMode: true,
  // Blade is built on styled-components v5. Next's compiler handles the
  // display-name and SSR bookkeeping that v5 otherwise needs a Babel plugin
  // for; the server-side stylesheet itself is collected in app/registry.tsx.
  compiler: { styledComponents: true },
  transpilePackages: ["@razorpay/blade"],
  env: {
    NEXT_PUBLIC_API_BASE_URL:
      process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
    NEXT_PUBLIC_MERCHANT_ID: process.env.NEXT_PUBLIC_MERCHANT_ID ?? "M123",
    // Until the JWT lands (D-52) the caller identifies itself with a header.
    // The seeded analyst is the default so the demo runs with no setup.
    NEXT_PUBLIC_USER_ID:
      process.env.NEXT_PUBLIC_USER_ID ?? "22222222-2222-4222-8222-222222222222",
  },
};

export default config;
