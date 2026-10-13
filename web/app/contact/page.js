export const metadata = {
  title: "Contact — Build With ForegoneAI",
  description: "Institutional partnerships, strategic investment, technical collaboration and career inquiries.",
  openGraph: {
    title: "Contact — Build With ForegoneAI",
    description: "Institutional partnerships, strategic investment, technical collaboration and career inquiries.",
    type: "website",
    url: "https://foregone.ai/contact/",
    images: ["//assets/img/extra-2.webp"],
  },
};

export default function Contact() {
  return (
    <main id="main">

    <section className="hero hero--sub hero--stage">
      <div className="hero__grid-bg" aria-hidden="true"></div>
      <canvas className="hero__gl" data-gl="portal" aria-hidden="true"></canvas>
      <div className="hero__scrim" aria-hidden="true"></div>
      <div className="hero__in wrap">
        <div className="stage">
          <div className="stage__copy">
            <p className="eyebrow eyebrow--dot">Contact</p>
            <h1 className="d1 rv-stack" data-scramble="">
              <span className="rv-line"><span>Build with</span></span>
              <span className="rv-line"><span>ForegoneAI.</span></span>
            </h1>
            <p className="lede mt-m" data-rv="" data-rv-delay="0.4">Institutional partnerships, strategic investment, technical collaboration and career inquiries.</p>
          </div>
        </div>
      </div>
    </section>

    <section className="section">
      <div className="wrap">
        <div className="split split--wide-r split--top">
          <div>
            <p className="eyebrow" data-rv="">Direct</p>
            <h2 className="d3" data-rv="">We read every inquiry.</h2>
            <ul className="deets mt-m" data-rv="" data-rv-delay="0.1">
              <li id="partnership"><span className="k">General</span><span className="v">info@foregone.ai</span></li>
              <li><span className="k">Strategic Investment</span><span className="v">investors@foregone.ai</span></li>
            </ul>
          </div>

          <div data-form-wrap="" data-rv="" data-rv-delay="0.15">
            <div className="panel">
              <p className="eyebrow">Send a Message</p>
              <div className="form__ok" role="status">
                Received. Someone from ForegoneAI will respond directly.
              </div>
              <form className="form mt-m" data-form="" noValidate>
                <div className="form__row">
                  <div className="field">
                    <label htmlFor="f-name">Name</label>
                    <input id="f-name" name="name" type="text" placeholder="Full name" required />
                  </div>
                  <div className="field">
                    <label htmlFor="f-org">Organization</label>
                    <input id="f-org" name="organization" type="text" placeholder="Firm or company" />
                  </div>
                </div>
                <div className="field">
                  <label htmlFor="f-email">Email</label>
                  <input id="f-email" name="email" type="email" placeholder="you@firm.com" required />
                </div>
                <div className="field field--sel">
                  <label htmlFor="f-topic">Inquiry type</label>
                  <select id="f-topic" name="topic" required>
                    <option value="">Select one</option>
                    <option>Institutional partnership</option>
                    <option>Design partnership or pilot</option>
                    <option>System integration</option>
                    <option>Strategic investment</option>
                    <option>Technical collaboration</option>
                    <option>Careers</option>
                    <option>Other</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="f-msg">Message</label>
                  <textarea id="f-msg" name="message" placeholder="What are you trying to solve?" required></textarea>
                </div>
                <div className="btn-row" style={{ marginTop: '4px' }}>
                  <button className="btn btn--primary btn--lg" type="submit">Send inquiry <span className="arw" aria-hidden="true">&rarr;</span></button>
                </div>
              </form>
            </div>
          </div>
        </div>
      </div>
    </section>

    </main>
  );
}
