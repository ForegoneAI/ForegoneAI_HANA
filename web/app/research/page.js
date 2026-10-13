import Link from "next/link";

export const metadata = {
  title: "Research & Insights — ForegoneAI",
  description: "Selected research, product progress and operating insights from ForegoneAI: build notes, research, field intelligence and product updates.",
  openGraph: {
    title: "Research & Insights — ForegoneAI",
    description: "Selected research, product progress and operating insights.",
    type: "website",
    url: "https://foregone.ai/research/",
    images: ["//assets/img/hero-sphere-poster.webp"],
  },
};

export default function Research() {
  return (
    <main id="main">

    <section className="hero hero--sub hero--stage">
      <div className="hero__grid-bg" aria-hidden="true"></div>
      <canvas className="hero__gl" data-gl="meridian" aria-hidden="true"></canvas>
      <div className="hero__scrim" aria-hidden="true"></div>

      <div className="hero__in wrap">
        <div className="stage">
          <div className="stage__copy">
            <p className="eyebrow eyebrow--dot">Research &amp; Insights</p>
            <h1 className="d1 rv-stack" data-scramble="">
              <span className="rv-line"><span className="hl-soft">Intelligence should be</span></span>
              <span className="rv-line"><span>demonstrated.</span></span>
            </h1>
            <p className="lede" data-rv="" data-rv-delay="0.45">
              Selected research, product progress and operating insights.
            </p>
            <div className="btn-row" data-rv="" data-rv-delay="0.6">
              <a className="btn btn--primary btn--lg" href="#index">View Latest Research <span className="arw" aria-hidden="true">&rarr;</span></a>
              <Link className="btn btn--lg" href="/hana/">Follow HANA&rsquo;s Development <span className="arw" aria-hidden="true">&rarr;</span></Link>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section className="section">
      <div className="wrap">
        <p className="eyebrow eyebrow--dot" data-rv="">What This Is</p>
        <h2 className="statement" data-rv="">
          What we study,<br />build and <em>learn</em>.
        </h2>
      </div>
    </section>

    {/* ======================================================================
         The four streams — one line each
         ====================================================================== */}
    <section className="section section--flush-t">
      <div className="wrap">
        <div className="grid g2 grid--hair" data-rv-stagger="0.06">
          <div className="card" data-rv="">
            <span className="card__idx">Stream 01</span>
            <h3 className="d4">HANA Build Notes</h3>
            <p className="muted">A specific problem, the approach tested, what it revealed.</p>
          </div>
          <div className="card" data-rv="">
            <span className="card__idx">Stream 02</span>
            <h3 className="d4">Research</h3>
            <p className="muted">The technical questions behind the systems we build.</p>
          </div>
          <div className="card" data-rv="">
            <span className="card__idx">Stream 03</span>
            <h3 className="d4">Field Intelligence</h3>
            <p className="muted">Structural problems seen in private markets and institutional operations.</p>
          </div>
          <div className="card" data-rv="">
            <span className="card__idx">Stream 04</span>
            <h3 className="d4">Product Updates</h3>
            <p className="muted">Capabilities, milestones, pilots and releases across HANA.</p>
          </div>
        </div>
      </div>
    </section>

    {/* ======================================================================
         Insights index
         ----------------------------------------------------------------------
         TO PUBLISH A NEW ENTRY: copy one <article className="post"> block below and
         edit it. Four things to set:

           1. data-cat=""  — one of: build | research | field | product
                          (this is what the filter buttons match on)
           2. .post__cat    — the label shown on the card
           3. .post__date   — publication date
           4. Delete the <span className="post__tag">Placeholder</span> line and the
              "post--draft" class once the entry is real.

         Point the card's href at the article page when you have one.
         ====================================================================== */}
    <section className="section section--flush-t" id="index">
      <div className="wrap">
        <div className="sec-head mb-l">
          <p className="eyebrow eyebrow--dot" data-rv="">The Index</p>
          <h2 className="d2" data-rv="">Notes, research<br />and updates.</h2>
        </div>

        <div className="filters" data-rv="" role="group" aria-label="Filter entries by stream">
          <button className="filter is-on" data-filter="all" type="button">All</button>
          <button className="filter" data-filter="build" type="button">Build Notes</button>
          <button className="filter" data-filter="research" type="button">Research</button>
          <button className="filter" data-filter="field" type="button">Field Intelligence</button>
          <button className="filter" data-filter="product" type="button">Product Updates</button>
        </div>

        <div className="posts" data-rv-stagger="0.05">

          <article className="post post--draft" data-cat="build" data-rv="">
            <div className="post__meta">
              <span className="post__cat">Build Note</span>
              <span className="post__date">&mdash;</span>
              <span className="post__tag">Placeholder</span>
            </div>
            <h3>Note title</h3>
            <p className="muted">One-line summary.</p>
            <span className="post__more">Read note <span className="arw" aria-hidden="true">&rarr;</span></span>
          </article>

          <article className="post post--draft" data-cat="research" data-rv="">
            <div className="post__meta">
              <span className="post__cat">Research</span>
              <span className="post__date">&mdash;</span>
              <span className="post__tag">Placeholder</span>
            </div>
            <h3>Research title</h3>
            <p className="muted">One-line summary.</p>
            <span className="post__more">Read paper <span className="arw" aria-hidden="true">&rarr;</span></span>
          </article>

          <article className="post post--draft" data-cat="field" data-rv="">
            <div className="post__meta">
              <span className="post__cat">Field Intelligence</span>
              <span className="post__date">&mdash;</span>
              <span className="post__tag">Placeholder</span>
            </div>
            <h3>Observation title</h3>
            <p className="muted">One-line summary.</p>
            <span className="post__more">Read observation <span className="arw" aria-hidden="true">&rarr;</span></span>
          </article>

          <article className="post post--draft" data-cat="product" data-rv="">
            <div className="post__meta">
              <span className="post__cat">Product Update</span>
              <span className="post__date">&mdash;</span>
              <span className="post__tag">Placeholder</span>
            </div>
            <h3>Update title</h3>
            <p className="muted">One-line summary.</p>
            <span className="post__more">Read update <span className="arw" aria-hidden="true">&rarr;</span></span>
          </article>

        </div>

        <p className="post__empty" data-empty="" hidden>No entries in this stream yet.</p>
      </div>
    </section>

    {/* ======================================================================
         Current areas of interest
         ====================================================================== */}
    <section className="section">
      <div className="wrap">
        <div className="sec-head mb-l">
          <p className="eyebrow eyebrow--dot" data-rv="">Current Areas of Interest</p>
          <h2 className="d2" data-rv="">The questions behind<br />the work.</h2>
        </div>
        <ul className="ticks ticks--2" data-rv="">
          <li>Domain-specific intelligence</li>
          <li>Institutional memory</li>
          <li>Relationship intelligence</li>
          <li>Decision systems</li>
          <li>Model evaluation</li>
          <li>Human oversight</li>
          <li>Multi-agent coordination</li>
          <li>Quantitative research</li>
          <li>Intelligent workflows</li>
          <li>AI security and governance</li>
        </ul>
      </div>
    </section>

    <section className="cta">
      <div className="cta__glow" aria-hidden="true"></div>
      <canvas className="cta__field" data-field="" aria-hidden="true"></canvas>
      <div className="wrap wrap--narrow">
        <p className="eyebrow eyebrow--dot" data-rv="" style={{ justifyContent: 'center' }}>Follow the Work</p>
        <h2 className="d2" data-rv="">Built in the open,<br />where it can be.</h2>
        <p className="lede mt-m" data-rv="" data-rv-delay="0.1">Research collaboration, partnerships or technical discussion.</p>
        <div className="btn-row" data-rv="" data-rv-delay="0.18">
          <Link className="btn btn--primary btn--lg" href="/contact/">Contact ForegoneAI <span className="arw" aria-hidden="true">&rarr;</span></Link>
          <Link className="btn btn--lg" href="/hana/">Follow HANA&rsquo;s Development <span className="arw" aria-hidden="true">&rarr;</span></Link>
        </div>
      </div>
    </section>

    </main>
  );
}
