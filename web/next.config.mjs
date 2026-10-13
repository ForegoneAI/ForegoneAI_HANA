/** @type {import('next').NextConfig} */
const nextConfig = {
  // GitHub Pages serves files, not a Node server, so the whole site is
  // pre-rendered to plain HTML at build time into out/.
  output: "export",

  // keeps the URLs exactly as they are today: /hana/ rather than /hana.
  // Without this the export emits hana.html and every existing link breaks.
  trailingSlash: true,

  // next/image needs a server to optimise on the fly, which a static export
  // has none of. The site has five images and no <img> tags, so nothing lost.
  images: { unoptimized: true },
};

export default nextConfig;
