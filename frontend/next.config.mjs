import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit .next/standalone — a self-contained server carrying only the traced runtime
  // dependencies, so the container image need not ship all of node_modules (ACR-42 / A10-1).
  // Harmless outside Docker: `npm run dev` and `npm run start` are unaffected.
  output: "standalone",
};

export default withNextIntl(nextConfig);
