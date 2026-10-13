import Link from "next/link";

export const metadata = {
  title: "ForegoneAI | The Edge Must Evolve.",
  description: "Intelligence systems for institutions operating across capital markets and complex business environments. HANA is our flagship platform.",
  openGraph: {
    title: "ForegoneAI | The Edge Must Evolve.",
    description: "Intelligence systems for institutions operating across capital markets and complex business environments. HANA is our flagship platform.",
    type: "website",
    url: "https://foregone.ai/",
    images: ["/assets/img/hero-sphere-poster.webp"],
  },
};

export default function Home() {
  return (
    <main id="main">

    <section className="hero hero--stage">
      <div className="hero__grid-bg" aria-hidden="true"></div>
      <canvas className="hero__gl" data-gl="knot" aria-hidden="true"></canvas>
      <div className="hero__scrim" aria-hidden="true"></div>

      <div className="hero__in wrap">
        <div className="stage">
          <div className="stage__copy">
            <p className="eyebrow eyebrow--dot">Institutional Intelligence</p>
            <h1 className="d1 rv-stack" data-scramble="">
              <span className="rv-line"><span>ForegoneAI</span></span>
            </h1>
            <p className="lede" data-rv="" data-rv-delay="0.4">
              Intelligence systems for institutions operating across capital markets
              and complex business environments.
            </p>
            <div className="btn-row" data-rv="" data-rv-delay="0.55">
              <Link className="btn btn--primary btn--lg" href="/hana/">Explore HANA <span className="arw" aria-hidden="true">&rarr;</span></Link>
              <Link className="btn btn--lg" href="/contact/">Work With Us <span className="arw" aria-hidden="true">&rarr;</span></Link>
            </div>
          </div>

        </div>
      </div>
    </section>

    <div className="marquee" aria-hidden="true">
      <div className="marquee__track">
        <div>
          <span>Private Markets</span><i>&#9670;</i>
          <span>Quantitative Research</span><i>&#9670;</i>
          <span>Capital Formation</span><i>&#9670;</i>
          <span>Institutional Memory</span><i>&#9670;</i>
          <span>Relationship Intelligence</span><i>&#9670;</i>
          <span>Decision Infrastructure</span><i>&#9670;</i>
        </div>
      </div>
    </div>

    <section className="section">
      <div className="wrap">
        <p className="eyebrow eyebrow--dot" data-rv="">Why ForegoneAI Exists</p>
        <h2 className="statement" data-rv="">
          Institutions do not lack information.<br />
          They lack a <em>reliable way</em> to connect it.
        </h2>
      </div>
    </section>

    {/* ======================================================================
         Constellation 01 — the four failure modes, on a tetrahedron.
         Each <li> is real content: title in .cstl__node-t, detail in .cstl__node-b.
         Without JS or WebGL it renders as a plain list; with it, each item is
         lifted onto a vertex and its detail opens in the readout box.
         ====================================================================== *\/ */}
    <section className="section section--flush-t">
      <div className="wrap">
        <div className="cstl" data-cstl="" data-shape="tetra" data-rv="">
          <canvas className="cstl__gl" aria-hidden="true"></canvas>
          <ul className="cstl__nodes">
            <li data-k="01">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Knowledge sits in silos</span></button>
              <p className="cstl__node-b">Documents, models and data rooms never resolve into one picture.</p>
            </li>
            <li data-k="02">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Context leaves with people</span></button>
              <p className="cstl__node-b">Years of reasoning walk out with whoever held it.</p>
            </li>
            <li data-k="03">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Research repeats itself</span></button>
              <p className="cstl__node-b">The same market gets re-underwritten from scratch.</p>
            </li>
            <li data-k="04">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Assumptions go untested</span></button>
              <p className="cstl__node-b">Downside gets examined after commitment, not before.</p>
            </li>
          </ul>
          <div className="cstl__panel" data-panel="" aria-live="polite"></div>
          <p className="cstl__hint">Hover a vertex to read it</p>
        </div>
      </div>
    </section>

    {/* ======================================================================
         Constellation 02 — an octahedron: three capabilities above,
         three specialized systems below.
         ====================================================================== */}
    <section className="section" id="hana">
      <div className="wrap">
        <div className="sec-head mb-l">
          <p className="eyebrow eyebrow--dot" data-rv="">HANA &mdash; Human-Aligned Network Analysis</p>
          <h2 className="d2" data-rv="">One intelligence platform.<br />Multiple specialized systems.</h2>
        </div>
        <div className="cstl" data-cstl="" data-shape="octa" data-rv="">
          <canvas className="cstl__gl" aria-hidden="true"></canvas>
          <ul className="cstl__nodes">
            <li data-k="Connect">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Information</span></button>
              <p className="cstl__node-b">Structured and unstructured sources, resolved into one layer.</p>
            </li>
            <li data-k="Preserve">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Context</span></button>
              <p className="cstl__node-b">Decisions and outcomes become institutional memory.</p>
            </li>
            <li data-k="Coordinate">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Work</span></button>
              <p className="cstl__node-b">Research, follow-ups and approvals, evidence attached.</p>
            </li>
            <li data-k="System &mdash; H9N">
              <a className="cstl__node" href="/systems/#h9n"><span className="cstl__node-t">H9N</span></a>
              <p className="cstl__node-b">Private Markets Intelligence &mdash; sourcing, underwriting, diligence and relationship mapping.</p>
            </li>
            <li data-k="System &mdash; H1S">
              <a className="cstl__node" href="/systems/#h1s"><span className="cstl__node-t">H1S</span></a>
              <p className="cstl__node-b">Market &amp; Trading Intelligence &mdash; market data, quantitative research, model governance, execution.</p>
            </li>
            <li data-k="System &mdash; H5B">
              <a className="cstl__node" href="/systems/#h5b"><span className="cstl__node-t">H5B</span></a>
              <p className="cstl__node-b">Business Development Intelligence &mdash; prospect research, relationship context, pipeline and sales.</p>
            </li>
          </ul>
          <div className="cstl__panel" data-panel="" aria-live="polite"></div>
          <p className="cstl__hint">Hover a vertex to read it</p>
        </div>

        <div className="btn-row" data-rv=""><Link className="btn" href="/systems/">All systems <span className="arw" aria-hidden="true">&rarr;</span></Link></div>

        <div className="panel panel--amber mt-l" data-rv="">
          <div className="split split--wide-l split--top">
            <p className="statement" style={{ fontSize: 'clamp(1.7rem,3.4vw,2.9rem)' }}>
              HANA does not remove people from consequential decisions.
            </p>
            <div>
              <p className="body-lg">Final authority stays with whoever is accountable for the outcome.</p>
              <div className="btn-row"><Link className="btn" href="/hana/">How HANA thinks <span className="arw" aria-hidden="true">&rarr;</span></Link></div>
            </div>
          </div>
        </div>
      </div>
    </section>

    {/* ======================================================================
         Constellation 03 — the build loop, on a closed four-point ring.
         ====================================================================== */}
    <section className="section">
      <div className="wrap">
        <div className="sec-head mb-l">
          <p className="eyebrow eyebrow--dot" data-rv="">Built From Inside the Work</p>
          <h2 className="d2" data-rv="">Developed close to the environments it operates in.</h2>
        </div>
        <div className="cstl" data-cstl="" data-shape="ring" data-rv="">
          <canvas className="cstl__gl" aria-hidden="true"></canvas>
          <ul className="cstl__nodes">
            <li data-k="Loop &mdash; 01">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Every workflow</span></button>
              <p className="cstl__node-b">Exposes a constraint.</p>
            </li>
            <li data-k="Loop &mdash; 02">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Every decision</span></button>
              <p className="cstl__node-b">Reveals missing context.</p>
            </li>
            <li data-k="Loop &mdash; 03">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Every mistake</span></button>
              <p className="cstl__node-b">Identifies what the system must understand next.</p>
            </li>
            <li data-k="Loop &mdash; 04">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Every outcome</span></button>
              <p className="cstl__node-b">Strengthens the knowledge behind it.</p>
            </li>
          </ul>
          <div className="cstl__panel" data-panel="" aria-live="polite"></div>
          <p className="cstl__hint">Hover a vertex to read it</p>
        </div>
      </div>
    </section>

    <section className="cta">
      <div className="cta__glow" aria-hidden="true"></div>
      <canvas className="cta__field" data-field="" aria-hidden="true"></canvas>
      <div className="wrap wrap--narrow">
        <p className="eyebrow eyebrow--dot" data-rv="" style={{ justifyContent: 'center' }}>Build With ForegoneAI</p>
        <h2 className="d2" data-rv="">The edge must evolve.</h2>
        <p className="lede mt-m" data-rv="" data-rv-delay="0.1">For institutional partnerships, strategic investment or technical collaboration.</p>
        <div className="btn-row" data-rv="" data-rv-delay="0.18">
          <Link className="btn btn--primary btn--lg" href="/contact/">Contact ForegoneAI <span className="arw" aria-hidden="true">&rarr;</span></Link>
          <a className="btn btn--lg" href="/contact/#partnership">Institutional Partnerships <span className="arw" aria-hidden="true">&rarr;</span></a>
        </div>
      </div>
    </section>

    </main>
  );
}
