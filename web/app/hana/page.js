import Link from "next/link";

export const metadata = {
  title: "HANA — Human-Aligned Network Analysis | ForegoneAI",
  description: "One intelligence platform. Multiple specialized systems. HANA works across institutional information, relationships, workflows and decision processes.",
  openGraph: {
    title: "HANA — Human-Aligned Network Analysis | ForegoneAI",
    description: "One intelligence platform. Multiple specialized systems. HANA works across institutional information, relationships, workflows and decision processes.",
    type: "website",
    url: "https://foregone.ai/hana/",
    images: ["//assets/img/hero-sphere-poster.webp"],
  },
};

export default function Hana() {
  return (
    <main id="main">

    <section className="hero hero--sub hero--stage">
      <div className="hero__grid-bg" aria-hidden="true"></div>
      <canvas className="hero__gl" data-gl="orb" aria-hidden="true"></canvas>
      <div className="hero__scrim" aria-hidden="true"></div>
      <div className="hero__in wrap">
        <div className="stage">
          <div className="stage__copy">
            <p className="eyebrow eyebrow--dot">Flagship Platform</p>
            <h1 className="d1 d1--lead rv-stack" data-scramble="">
              <span className="rv-line"><span>HANA</span></span>
              <span className="rv-line rv-line--sub"><span className="hl-expand">Human-Aligned Network Analysis</span></span>
            </h1>
            <p className="lede mt-m" data-rv="" data-rv-delay="0.4">HANA works across institutional information, relationships, workflows and decision processes.</p>
          </div>
        </div>
      </div>
    </section>

    <section className="section">
      <div className="wrap">
        <p className="eyebrow" data-rv="">The Platform</p>
        <h2 className="statement" data-rv="">
          She identifies connections,<br />preserves context and<br /><em>tests assumptions.</em>
        </h2>
        <p className="lede mt-l" data-rv="" style={{ maxWidth: '60ch' }}>
          Each system runs its own data, permissions, models and objectives on a
          common intelligence foundation.
        </p>
      </div>
    </section>

    <section className="section section--flush-t">
      <div className="wrap">
        <p className="eyebrow mb-l" data-rv="">What HANA Does</p>
        {/* six capabilities riding a continuous (2,3) torus knot — the same
             family of form as the hero, so the page reads as one object */}
        <div className="cstl" data-cstl="" data-shape="knot" data-rv="">
          <canvas className="cstl__gl" aria-hidden="true"></canvas>
          <ul className="cstl__nodes">
            <li data-k="01">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Connects everything</span></button>
              <p className="cstl__node-b">Structured and unstructured information, one layer.</p>
            </li>
            <li data-k="02">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Maps relationships</span></button>
              <p className="cstl__node-b">People, companies, capital and opportunities.</p>
            </li>
            <li data-k="03">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Finds patterns</span></button>
              <p className="cstl__node-b">Visible only once disconnected systems connect.</p>
            </li>
            <li data-k="04">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Tests assumptions</span></button>
              <p className="cstl__node-b">Against downside scenarios and changing conditions.</p>
            </li>
            <li data-k="05">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Coordinates work</span></button>
              <p className="cstl__node-b">Research, follow-ups and approvals, tracked to completion.</p>
            </li>
            <li data-k="06">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Retains knowledge</span></button>
              <p className="cstl__node-b">Institutional memory instead of scattered files.</p>
            </li>
          </ul>
          <div className="cstl__panel" data-panel="" aria-live="polite"></div>
          <p className="cstl__hint">Hover a point to read it</p>
        </div>
      </div>
    </section>

    <section className="section" id="approach">
      <div className="wrap">
        <div className="sec-head mb-l">
          <p className="eyebrow" data-rv="">How HANA Approaches Intelligence</p>
          <h2 className="d2" data-rv="">Five principles.</h2>
        </div>
        {/* five principles on a (3,2) knot — a different winding, so the two
             sections read as related but not identical */}
        <div className="cstl" data-cstl="" data-shape="knotAlt" data-rv="">
          <canvas className="cstl__gl" aria-hidden="true"></canvas>
          <ul className="cstl__nodes">
            <li data-k="Principle 01">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Context before conclusion</span></button>
              <p className="cstl__node-b">A useful answer depends on the environment surrounding the question.</p>
            </li>
            <li data-k="Principle 02">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Evidence before confidence</span></button>
              <p className="cstl__node-b">Verified information, assumptions and estimates are not the same thing.</p>
            </li>
            <li data-k="Principle 03">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Downside before commitment</span></button>
              <p className="cstl__node-b">What could fail, which assumptions are most sensitive, where risk is uncompensated.</p>
            </li>
            <li data-k="Principle 04">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Memory before repetition</span></button>
              <p className="cstl__node-b">Research and outcomes become usable intelligence, not trapped files.</p>
            </li>
            <li data-k="Principle 05">
              <button className="cstl__node" type="button"><span className="cstl__node-t">Human authority at the end</span></button>
              <p className="cstl__node-b">HANA analyzes and recommends. People decide.</p>
            </li>
          </ul>
          <div className="cstl__panel" data-panel="" aria-live="polite"></div>
          <p className="cstl__hint">Hover a point to read it</p>
        </div>
      </div>
    </section>

    <section className="cta">
      <div className="cta__glow" aria-hidden="true"></div>
      <canvas className="cta__field" data-field="" aria-hidden="true"></canvas>
      <div className="wrap wrap--narrow">
        <p className="eyebrow eyebrow--dot" data-rv="" style={{ justifyContent: 'center' }}>Work With HANA</p>
        <h2 className="d2" data-rv="">Put HANA inside your operating environment.</h2>
        <p className="lede mt-m" data-rv="" data-rv-delay="0.1">Institutional partnerships, pilots and system integrations.</p>
        <div className="btn-row" data-rv="" data-rv-delay="0.18">
          <Link className="btn btn--primary btn--lg" href="/contact/">Contact ForegoneAI <span className="arw" aria-hidden="true">&rarr;</span></Link>
          <a className="btn btn--lg" href="/contact/#partnership">Institutional Partnerships <span className="arw" aria-hidden="true">&rarr;</span></a>
        </div>
      </div>
    </section>

    </main>
  );
}
