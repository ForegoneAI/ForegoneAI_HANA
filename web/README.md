# ForegoneAI site — React

Next.js (App Router) static export of the marketing site. **This is what
deploys to foregone.ai.** It replaced the hand-written HTML in `../site`, which
is kept in the repo for reference only and is no longer published.

```bash
cd web
npm install
npm run dev     # http://localhost:3000
npm run build   # static HTML into web/out
```

## Why these choices

**Static export.** `next.config.mjs` sets `output: "export"`, so the build
writes plain HTML files — GitHub Pages serves files, not a Node server, so
anything requiring a server (SSR, API routes, ISR, middleware) will not work
here. `trailingSlash: true` keeps the URLs exactly as they were: `/hana/`, not
`/hana`. Without it the export emits `hana.html` and every existing link breaks.

**The stylesheet is linked, not imported.** `main.css` lives in
`public/assets/css/` and is loaded with a `<link>` in `app/layout.js`. Its
`@font-face` rules use `../fonts/` paths relative to the stylesheet, and served
from `/assets/css/` those resolve correctly with no rewriting. Importing it
through the bundler would work too, but only by rewriting those URLs — a
transformation with nothing to gain.

## Layout

```
app/layout.js          nav, drawer, footer, background layers — the chrome every page shares
app/page.js            /            app/hana/page.js       /hana/
app/systems/page.js    /systems/    app/research/page.js   /research/
app/contact/page.js    /contact/
components/Nav.jsx     the shared chrome markup, included by layout
components/SiteEffects.jsx   runs the motion layer, keyed to the route
lib/site.js            the whole motion + canvas layer (ported from site/assets/js/main.js)
public/assets/         css, fonts, and the five images that are actually referenced
```

Page metadata (title, description, Open Graph) is the `metadata` export at the
top of each page file — it replaces the hand-written `<head>` tags. `og:image`
is now absolute via `metadataBase`; relative `og:image` paths aren't in the
Open Graph spec and scrapers read them inconsistently.

## How the motion layer works

`lib/site.js` is the original `main.js` with its module bodies unchanged — the
lighting rig, the camera fit, the label clamping, the Safari hover workaround
are all character for character what they were. What changed is lifecycle.

The original assumed a page that loads once and is thrown away by a full
navigation, so it never released anything: 42 event listeners, 7 observers, 15
animation loops with no `cancelAnimationFrame` anywhere, and six WebGL
contexts. Under a router the same code mounts and unmounts repeatedly, and
browsers only allow around 16 WebGL contexts at once — a few route changes
would exhaust them and the artwork would stop appearing.

So every listener, observer, animation frame, timer and WebGL context is routed
through a tracked helper at the top of `initSite()`, and the function returns a
disposer that releases all of it. `SiteEffects` calls it in an effect keyed to
the pathname: React runs the previous route's cleanup before the next route's
effect, which is what keeps the counts balanced instead of growing.

Verified over 30 client-side navigations: window listeners stayed at 12, and
the 3-D still built and rendered with no context-loss warnings.

### Three changes that were not cosmetic

**`THREE.sRGBEncoding` no longer exists.** It was removed in three r152. The
original line was guarded (`if (THREE.sRGBEncoding)`) so on a modern build it
silently did nothing. Modern three already defaults to sRGB output, but
`outputColorSpace` is now set explicitly so the intent survives another API
change.

**`place()` projected through a stale camera on its first frame.** `project()`
reads `camera.matrixWorldInverse`, and three only refreshes that during
`render()` — but `frame()` calls `place()` before its first render. On that one
frame the camera was treated as sitting at the origin, which put a vertex on the
camera plane and threw its label several thousand pixels off-frame. On a wide
screen, where labels are not clamped, that briefly widened the page.
`camera.updateMatrixWorld()` before projecting fixes it. This was latent in the
original too; running from a React effect just made it easier to catch.

**The label restyle animated when it shouldn't.** The stylesheet transitions
`letter-spacing` on `.cstl__node`, for hover. Under the original script `is-3d`
landed before the first paint so nothing animated; from an effect it lands
after, so the labels visibly grew. A `cstl-no-anim` class suppresses that one
transition for a frame.

## Deploy

`.github/workflows/static.yml` (repo root) runs on every push to `master`: it
installs with `npm ci` in `web/`, builds, and publishes `web/out` to GitHub
Pages. There is no manual step — merging to `master` is the deploy.

`npm ci` rather than `npm install` on purpose: it installs exactly what
`package-lock.json` pins, so a deploy can never quietly pick up a dependency
version the build was not tested against.

The custom domain is a repo setting (**Settings -> Pages**), not a `CNAME` file
in the published folder, so it survives a change of published directory. DNS for
`foregone.ai` and `www` points at `foregoneai.github.io`.

## Known

- `../site` is no longer published. It is left in the repo as the reference for
  what the React port was built from; nothing reads it and nothing deploys it.
  Deleting it is safe once the React site has run for a while.
- `careers.html` and `company.html` have been deleted. `../site/future.html`
  still exists but is equally unreachable — it was never linked from the nav and
  has no route here. Say the word and it goes too.
- The contact form is still front-end only, exactly as before: it validates,
  fakes a send and shows success. `forms()` in `lib/site.js` is where to point
  it at a real endpoint.
