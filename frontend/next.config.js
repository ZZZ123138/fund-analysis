/** @type {import('next').NextConfig} */
const nextConfig = {
  // output: "export" 在开发模式下禁用以支持 API 代理
  ...(process.env.NODE_ENV === "production" && { output: "export" }),
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8001/api/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
