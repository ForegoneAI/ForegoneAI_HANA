import type { Metadata } from "next";
import { JetBrains_Mono, Onest, Parkinsans } from "next/font/google";

import "./globals.css";

// The same typefaces as the foregone.ai marketing site (site/assets/css/main.css).
// Next.js has no fallback metrics for Parkinsans, so skip generating one.
const display = Parkinsans({ subsets: ["latin"], variable: "--f-display", adjustFontFallback: false });
const body = Onest({ subsets: ["latin"], variable: "--f-body" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--f-mono" });

export const metadata: Metadata = {
  title: "HANA · H9N",
  description: "Upload a deal package and review its cited Deal Profile.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
