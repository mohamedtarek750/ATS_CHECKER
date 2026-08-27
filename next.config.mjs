/** @type {import('next').NextConfig} */
const nextConfig = {
  // A lint or type complaint should not stop a deployment. Both are checked in
  // development and in CI, where they can be fixed - failing here only means an
  // outage nobody can act on.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: false },

  // In development the Python API runs separately on :8000. In production Vercel
  // routes /api/* to the serverless function, so no rewrite is needed there.
  async rewrites() {
    if (process.env.NODE_ENV === "development") {
      return [
        { source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" },
      ];
    }
    return [];
  },
};
export default nextConfig;
