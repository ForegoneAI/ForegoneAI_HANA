import Link from "next/link";
import SiteEffects from "@/components/SiteEffects";

export const metadata = {
  metadataBase: new URL("https://foregone.ai"),
  // every page sets its own title; this is the fallback
  title: "ForegoneAI | The Edge Must Evolve.",
  description: "Intelligence systems for institutions operating across capital markets and complex business environments. HANA is our flagship platform.",
  icons: {
    icon: "/assets/img/favicon.svg",
    apple: "/assets/img/apple-touch-icon.png",
  },
};

export const viewport = {
  themeColor: "#08070A",
  width: "device-width",
  initialScale: 1,
  // clears the notch and home indicator on iPhone; the CSS reads the insets
  viewportFit: "cover",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap"
        />
        {/* Linked rather than imported through the bundler on purpose: the
            @font-face rules inside use ../fonts/ paths relative to the
            stylesheet, and served from /assets/css/ those resolve exactly as
            they do today. Bundling would rewrite them for no gain. */}
        <link rel="stylesheet" href="/assets/css/main.css" />
      </head>
      <body>
        <div className="bg-grid" aria-hidden="true"></div>
        <a className="skip" href="#main">Skip to content</a>
        <div className="grain" aria-hidden="true"></div>
        <div className="progress" aria-hidden="true"></div>

        <header className="nav">
          <div className="wrap nav__in">
            <Link className="brand" href="/" aria-label="ForegoneAI &mdash; home">
              <svg className="brand__mark" viewBox="0 0 48 48" fill="none" stroke="currentColor"
                   strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="24" cy="24" r="21" strokeWidth="1.61"/>
                <path d="M23.72 9.80C22.02 19.19 20.69 27.28 20.68 37.33" strokeWidth="1.39"/>
                <path d="M20.73 34.92C21.53 28.75 25.81 25.98 29.28 25.81" strokeWidth="1.39"/>
              </svg>
              <span>FOREGONE<em>AI</em></span>
            </Link>
            <nav aria-label="Primary">
              <ul className="nav__links">
                <li><Link href="/hana/">HANA</Link></li>
                <li><Link href="/systems/">Systems</Link></li>
                <li><Link href="/research/">Research &amp; Insights</Link></li>
              </ul>
            </nav>
            <div className="nav__cta">
              <Link className="btn btn--sm" href="/contact/">Contact <span className="arw" aria-hidden="true">&rarr;</span></Link>
              <button className="burger" aria-label="Open menu" aria-expanded="false" aria-controls="drawer">
                <span></span><span></span>
              </button>
            </div>
          </div>
        </header>
        <div className="drawer" id="drawer" aria-hidden="true">
          <nav aria-label="Mobile">
            <ul className="drawer__links">
              <li><Link href="/"><i>01</i> Home</Link></li>
              <li><Link href="/hana/"><i>02</i> HANA</Link></li>
              <li><Link href="/systems/"><i>03</i> Systems</Link></li>
              <li><Link href="/research/"><i>04</i> Research &amp; Insights</Link></li>
              <li><Link href="/contact/"><i>05</i> Contact</Link></li>
            </ul>
          </nav>
          <div className="drawer__foot">
            <span>Human conviction. Machine intelligence.</span>
            <Link href="/contact/" className="tlink">Start a conversation <span className="arw">&rarr;</span></Link>
          </div>
        </div>
        {children}
        <footer className="foot">
          <div className="wrap">
            <div className="foot__grid">
              <div>
                <Link className="brand" href="/">
                  <svg className="brand__mark" viewBox="0 0 48 48" fill="none" stroke="currentColor"
                       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="24" cy="24" r="21" strokeWidth="1.61"/>
                    <path d="M23.72 9.80C22.02 19.19 20.69 27.28 20.68 37.33" strokeWidth="1.39"/>
                    <path d="M20.73 34.92C21.53 28.75 25.81 25.98 29.28 25.81" strokeWidth="1.39"/>
                  </svg>
                  <span>FOREGONE<em>AI</em></span>
                </Link>
                <p className="foot__tag">Human conviction.<br /><em>Machine intelligence.</em></p>
              </div>
              <div>
                <h4>Platform</h4>
                <ul>
                  <li><Link href="/hana/">HANA</Link></li>
                  <li><a href="/systems/#h9n">H9N &mdash; Private Markets</a></li>
                  <li><a href="/systems/#h1s">H1S &mdash; Markets &amp; Trading</a></li>
                  <li><a href="/systems/#h5b">H5B &mdash; Business Development</a></li>
                </ul>
              </div>
              <div>
                <h4>Research</h4>
                <ul>
                  <li><Link href="/research/">Research &amp; Insights</Link></li>
                </ul>
              </div>
              <div>
                <h4>Connect</h4>
                <ul>
                  <li><a href="/contact/#partnership">Institutional Partnerships</a></li>
                  <li><Link href="/contact/">Contact</Link></li>
                </ul>
              </div>
            </div>
            <div className="foot__bar">
              <span>&copy; <span data-year="">2026</span> ForegoneAI. All rights reserved.</span>
              <span>Built from inside the work.</span>
            </div>
            <svg className="foot__word" viewBox="0 0 918 112" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
              <defs>
                <linearGradient id="footWordFade" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#EDE8E1" stopOpacity=".13"/>
                  <stop offset=".62" stopColor="#FFFFFF" stopOpacity=".07"/>
                  <stop offset="1" stopColor="#FFFFFF" stopOpacity="0"/>
                </linearGradient>
              </defs>
              <text x="459" y="105" textAnchor="middle" textLength="918" lengthAdjust="spacing">FOREGONEAI</text>
            </svg>
          </div>
        </footer>
        <SiteEffects />
      </body>
    </html>
  );
}
