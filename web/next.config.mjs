/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // Cloud Run wants a self contained server bundle rather than the whole
  // node_modules tree in the image.
  output: "standalone",

  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080",
    NEXT_PUBLIC_DEMO_RUN_ID: process.env.NEXT_PUBLIC_DEMO_RUN_ID ?? "demo-run-0001",
  },

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },

  async rewrites() {
    // Same origin proxy to the API. Server sent events pass through cleanly
    // and the browser never needs a cross origin credential.
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
