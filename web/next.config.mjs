/** @type {import('next').NextConfig} */
const nextConfig = {
  // In development the Python API runs separately on :8000; in production Vercel
  // routes /api/* to the serverless function, so no rewrite is needed there.
  async rewrites() {
    if (process.env.NODE_ENV === "development") {
      return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
    }
    return [];
  },
};
export default nextConfig;
