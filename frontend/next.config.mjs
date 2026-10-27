/** @type {import('next').NextConfig} */
const nextConfig = {
  // Keep the Webpack dev cache separate from any Turbopack cache created earlier.
  distDir: process.env.NEXT_DIST_DIR ?? (process.env.NODE_ENV === 'development' ? '.next-webpack' : '.next'),
};

export default nextConfig;
