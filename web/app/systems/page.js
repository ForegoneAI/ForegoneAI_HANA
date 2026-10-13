import Link from "next/link";

export const metadata = {
  title: "HANA Systems — H9N, H1S, H5B | ForegoneAI",
  description: "H9N for private markets, H1S for markets and trading, H5B for business development. Specialized intelligence on a common architecture.",
  openGraph: {
    title: "HANA Systems — H9N, H1S, H5B | ForegoneAI",
    description: "H9N for private markets, H1S for markets and trading, H5B for business development. Specialized intelligence on a common architecture.",
    type: "website",
    url: "https://foregone.ai/systems/",
    images: ["//assets/img/villa-dusk.webp"],
  },
};

export default function Systems() {
  return (
    <main id="main">

    <section className="hero hero--sub hero--stage">
      <div className="hero__grid-bg" aria-hidden="true"></div>
      <canvas className="hero__gl" data-gl="lattice" aria-hidden="true"></canvas>
      <div className="hero__scrim" aria-hidden="true"></div>
      <div className="hero__in wrap">
        <div className="stage">
          <div className="stage__copy">
            <p className="eyebrow eyebrow--dot">HANA Systems</p>
            <h1 className="d1 d1--lead rv-stack" data-scramble="">
              <span className="rv-line"><span>Specialized</span></span>
              <span className="rv-line"><span>Systems</span></span>
            </h1>
            <p className="lede mt-m" data-rv="" data-rv-delay="0.4">Built around the data, responsibilities and decisions of each domain. They share a foundation, not a configuration.</p>
          </div>
        </div>
      </div>
    </section>

    <div className="marquee" aria-hidden="true">
      <div className="marquee__track">
        <div>
          <span>H9N &mdash; Private Markets</span><i>&#9670;</i>
          <span>H1S &mdash; Markets &amp; Trading</span><i>&#9670;</i>
          <span>H5B &mdash; Business Development</span><i>&#9670;</i>
          <span>Common Intelligence Foundation</span><i>&#9670;</i>
        </div>
      </div>
    </div>

    <section className="section">
      <div className="wrap">

        <article className="sys" id="h9n">
          <div data-rv="left">
            <div className="sys__code">H9N</div>
            <p className="sys__tag">Private Markets Intelligence</p>
            <span className="sys__status">In active development</span>
          </div>
          <div className="sys__body" data-rv="" data-rv-delay="0.1">
            <p className="lede">For real-estate and private-equity firms, developers, family offices, lenders and allocators.</p>
            <h4 className="mt-m">Development areas</h4>
            <ul className="ticks ticks--2">
              <li>Sourcing and qualification</li>
              <li>Market and asset intelligence</li>
              <li>Deal scoring and prioritization</li>
              <li>Underwriting and assumption analysis</li>
              <li>Sponsor, lender and investor mapping</li>
              <li>Diligence and IC preparation</li>
            </ul>
            <p className="body-lg mt-m">Built inside Foregone&rsquo;s own private-market work &mdash; real deals, real deadlines, real capital constraints.</p>
          </div>
        </article>
        <article className="sys" id="h1s">
          <div data-rv="left">
            <div className="sys__code">H1S</div>
            <p className="sys__tag">Market and Trading Intelligence</p>
            <span className="sys__status">In active development</span>
          </div>
          <div className="sys__body" data-rv="" data-rv-delay="0.1">
            <p className="lede">For quantitative research, market intelligence and systematic trading environments.</p>
            <h4 className="mt-m">Development areas</h4>
            <ul className="ticks ticks--2">
              <li>Market and regime analysis</li>
              <li>Signal development and validation</li>
              <li>Model testing and monitoring</li>
              <li>Portfolio and exposure analysis</li>
              <li>Risk controls and execution</li>
              <li>Research memory and governance</li>
            </ul>
          </div>
        </article>
        <article className="sys" id="h5b">
          <div data-rv="left">
            <div className="sys__code">H5B</div>
            <p className="sys__tag">Business Development Intelligence</p>
            <span className="sys__status">In active development</span>
          </div>
          <div className="sys__body" data-rv="" data-rv-delay="0.1">
            <p className="lede">For revenue organizations building repeatable sales operations.</p>
            <h4 className="mt-m">Development areas</h4>
            <ul className="ticks ticks--2">
              <li>Lead sourcing and qualification</li>
              <li>Decision-maker research</li>
              <li>Relationship mapping</li>
              <li>Outreach and meeting intelligence</li>
              <li>Pipeline and follow-up coordination</li>
              <li>Institutional relationship memory</li>
            </ul>
            <p className="body-lg mt-m">The system provides coordination. <strong>People provide the trust and the ability to close.</strong></p>
          </div>
        </article>
      </div>
    </section>

    <section className="section" id="future-systems">
      <div className="wrap">
        <div className="split split--wide-l split--top">
          <div>
            <p className="eyebrow" data-rv="">Future Systems</p>
            <h2 className="statement" data-rv="">Three systems are<br />the <em>beginning.</em></h2>
          </div>
          <div data-rv="" data-rv-delay="0.12">
            <p className="body-lg">
              Each new system must solve a defined problem. <strong>We do not add AI where it
              creates no advantage.</strong>
            </p>
          </div>
        </div>
      </div>
    </section>

    <section className="cta">
      <div className="cta__glow" aria-hidden="true"></div>
      <canvas className="cta__field" data-field="" aria-hidden="true"></canvas>
      <div className="wrap wrap--narrow">
        <p className="eyebrow eyebrow--dot" data-rv="" style={{ justifyContent: 'center' }}>Design Partnerships</p>
        <h2 className="d2" data-rv="">Shape a system around your environment.</h2>
        <p className="lede mt-m" data-rv="" data-rv-delay="0.1">Design partnerships, pilots and long-term integration.</p>
        <div className="btn-row" data-rv="" data-rv-delay="0.18">
          <a className="btn btn--primary btn--lg" href="/contact/#partnership">Discuss a Partnership <span className="arw" aria-hidden="true">&rarr;</span></a>
          <Link className="btn btn--lg" href="/hana/">Explore HANA <span className="arw" aria-hidden="true">&rarr;</span></Link>
        </div>
      </div>
    </section>

    </main>
  );
}
