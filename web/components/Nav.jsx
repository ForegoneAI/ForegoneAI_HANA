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