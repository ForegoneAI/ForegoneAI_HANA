# ForegoneAI — HANA

Static site. No build step, no package manager, no framework — plain HTML, CSS
and one JS file, plus a bundled Three.js. What you edit is what ships.

```bash
cd site && python3 -m http.server 8000     # http://localhost:8000
```

Serve over HTTP; opening `index.html` from the filesystem breaks fonts and links.

---

## Deploy

Live at **foregone.ai** from **ForegoneAI/ForegoneAI_HANA**, branch `master`.

`.github/workflows/static.yml` (repo root, one level up) publishes `./site`
verbatim to GitHub Pages on every push. The empty `.nojekyll` is what stops
Pages hiding `assets/`. Custom domain is set under **Settings → Pages**; DNS for
`foregone.ai` and `www` points at `foregoneai.github.io`.

No local git clone — this folder is uploaded through the GitHub web UI. Making
it a real clone would turn deploys into one command.

## URLs

Five pages, each a directory, so URLs carry no extension:

```
index.html        →  foregone.ai/
hana/index.html   →  foregone.ai/hana/
systems/          research/          contact/
```

Internal links are relative, so the site also works from a subpath.

The pre-migration flat URLs (`/hana.html` and friends) previously had redirect
stubs here. They have been removed, so those URLs now 404. The stubs are kept in
`../unused/redirect-stubs/` if any turn out to still be linked.

## Layout

```
index.html  hana/  systems/  research/  contact/   the five pages
.nojekyll                                          serve assets/ verbatim
assets/css/main.css      1.9k lines - tokens + every component
assets/js/main.js        1.5k lines - all behaviour, one IIFE
assets/js/vendor/        three.min.js (bundled, no CDN) + its licence
assets/fonts/            3 variable fonts + their OFL licences
assets/img/              5 files, all of them metadata (see below)
```

Total 1.3 MB, of which Three.js is 592 KB and the fonts 200 KB.

Excess files and resources  provided by the ForegoneAI team — is in `../unused/`, outside the published
folder. Nothing here references it.

---

## Design tokens

Top of `main.css`. Change a token, it propagates.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#060607` | Page base |
| `--bg-1` / `--bg-2` / `--bg-raise` | `#0A0A0C` / `#0E0E11` / `#141417` | Raised surfaces |
| `--ink` → `--ink-4` | `#F4F5F6` → `#45484E` | Text ramp |
| `--line` / `--line-soft` | 8.5% / 4.5% white | Borders |
| `--glow` | `#FFFFFF` | Accent, highlights, focus |
| `--gutter` / `--maxw` / `--nav-h` | `clamp(22px,6.8vw,96px)` / `1400px` / `74px` | Page metrics |

**The palette is monochrome.** `--amber`, `--dusk-teal` and `--dusk-rose` are
left over from a warm palette and now hold greys (`--amber` is `#E6E6E6`). The
names are vestigial — don't read colour into them.

Type: Parkinsans (display), Onest (body/UI), Darker Grotesque (statement lines),
all local variable fonts under the OFL. One external dependency: JetBrains Mono
from Google Fonts for small caps labels; falls back to system mono if blocked.

## Imagery

**There are no `<img>` tags on this site.** Every visual is drawn at runtime —
WebGL objects, canvas, CSS. The five files in `assets/img/` are metadata only:
`favicon.svg` and `apple-touch-icon.png` on every page, plus three `og:image`
social previews (`hero-sphere-poster.webp` for home/hana/research,
`villa-dusk.webp` for systems, `extra-2.webp` for contact).

If you add real imagery, note that nothing here uses `srcset` yet.

---

## Behaviour (`assets/js/main.js`)

One IIFE, one module per effect, each a no-op when its hook is absent. Order set
by `init()`: `nav`, `progress`, `reveals`, `heroLines`, `decode`, `cardGlow`,
`heroForm`, `constellations`, `field`, `marquee`, `forms`, `insightFilters`,
`year`.

| Attribute | Effect |
|---|---|
| `data-rv` / `data-rv-delay` / `data-rv-stagger` | Reveal on scroll; delay in seconds; auto-delay children |
| `data-scramble` | Headline decodes out of noise once, on arrival |
| `data-gl` | Hero object: `orb`, `knot`, `lattice`, `meridian`, `portal` |
| `data-cstl` + `data-shape` | Diagram: `tetra`, `octa`, `ring`, `knot`, `knotAlt` |
| `data-panel` | Readout box inside a `data-cstl` block |
| `data-field` | WebGL field behind the closing CTA |
| `data-filter` / `data-cat` | Research index filtering |
| `data-form` / `data-year` | Contact form; year stamp |

**The constellation `<ul>` is the real content and the fallback.** Without JS or
WebGL it renders as a plain list with every title and description visible. Worth
keeping that way.

---

## Phone vs desktop

Two gates: `NARROW()` (viewport under 760px) and `COARSE` (touch screen).
Desktop matches neither and is byte-identical to the pre-mobile version across
five pages at 1440/1280/1024.

Under 760px: labels are clamped inside the canvas (sizes from a
`ResizeObserver`, not a one-time measure); the camera fits the form to whichever
axis is tighter; the readout docks to the bottom edge instead of floating; tap
replaces hover, and hover handlers are **not bound at all** on touch, because
Safari's fake `mouseenter`/`mouseleave` pair cancels a tap-selection before it
can be read. Link labels take two taps — read, then follow. Pixel ratio is
capped at 1.75 (hero) / 1.6 (constellations) against an iPhone's native 3.

On iOS at any width: `viewport-fit=cover` plus `env(safe-area-inset-*)`, always
as `max(original, env(...))` — reversing that silently zeroes the padding on
every device without an inset. One shared resize listener ignores height-only
changes under 140px, since Safari's collapsing URL bar fires a resize on every
scroll and re-fitting made the artwork jump.

`prefers-reduced-motion: reduce` skips every canvas; content stays complete. A
refused WebGL context degrades to the plain list. Scrambled headlines keep their
wording in `aria-label`; the readout is `aria-live="polite"`.

---

## Gotchas

- **The contact form is front-end only.** It validates, fakes a send, shows
  success. Point `forms()` at a real endpoint before relying on it.
- **Mobile/desktop mode is decided at page load** — dragging a desktop window
  across 760px needs a reload. Never affects a real phone.
- **`main.css` still carries rules for components no longer in the markup**
  (roughly 40 class names, from pages that were removed). Harmless, but it is
  the next thing to prune if the stylesheet starts feeling unwieldy. Still need
  to verify each by hand.
