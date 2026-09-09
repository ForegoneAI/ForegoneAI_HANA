/* ==========================================================================
   ForegoneAI — HANA
   Motion + canvas layer.  Vanilla JS, no dependencies.
   ========================================================================== */
(function () {
  "use strict";

  const $  = (s, c) => (c || document).querySelector(s);
  const $$ = (s, c) => Array.from((c || document).querySelectorAll(s));
  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const COARSE  = window.matchMedia("(pointer: coarse)").matches;

  /* ======================================================================
     1. Nav — stuck state, drawer, active link
     ====================================================================== */
  function nav() {
    const bar = $(".nav");
    const burger = $(".burger");
    const drawer = $(".drawer");

    if (bar) {
      const onScroll = () => bar.classList.toggle("is-stuck", window.scrollY > 24);
      onScroll();
      window.addEventListener("scroll", onScroll, { passive: true });
    }

    if (burger && drawer) {
      const toggle = (force) => {
        const open = force !== undefined ? force : !document.body.classList.contains("menu-open");
        document.body.classList.toggle("menu-open", open);
        burger.setAttribute("aria-expanded", String(open));
        drawer.setAttribute("aria-hidden", String(!open));
      };
      burger.addEventListener("click", () => toggle());
      $$("a", drawer).forEach((a) => a.addEventListener("click", () => toggle(false)));
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && document.body.classList.contains("menu-open")) toggle(false);
      });
    }

    // active link — works with extensionless / directory URLs (/hana/, /hana,
    // /hana/index.html) and with the flat .html files, so nothing breaks if a
    // page is opened straight off disk.
    const KEYS = ["hana", "systems", "research", "contact"];
    const keyOf = (p) => {
      const seg = String(p || "")
        .split("#")[0].split("?")[0]
        .replace(/\/index\.html?$/i, "/")
        .replace(/\.html?$/i, "")
        .split("/")
        .filter((s) => s && s !== "." && s !== "..")
        .pop();
      return KEYS.indexOf(seg) >= 0 ? seg : "home";
    };
    const page = keyOf(location.pathname);
    $$(".nav__links a, .drawer__links a").forEach((a) => {
      if (keyOf(a.getAttribute("href")) === page) a.classList.add("is-active");
    });
  }

  /* ======================================================================
     2. Scroll progress
     ====================================================================== */
  function progress() {
    const el = $(".progress");
    if (!el) return;
    let raf = 0;
    const run = () => {
      raf = 0;
      const h = document.documentElement.scrollHeight - window.innerHeight;
      el.style.transform = "scaleX(" + (h > 0 ? window.scrollY / h : 0) + ")";
    };
    window.addEventListener("scroll", () => { if (!raf) raf = requestAnimationFrame(run); }, { passive: true });
    run();
  }

  /* ======================================================================
     3. Reveal on scroll
     ====================================================================== */
  function reveals() {
    const els = $$("[data-rv]");
    if (!els.length) return;
    if (REDUCED || !("IntersectionObserver" in window)) {
      els.forEach((e) => e.classList.add("in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (!en.isIntersecting) return;
          const d = parseFloat(en.target.dataset.rvDelay || "0");
          if (d) en.target.style.transitionDelay = d + "s";
          en.target.classList.add("in");
          io.unobserve(en.target);
        });
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.08 }
    );
    els.forEach((e) => io.observe(e));

    // auto-stagger direct children of [data-rv-stagger]
    $$("[data-rv-stagger]").forEach((group) => {
      const step = parseFloat(group.dataset.rvStagger) || 0.07;
      $$("[data-rv]", group).forEach((child, i) => {
        if (!child.dataset.rvDelay) child.dataset.rvDelay = (i * step).toFixed(3);
      });
    });

    // Anything already on screen at first paint reveals straight away. The
    // observer alone can't be trusted with it: its -12% bottom margin is there
    // to hold a reveal until the element is properly in view, but that pulls the
    // trigger line above the fold, so content sitting low in the first screen —
    // a hero's buttons, once the copy is bottom-anchored — clears the viewport
    // yet never clears the threshold, and stays invisible until you scroll.
    const reveal = (el) => {
      const d = parseFloat(el.dataset.rvDelay || "0");
      if (d) el.style.transitionDelay = d + "s";
      el.classList.add("in");
      io.unobserve(el);
    };
    requestAnimationFrame(() => {
      els.forEach((el) => {
        if (el.classList.contains("in")) return;
        const r = el.getBoundingClientRect();
        if (r.top < window.innerHeight && r.bottom > 0) reveal(el);
      });
    });
  }

  /* ======================================================================
     4. Hero headline reveal
     ====================================================================== */
  function heroLines() {
    $$(".rv-stack").forEach((el) => {
      requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("rv-ready")));
    });
  }

  /* ======================================================================
     4b. Decode — hero headlines resolve out of noise once, on arrival.
         Applied only to [data-scramble] (one headline per page) so it stays
         a punctuation mark, not a tic.
     ====================================================================== */
  function decode() {
    const els = $$("[data-scramble]");
    if (!els.length) return;

    // the real wording stays the accessible name whatever the glyphs do
    els.forEach((el) => {
      if (!el.getAttribute("aria-label")) {
        el.setAttribute("aria-label", el.textContent.replace(/\s+/g, " ").trim());
      }
    });
    if (REDUCED) return;

    const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&/<>=+*";
    const pick = () => GLYPHS.charAt((Math.random() * GLYPHS.length) | 0);

    els.forEach((el) => {
      // scramble each line separately so the line structure survives
      const lines = $$(".rv-line > span", el);
      (lines.length ? lines : [el]).forEach((node, li) => {
        const text = node.textContent;
        const chars = text.split("");
        // spaces and punctuation hold still — only letters and digits decode
        const idx = [];
        for (let i = 0; i < chars.length; i++) {
          if (/[A-Za-z0-9]/.test(chars[i])) idx.push(i);
        }
        if (!idx.length) return;

        const step = Math.min(55, 700 / idx.length);
        const base = 340 + li * 120;
        const settle = idx.map((_, n) => base + n * step);
        // Each character holds a glyph for a beat rather than changing every
        // frame. Same overall timing — you can just read the decode happening
        // instead of seeing a blur. Also makes it frame-rate independent.
        const HOLD = 78;
        const swapAt = idx.map(() => 0);
        const shown = idx.map(() => pick());

        // clock starts on the first animation frame, not here: WebGL setup can
        // block the main thread long enough to skip the whole window otherwise
        let t0 = 0, last = "";

        function tick(now) {
          if (!t0) t0 = now;
          const t = now - t0;
          let done = true;
          const out = chars.slice();
          for (let n = 0; n < idx.length; n++) {
            if (t >= settle[n]) continue;
            done = false;
            if (t >= swapAt[n]) {
              shown[n] = pick();
              swapAt[n] = t + HOLD * (0.75 + Math.random() * 0.5);
            }
            out[idx[n]] = shown[n];
          }
          const str = done ? text : out.join("");
          if (str !== last) { node.textContent = str; last = str; }
          if (!done) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
      });
    });
  }

  /* ======================================================================
     5. Parallax
     ====================================================================== */
  function parallax() {
    if (REDUCED) return;
    const items = $$("[data-para]");
    if (!items.length) return;
    let raf = 0;
    const run = () => {
      raf = 0;
      const vh = innerHeight;
      items.forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.bottom < -200 || r.top > vh + 200) return;
        const speed = parseFloat(el.dataset.para) || 0.12;
        const mid = r.top + r.height / 2 - vh / 2;
        el.style.transform = `translate3d(0, ${(-mid * speed).toFixed(2)}px, 0) scale(1.12)`;
      });
    };
    window.addEventListener("scroll", () => { if (!raf) raf = requestAnimationFrame(run); }, { passive: true });
    window.addEventListener("resize", run);
    run();
  }

  /* ======================================================================
     6. Card pointer glow
     ====================================================================== */
  function cardGlow() {
    if (COARSE) return;
    $$(".card").forEach((c) => {
      c.addEventListener("mousemove", (e) => {
        const r = c.getBoundingClientRect();
        c.style.setProperty("--mx", ((e.clientX - r.left) / r.width) * 100 + "%");
        c.style.setProperty("--my", ((e.clientY - r.top) / r.height) * 100 + "%");
      });
    });
  }

  /* ======================================================================
     7. Count-up numbers
     ====================================================================== */
  function counters() {
    const els = $$("[data-count]");
    if (!els.length) return;
    if (REDUCED || !("IntersectionObserver" in window)) {
      els.forEach((e) => (e.textContent = e.dataset.count));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        const el = en.target;
        io.unobserve(el);
        const end = parseFloat(el.dataset.count);
        const dec = (el.dataset.count.split(".")[1] || "").length;
        const dur = 1500;
        const t0 = performance.now();
        const step = (t) => {
          const p = Math.min((t - t0) / dur, 1);
          const e = 1 - Math.pow(1 - p, 3);
          el.textContent = (end * e).toFixed(dec);
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      });
    }, { threshold: 0.5 });
    els.forEach((e) => io.observe(e));
  }

  /* ======================================================================
     8. Network canvas — the "Human-Aligned Network" motif
     ====================================================================== */
  function network() {
    const cvs = $("[data-net]");
    if (!cvs || REDUCED) return;
    const ctx = cvs.getContext("2d");
    if (!ctx) return;

    let w = 0, h = 0, dpr = 1, nodes = [], raf = 0, running = true;
    const mouse = { x: -9999, y: -9999 };

    function resize() {
      const r = cvs.getBoundingClientRect();
      dpr = Math.min(devicePixelRatio || 1, 2);
      w = r.width; h = r.height;
      cvs.width = Math.max(1, Math.floor(w * dpr));
      cvs.height = Math.max(1, Math.floor(h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
    }

    function seed() {
      const target = Math.round(Math.min(120, Math.max(34, (w * h) / 15000)));
      nodes = [];
      for (let i = 0; i < target; i++) {
        nodes.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.22,
          vy: (Math.random() - 0.5) * 0.22,
          r: Math.random() * 1.5 + 0.6,
          p: Math.random() * Math.PI * 2,
        });
      }
    }

    const LINK = 132;

    function draw(t) {
      raf = 0;
      ctx.clearRect(0, 0, w, h);

      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        n.x += n.vx; n.y += n.vy;
        if (n.x < -20) n.x = w + 20; else if (n.x > w + 20) n.x = -20;
        if (n.y < -20) n.y = h + 20; else if (n.y > h + 20) n.y = -20;

        // gentle pull toward pointer
        const dx = mouse.x - n.x, dy = mouse.y - n.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < 34000 && d2 > 1) {
          const f = (1 - d2 / 34000) * 0.014;
          n.vx += dx * f * 0.05;
          n.vy += dy * f * 0.05;
        }
        n.vx *= 0.994; n.vy *= 0.994;
        const sp = Math.hypot(n.vx, n.vy);
        if (sp > 0.5) { n.vx *= 0.5 / sp; n.vy *= 0.5 / sp; }
      }

      // links
      ctx.lineWidth = 0.65;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const d = Math.hypot(dx, dy);
          if (d > LINK) continue;
          const o = (1 - d / LINK) * 0.3;
          ctx.strokeStyle = `rgba(255,255,255,${o.toFixed(3)})`;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }

      // nodes
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        const tw = 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(t * 0.0012 + n.p));
        ctx.fillStyle = `rgba(255,255,255,${(0.5 * tw).toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fill();
      }

      if (running) raf = requestAnimationFrame(draw);
    }

    window.addEventListener("mousemove", (e) => {
      const r = cvs.getBoundingClientRect();
      mouse.x = e.clientX - r.left;
      mouse.y = e.clientY - r.top;
    }, { passive: true });
    window.addEventListener("mouseout", () => { mouse.x = -9999; mouse.y = -9999; });

    let rt = 0;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(resize, 180); });

    // pause when offscreen
    if ("IntersectionObserver" in window) {
      new IntersectionObserver((es) => {
        es.forEach((en) => {
          running = en.isIntersecting;
          if (running && !raf) raf = requestAnimationFrame(draw);
        });
      }, { threshold: 0 }).observe(cvs);
    }

    resize();
    raf = requestAnimationFrame(draw);
  }

  /* ======================================================================
     8b. Hero form — a lit solid, not a wireframe.

     The whole visual language here comes from one idea: a single hard light
     raking across a near-black matte body in a dark room. That is what makes
     the reference read as architecture rather than as a diagram — the form is
     described almost entirely by the crescent of light on its edge, and by
     what the light fails to reach.

     Which means the lighting rig, not the geometry, is the design. Every page
     shares the rig and the material and changes only the primitive, so five
     different objects still read as five photographs of the same room.
     ====================================================================== */
  function heroForm() {
    const cvs = $("[data-gl]");
    if (!cvs || REDUCED) return;
    if (typeof THREE === "undefined") return;

    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas: cvs, alpha: true, antialias: true });
    } catch (e) { return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    // filmic response so the rim can blow out to white without the midtones
    // going chalky — the reference has a very long, very dark falloff
    if (THREE.ACESFilmicToneMapping) {
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.15;
    }
    if (THREE.sRGBEncoding) renderer.outputEncoding = THREE.sRGBEncoding;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 120);
    camera.position.set(0, 0, 13);

    const group = new THREE.Group();
    scene.add(group);

    /* -- the rig ---------------------------------------------------------
       A key placed BEHIND the subject is what draws the crescent: with the
       light on the far side, only the sliver of surface turning away from the
       camera is lit, and the mass in front stays black. A front light would
       flatten it into a grey ball. */
    const key = new THREE.DirectionalLight(0xffffff, 5.2);
    key.position.set(-2.4, 3.0, -7.0);
    scene.add(key);

    // a second, colder rim from the opposite side, so the silhouette closes
    const rim = new THREE.DirectionalLight(0xffffff, 1.9);
    rim.position.set(3.4, 0.5, -6.0);
    scene.add(rim);

    // barely-there front fill: enough to keep the body from reading as a hole
    const fill = new THREE.DirectionalLight(0xffffff, 0.07);
    fill.position.set(1.6, -0.8, 6);
    scene.add(fill);

    // a grazing wash from the front-left. A back key alone describes a sphere
    // beautifully and a flat-sided form not at all — a slab turns its faces away
    // from the rim and reads as a black hole in the frame. This is angled to
    // skim those faces without lifting the sphere's front off black.
    const graze = new THREE.DirectionalLight(0xffffff, 0.55);
    graze.position.set(-6.0, 2.4, 3.2);
    scene.add(graze);

    // sky/ground wash — the room itself
    scene.add(new THREE.HemisphereLight(0xa0a0a0, 0x050505, 0.24));

    /* -- materials -------------------------------------------------------- */
    const shell = new THREE.MeshStandardMaterial({
      color: 0x090909, roughness: 0.30, metalness: 0.34
    });
    const inlay = new THREE.MeshStandardMaterial({
      color: 0x939393, roughness: 0.22, metalness: 0.85
    });
    const faint = new THREE.MeshStandardMaterial({
      color: 0x767676, roughness: 0.2, metalness: 0.95,
      transparent: true, opacity: 0.55
    });

    /* the single point of light on the body — the whole composition hangs off
       this one bright pixel, so it is a real emissive object rather than a
       specular highlight that would drift as the form turns */
    const pip = new THREE.Mesh(
      new THREE.SphereGeometry(0.035, 16, 16),
      new THREE.MeshBasicMaterial({ color: 0xffffff })
    );

    /* -- soft volumetric bloom, drawn once into a canvas texture ----------- */
    function haloTexture() {
      const c = document.createElement("canvas");
      c.width = c.height = 256;
      const g = c.getContext("2d").createRadialGradient(128, 128, 0, 128, 128, 128);
      g.addColorStop(0, "rgba(255,255,255,.55)");
      g.addColorStop(0.35, "rgba(226,226,226,.16)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      const ctx = c.getContext("2d");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 256, 256);
      return new THREE.CanvasTexture(c);
    }
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({
      map: haloTexture(), transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, opacity: 0.9
    }));
    halo.scale.set(11, 11, 1);
    halo.position.set(-0.4, 0.7, -4);
    group.add(halo);

    /* -- the plinth the object stands on ----------------------------------- */
    function plinth(r) {
      const g = new THREE.Group();
      const disc = new THREE.Mesh(
        new THREE.RingGeometry(r * 0.62, r * 1.55, 96),
        new THREE.MeshStandardMaterial({
          color: 0x0e0e0e, roughness: 0.12, metalness: 0.9,
          side: THREE.DoubleSide, transparent: true, opacity: 0.85
        })
      );
      disc.rotation.x = -Math.PI / 2;
      const lip = new THREE.Mesh(new THREE.TorusGeometry(r * 1.5, 0.008, 8, 128), inlay);
      lip.rotation.x = -Math.PI / 2;
      g.add(disc, lip);
      g.position.y = -r * 1.16;
      return g;
    }

    /* a band of fine grooves wrapped round a sphere's equator: each ring is
       sized to the chord at its own height, so they lie ON the surface */
    function grooves(R, count, spread) {
      const g = new THREE.Group();
      for (let i = 0; i < count; i++) {
        const y = ((i / (count - 1)) - 0.5) * spread * R;
        const rr = Math.sqrt(Math.max(R * R - y * y, 0.0001)) * 1.011;
        const t = new THREE.Mesh(new THREE.TorusGeometry(rr, 0.0042, 10, 260), faint);
        t.rotation.x = -Math.PI / 2;
        t.position.y = y;
        g.add(t);
      }
      return g;
    }

    const spin = [];
    const variant = cvs.dataset.gl || "orb";
    let R = 3.1;

    if (variant === "knot") {
      // HANA — one continuous path, drawn as a solid tube
      R = 3.0;
      const knot = new THREE.Mesh(
        new THREE.TorusKnotGeometry(1.95, 0.2, 320, 26, 2, 3), shell
      );
      const halo2 = new THREE.Mesh(new THREE.TorusGeometry(3.0, 0.01, 8, 200), faint);
      halo2.rotation.x = Math.PI / 2.1;
      group.add(knot, halo2, plinth(2.6));
      pip.position.set(0.55, 0.15, 2.15);
      group.add(pip);
      spin.push([knot, 0.0009, 0.0013, 0], [halo2, 0, 0.0007, 0]);

    } else if (variant === "lattice") {
      // Systems — a monolith, and the two smaller masses it governs
      R = 3.0;
      const slab = new THREE.Mesh(new THREE.BoxGeometry(1.9, 4.4, 1.9), shell);
      slab.rotation.y = Math.PI / 4.4;
      const a = new THREE.Mesh(new THREE.BoxGeometry(0.85, 0.85, 0.85), shell);
      a.position.set(-2.15, -1.55, 0.7); a.rotation.y = -Math.PI / 5;
      const b = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.6, 0.6), shell);
      b.position.set(2.0, -1.85, -0.4); b.rotation.y = Math.PI / 3.5;
      const band = new THREE.Mesh(new THREE.BoxGeometry(1.94, 0.012, 1.94), inlay);
      band.position.y = 0.55; band.rotation.y = Math.PI / 4.4;
      group.add(slab, a, b, band, plinth(2.5));
      pip.position.set(0.35, 0.55, 1.0);
      group.add(pip);
      spin.push([slab, 0, 0.00042, 0], [band, 0, 0.00042, 0],
                [a, 0.0008, 0.0011, 0], [b, -0.001, 0.0013, 0]);

    } else if (variant === "meridian") {
      // Research — a faceted mass, cut rather than moulded
      R = 3.05;
      const gem = new THREE.Mesh(new THREE.IcosahedronGeometry(2.5, 1), shell);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(3.05, 0.009, 8, 220), faint);
      ring.rotation.x = -Math.PI / 2;
      const ring2 = new THREE.Mesh(new THREE.TorusGeometry(2.72, 0.007, 8, 220), faint);
      ring2.rotation.set(-Math.PI / 2.35, 0.3, 0);
      group.add(gem, ring, ring2, plinth(2.6));
      pip.position.set(-0.2, 0.35, 2.45);
      group.add(pip);
      spin.push([gem, 0.0004, 0.0009, 0], [ring, 0, 0.0006, 0], [ring2, 0, -0.0005, 0]);

    } else if (variant === "portal") {
      // Contact — an aperture: a ring standing open, nothing inside it
      R = 3.05;
      const ring = new THREE.Mesh(new THREE.TorusGeometry(2.35, 0.26, 28, 200), shell);
      const inner = new THREE.Mesh(new THREE.TorusGeometry(2.09, 0.012, 8, 200), inlay);
      const outer = new THREE.Mesh(new THREE.TorusGeometry(3.0, 0.008, 8, 220), faint);
      outer.rotation.x = -Math.PI / 2.6;
      group.add(ring, inner, outer, plinth(2.5));
      pip.position.set(0, 0, 0);
      group.add(pip);
      spin.push([ring, 0, 0, 0.0005], [inner, 0, 0, -0.0009], [outer, 0, 0.0008, 0]);

    } else {
      // Home — the sphere from the reference, banded at its equator
      R = 3.15;
      const ball = new THREE.Mesh(new THREE.SphereGeometry(R, 96, 72), shell);
      const band = grooves(R, 4, 0.24);
      group.add(ball, band, plinth(R));
      pip.position.set(0.12, 0.05, R * 0.995);
      group.add(pip);
      spin.push([band, 0, 0.00055, 0], [ball, 0, 0.00016, 0]);
    }

    /* a tight glow right at the pip, so it reads as a source and not a dot */
    const spark = new THREE.Sprite(new THREE.SpriteMaterial({
      map: haloTexture(), transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, opacity: 0.55
    }));
    spark.scale.set(1.5, 1.5, 1);
    spark.position.copy(pip.position);
    group.add(spark);

    /* The assembly's real bounds, plinth and all. Fitting to the primitive's
       own radius ignored everything built around it — the plinth sits well
       below the form's centre and reaches wider than it does, so the object
       kept landing hard on the fold. Sprites are skipped: the bloom is
       deliberately larger than the object and would swamp the box. */
    const bounds = (function () {
      group.updateMatrixWorld(true);
      const box = new THREE.Box3();
      group.traverse((o) => { if (o.isMesh) box.expandByObject(o); });
      return box.isEmpty() ? null : box;
    })();

    /* -- fit ---------------------------------------------------------------
       The form is a solid now, so its silhouette barely changes as it turns —
       no envelope probing needed. It is sized off its own radius against the
       frame the nav leaves visible, and sits on the centre line. */
    function resize() {
      const r = cvs.getBoundingClientRect();
      const w = r.width, h = r.height;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();

      const navEl = document.querySelector(".nav");
      const navB = navEl ? navEl.getBoundingClientRect().bottom : 74;
      const scrollY = window.scrollY || window.pageYOffset || 0;
      const occTop = Math.min(Math.max(navB - (r.top + scrollY), 0), h * 0.5);

      const tanHalf = Math.tan((camera.fov * Math.PI / 180) / 2);
      const halfH = tanHalf * camera.position.z;
      const k = (h / 2) / tanHalf;

      // The object stands in the right-hand half, the copy in the left. It is
      // placed against the CONTENT COLUMN rather than the viewport, so it sits
      // on the same grid the copy is measured from — on a wide monitor the copy
      // starts well inside the frame, and a viewport-centred object would drift
      // away from it.
      const band = h - occTop;
      const px = h / (2 * halfH);                       // px per world unit

      // On a narrow frame the stage collapses to one column, so the copy runs
      // the full width and a form placed beside it lands on top of the text.
      // There is no room to the side, so it takes the space below instead:
      // centred, smaller, and seated under the copy.
      const NARROW = w < 760;
      const SEAT  = NARROW ? 0.74 : 0.445;
      const FILLS = NARROW ? 0.42 : 0.62;
      const ZONE  = NARROW ? 0.86 : 0.46;

      let cx = r.left + w * (NARROW ? 0.5 : 0.74), zoneW = w * ZONE;
      const wrapEl = cvs.parentElement && cvs.parentElement.querySelector(".wrap");
      if (wrapEl) {
        const wr = wrapEl.getBoundingClientRect();
        const pad = parseFloat(getComputedStyle(wrapEl).paddingLeft) || 0;
        const cl = wr.left + pad, cw = Math.max(wr.width - pad * 2, 1);
        cx = NARROW ? cl + cw * 0.5 : cl + cw * 0.735;   // beside the copy, or under it
        zoneW = cw * ZONE;
      }
      group.position.x = (cx - (r.left + w / 2)) / px;

      // size and seat from the measured bounds, so what gets centred and what
      // gets fitted is the thing you can actually see
      const bh = bounds ? (bounds.max.y - bounds.min.y) : R * 2;
      const bw = bounds ? Math.max(-bounds.min.x, bounds.max.x) * 2 : R * 2;
      const cy = bounds ? (bounds.max.y + bounds.min.y) / 2 : 0;

      const sc = Math.min((band * FILLS) / px / bh, zoneW / px / bw);
      group.scale.setScalar(sc);
      group.position.y = -((occTop + band * SEAT) - h / 2) / px - cy * sc;
    }

    /* -- motion ------------------------------------------------------------
       The pointer moves the KEY LIGHT as well as the form. That is the whole
       interaction: the crescent travels around the body as you move, so the
       object is read by relighting it rather than by spinning it. */
    const aim = { x: 0, y: 0 }, at = { x: 0, y: 0 };
    if (!COARSE) {
      window.addEventListener("mousemove", (e) => {
        aim.x = (e.clientX / innerWidth) * 2 - 1;
        aim.y = (e.clientY / innerHeight) * 2 - 1;
      }, { passive: true });
    }

    let running = true, raf = 0;
    function frame(t) {
      raf = 0;
      at.x += (aim.x - at.x) * 0.045;
      at.y += (aim.y - at.y) * 0.045;

      group.rotation.y = t * 0.00004 + at.x * 0.20;
      group.rotation.x = at.y * 0.10;

      key.position.set(-2.4 + at.x * 3.0, 3.0 - at.y * 2.4, -7.0);
      graze.position.set(-6.0 + at.x * 2.4, 2.4 - at.y * 1.4, 3.2);
      rim.position.set(3.4 + at.x * 2.0, 0.5 - at.y * 1.1, -6.0);

      for (let i = 0; i < spin.length; i++) {
        const s = spin[i];
        s[0].rotation.x += s[1];
        s[0].rotation.y += s[2];
        s[0].rotation.z += s[3];
      }
      renderer.render(scene, camera);
      if (running) raf = requestAnimationFrame(frame);
    }

    let rt = 0;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(resize, 180); });
    window.addEventListener("load", () => resize());

    if ("IntersectionObserver" in window) {
      new IntersectionObserver((es) => es.forEach((en) => {
        running = en.isIntersecting;
        if (running && !raf) raf = requestAnimationFrame(frame);
      }), { threshold: 0 }).observe(cvs);
    }

    resize();
    raf = requestAnimationFrame(frame);
  }

  /* ======================================================================
     8c. Constellations — content mapped onto the vertices of a rotating form.
         The markup list is the source of truth and the fallback; this lifts
         each item onto its vertex and shows its detail in a readout box.
     ====================================================================== */
  const CSTL_SHAPES = {
    tetra: {
      tilt: [0.34, 0.12],
      verts: [[1, 1, 1], [-1, -1, 1], [-1, 1, -1], [1, -1, -1]],
      edges: [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]]
    },
    octa: {
      tilt: [0.52, 0.34],
      verts: [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]],
      edges: [[0, 2], [0, 3], [0, 4], [0, 5], [1, 2], [1, 3], [1, 4], [1, 5],
              [2, 4], [2, 5], [3, 4], [3, 5]]
    },
    ring: {
      tilt: [0.62, 0.18],
      verts: [[1, 0, 0], [0, 1, 0.35], [-1, 0, 0], [0, -1, -0.35]],
      edges: [[0, 1], [1, 2], [2, 3], [3, 0]]
    },
    // smooth continuous curves — points ride the path instead of sitting on
    // corners. curve: [p, q] of a torus knot, matching the HANA hero language.
    knot: { curve: [2, 3], radius: 1.85, tilt: [0.42, 0.16] },
    knotAlt: { curve: [3, 2], radius: 1.85, tilt: [0.56, 0.3] },
    cube: {
      tilt: [0.38, 0.2],
      verts: [[1, 1, 1], [1, 1, -1], [1, -1, 1], [1, -1, -1],
              [-1, 1, 1], [-1, 1, -1], [-1, -1, 1], [-1, -1, -1]],
      edges: [[0, 1], [0, 2], [0, 4], [1, 3], [1, 5], [2, 3],
              [2, 6], [3, 7], [4, 5], [4, 6], [5, 7], [6, 7]]
    }
  };

  function constellations() {
    const boxes = $$("[data-cstl]");
    if (!boxes.length || REDUCED || typeof THREE === "undefined") return;

    const build = (box) => {
      const canvas = $(".cstl__gl", box);
      /* Below this width the 3-D version is the wrong answer: the labels are
         absolutely positioned at projected vertices, so on a narrow frame they
         run off the sides and their hit areas shrink under a fingertip. The
         no-JS fallback — a plain list with every title and description on the
         page — is simply better here, so leave it alone. */
      if (window.innerWidth < 760) return;

      const items = $$(".cstl__nodes > li", box);
      const panel = $("[data-panel]", box);
      const spec = CSTL_SHAPES[box.dataset.shape] || CSTL_SHAPES.tetra;
      if (!canvas || !items.length) return;
      if (!spec.curve && items.length > spec.verts.length) return;

      let renderer;
      try {
        renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
      } catch (e) { return; }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
      camera.position.set(0, 0, 6.2);
      const glow = new THREE.Color(0xffffff);
      const ink = new THREE.Color(0xb4b4b4);
      const group = new THREE.Group();
      scene.add(group);

      /* the same rig the hero uses, so the diagram belongs to the same room:
         a key from behind to draw the rim, a grazing wash for the flat facets,
         and a low ambient so nothing goes fully to paper-black */
      const ckey = new THREE.DirectionalLight(0xffffff, 4.0);
      ckey.position.set(-2.0, 2.6, -5.5);
      const cgraze = new THREE.DirectionalLight(0xffffff, 0.95);
      cgraze.position.set(-5.0, 2.0, 3.0);
      const crim = new THREE.DirectionalLight(0xffffff, 1.6);
      crim.position.set(3.6, 0.8, -4.5);
      scene.add(ckey, cgraze, crim, new THREE.HemisphereLight(0xa8a8a8, 0x060606, 0.34));

      const R = 2.55;
      const tilt = spec.tilt || [0.35, 0.15];
      const linePts = [];
      let pos;

      if (spec.curve) {
        // point on a (p,q) torus knot at t in [0,1)
        const P = spec.curve[0], Q = spec.curve[1], KR = spec.radius || 1.85;
        const at = (t) => {
          const u = t * Math.PI * 2 * P;
          const qp = (Q / P) * u;
          const cs = Math.cos(qp);
          return new THREE.Vector3(
            KR * (2 + cs) * 0.5 * Math.cos(u),
            KR * (2 + cs) * 0.5 * Math.sin(u),
            KR * Math.sin(qp) * 0.5
          );
        };
        // information points spaced evenly along the path
        pos = [];
        for (let i = 0; i < items.length; i++) pos.push(at(i / items.length));
        // the path itself, drawn smoothly
        const SEG = 420;
        for (let i = 0; i < SEG; i++) linePts.push(at(i / SEG), at((i + 1) / SEG));
      } else {
        pos = spec.verts.map((v) => new THREE.Vector3(v[0], v[1], v[2]).normalize().multiplyScalar(R));
        spec.edges.forEach((e) => { linePts.push(pos[e[0]].clone(), pos[e[1]].clone()); });
      }
      /* The armature is drawn as SUBSTANCE, not as a line.

         A LineBasicMaterial is unlit — it is a flat stroke of colour, and no
         lighting rig can touch it, which is why this section never belonged to
         the same world as the hero. Rendered as thin tubes it becomes real
         geometry: the key rakes along it, a specular highlight travels the
         length as the form turns, and it picks up the room the way the hero
         objects do. Same armature, same silhouette — only the material is new. */
      const filament = new THREE.MeshStandardMaterial({
        color: 0xa2a8ae, roughness: 0.3, metalness: 0.9
      });
      if (spec.curve) {
        const path = new THREE.CatmullRomCurve3(
          linePts.filter((_, n) => n % 2 === 0), true, "catmullrom", 0.5
        );
        group.add(new THREE.Mesh(new THREE.TubeGeometry(path, 520, 0.019, 12, true), filament));
      } else {
        // one slim cylinder per edge, aimed from vertex to vertex
        const up = new THREE.Vector3(0, 1, 0), dir = new THREE.Vector3();
        for (let n = 0; n < linePts.length; n += 2) {
          const a2 = linePts[n], b2 = linePts[n + 1];
          const len = a2.distanceTo(b2);
          const tube = new THREE.Mesh(
            new THREE.CylinderGeometry(0.019, 0.019, len, 12, 1, true), filament
          );
          tube.position.copy(a2).add(b2).multiplyScalar(0.5);
          tube.quaternion.setFromUnitVectors(up, dir.copy(b2).sub(a2).normalize());
          group.add(tube);
        }
      }

      // a marker at every vertex that carries information
      /* a soft source in the scene, off to one side — the same bloom the hero
         forms carry, so the light in this section reads as coming from
         somewhere rather than being painted on */
      function cHalo() {
        const cv = document.createElement("canvas");
        cv.width = cv.height = 256;
        const ctx = cv.getContext("2d");
        const g2 = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
        g2.addColorStop(0, "rgba(255,255,255,.5)");
        g2.addColorStop(0.35, "rgba(226,226,226,.14)");
        g2.addColorStop(1, "rgba(255,255,255,0)");
        ctx.fillStyle = g2;
        ctx.fillRect(0, 0, 256, 256);
        return new THREE.CanvasTexture(cv);
      }
      const source = new THREE.Sprite(new THREE.SpriteMaterial({
        map: cHalo(), transparent: true, depthWrite: false,
        blending: THREE.AdditiveBlending, opacity: 0.5
      }));
      source.scale.set(6.2, 6.2, 1);
      source.position.set(-1.5, 1.1, -2.6);
      scene.add(source);
      // and a real lamp at the same spot, so the filaments actually catch it
      const lamp = new THREE.PointLight(0xffffff, 2.4, 14, 2);
      lamp.position.set(-1.5, 1.1, -1.6);
      scene.add(lamp);

      // vertices are polished, not painted — they take a highlight from the rig
      const dots = pos.slice(0, items.length).map((p) => {
        const d = new THREE.Mesh(
          new THREE.SphereGeometry(0.082, 20, 20),
          new THREE.MeshStandardMaterial({
            color: 0xf2f2f2, roughness: 0.12, metalness: 0.5,
            emissive: 0x8f8f8f, emissiveIntensity: 0.55
          })
        );
        d.position.copy(p);
        group.add(d);
        return d;
      });

      // generous invisible spheres so the vertex itself is easy to hover —
      // the visible dot is far too small to be a comfortable target
      const hits = pos.slice(0, items.length).map((p, i) => {
        const hit = new THREE.Mesh(
          new THREE.SphereGeometry(0.42, 12, 12),
          new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })
        );
        hit.position.copy(p);
        hit.userData.i = i;
        group.add(hit);
        return hit;
      });
      /* No centre object. The vertices and the armature between them are the
         content; anything in the middle competed with the labels for the one
         part of the frame they all have to cross. `decor` stays so the frame
         loop keeps its shape. */
      const decor = [];

      const ray = new THREE.Raycaster();
      const ndc = new THREE.Vector2();
      let inside = false, overLabel = -1, overVertex = -1;

      // the row number lives on the <li>; the button is what carries the style
      items.forEach((li) => {
        const btn = $(".cstl__node", li);
        if (btn && li.dataset.k) btn.setAttribute("data-k", li.dataset.k);
      });
      box.classList.add("is-3d");

      /* ---- interaction ---- */
      let active = -1;
      function setActive(i) {
        if (active === i) return;
        active = i;
        items.forEach((li, n) => li.classList.toggle("is-on", n === i));
        dots.forEach((d, n) => {
          d.scale.setScalar(n === i ? 2.0 : 1);
          d.material.emissiveIntensity = n === i ? 1.6 : 0.55;
        });
        if (!panel) return;
        if (i < 0) { panel.classList.remove("is-on"); return; }
        const li = items[i];
        const t = $(".cstl__node-t", li);
        const bd = $(".cstl__node-b", li);
        panel.textContent = "";
        if (li.dataset.k) {
          const k = document.createElement("span");
          k.className = "k"; k.textContent = li.dataset.k; panel.appendChild(k);
        }
        const hh = document.createElement("h4");
        hh.textContent = t ? t.textContent : "";
        panel.appendChild(hh);
        if (bd) {
          const pp = document.createElement("p");
          pp.textContent = bd.textContent;
          panel.appendChild(pp);
        }
        panel.classList.add("is-on");
        place();
      }

      // label and vertex are two ways into the same state; the label wins
      // when both are true so the readout never flickers between them
      function refresh() { setActive(overLabel >= 0 ? overLabel : overVertex); }

      items.forEach((li, i) => {
        const btn = $(".cstl__node", li) || li;
        // the pointer target is the whole ROW, because the row is what
        // highlights — binding this to the button alone left most of the
        // highlighted area dead, including the number and the description
        btn.addEventListener("mouseenter", () => { overLabel = i; refresh(); });
        btn.addEventListener("mouseleave", () => { if (overLabel === i) { overLabel = -1; refresh(); } });
        btn.addEventListener("focus", () => { overLabel = i; refresh(); });
        btn.addEventListener("blur", () => { if (overLabel === i) { overLabel = -1; refresh(); } });
        btn.addEventListener("click", (e) => {
          if (btn.tagName !== "A") { e.preventDefault(); overLabel = i; refresh(); }
        });
      });

      // clicking a vertex follows its link, where it has one
      box.addEventListener("click", () => {
        if (overVertex < 0 || overLabel >= 0) return;
        const a = $(".cstl__node", items[overVertex]);
        if (a && a.tagName === "A") a.click();
      });
      // the form settles while the pointer is inside, so labels stop moving
      // under the cursor and stay clickable
      let spin = 0.0022, spinTo = 0.0022;
      box.addEventListener("mouseenter", () => { spinTo = 0; });
      box.addEventListener("mouseleave", () => {
        spinTo = 0.0022; inside = false; overLabel = -1; overVertex = -1;
        box.style.cursor = ""; setActive(-1);
      });
      box.addEventListener("focusin", () => { spinTo = 0; });
      box.addEventListener("focusout", () => { spinTo = 0.0022; });

      /* ---- pointer parallax ---- */
      const mouse = { x: 0, y: 0 }, target = { x: 0, y: 0 };
      if (!COARSE) {
        box.addEventListener("mousemove", (e) => {
          const r = box.getBoundingClientRect();
          mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1;
          mouse.y = ((e.clientY - r.top) / r.height) * 2 - 1;
          ndc.x = mouse.x;
          ndc.y = -mouse.y;
          inside = true;
        }, { passive: true });
      }

      let w = 0, h = 0;
      function resize() {
        const r = canvas.getBoundingClientRect();
        w = r.width; h = r.height;
        if (!w || !h) return;
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.position.z = w / h < 1 ? 8.2 : 6.2;
        camera.updateProjectionMatrix();
      }

      // project each vertex to screen space and park its label there
      const v = new THREE.Vector3();
      const sides = items.map(function () { return 1; });
      /* The labels are no longer pinned to the projected vertices.

         That pattern cannot be made to work: the anchors are points on a
         rotating 3-D form, so they drift, bunch and cross the middle, and every
         fix for one collision creates another. Worse, it hid each item's
         description behind a hover — the content was there and unreadable.

         The list is now a list: numbered rows, title and description both
         visible, in reading order, working without JavaScript. The form keeps
         its job as the visual and gains a real one — hovering a row lights that
         row's point on the object, and hovering a point lights its row. The
         interaction survives; the content stops depending on it. */
      /* Each label sits on its own vertex. Nothing is displaced to avoid a
         neighbour: the moment a label is moved off its point, the pairing has
         to be re-explained with a leader, and a screen full of leaders reads
         as clutter. Labels close to their points, occasionally overlapping,
         is the more legible trade — so the only thing decided here is which
         SIDE of its vertex a label sits on, with hysteresis so it doesn't
         flicker as the form turns. */
      function place() {
        for (let i = 0; i < items.length; i++) {
          v.copy(pos[i]).applyMatrix4(group.matrixWorld).project(camera);
          const x = (v.x * 0.5 + 0.5) * w;
          const y = (-v.y * 0.5 + 0.5) * h;
          const depth = Math.min(Math.max((v.z + 1) / 2, 0), 1);   // 0 near → 1 far
          const li = items[i];

          const rel = x / w - 0.5;
          if (rel > 0.05) sides[i] = 1; else if (rel < -0.05) sides[i] = -1;

          const off = x + sides[i] * 16;
          li.style.transform =
            (sides[i] < 0 ? "translate(-100%,-50%) " : "translate(0,-50%) ") +
            "translate(" + off.toFixed(1) + "px," + y.toFixed(1) + "px)";
          li.classList.toggle("is-left", sides[i] < 0);
          // depth does the ordering: a label in front of the form covers one
          // behind it, which is the natural way to read two that coincide
          li.style.opacity = (1 - depth * 0.5).toFixed(2);
          li.style.zIndex = String(100 - Math.round(depth * 100));

          if (i === active && panel) {
            const pw = panel.offsetWidth, ph = panel.offsetHeight;
            let px = x + sides[i] * 26;
            if (sides[i] < 0) px -= pw;
            let py = y - ph / 2;
            px = Math.max(8, Math.min(px, w - pw - 8));
            py = Math.max(8, Math.min(py, h - ph - 8));
            panel.style.transform = "translate(" + px.toFixed(1) + "px," + py.toFixed(1) + "px)";
          }
        }
      }

      let running = true, raf = 0;
      function frame() {
        raf = 0;
        // once a point is engaged the tilt locks, so the label can't drift
        // out from under the cursor while you're reading it
        if (active < 0) {
          target.x += (mouse.y * 0.3 - target.x) * 0.05;
          target.y += (mouse.x * 0.4 - target.y) * 0.05;
        }
        group.rotation.x = tilt[0] + target.x;
        group.rotation.z = tilt[1];
        spin += (spinTo - spin) * 0.07;
        group.rotation.y += spin;
        for (let i = 0; i < decor.length; i++) {
          const d = decor[i];
          d[0].rotation.x += d[1];
          d[0].rotation.y += d[2];
          d[0].rotation.z += d[3];
        }
        group.updateMatrixWorld();
        if (inside) {
          ray.setFromCamera(ndc, camera);
          const hit = ray.intersectObjects(hits, false)[0];
          const idx = hit ? hit.object.userData.i : -1;
          if (idx !== overVertex) {
            overVertex = idx;
            box.style.cursor = idx >= 0 ? "pointer" : "";
            refresh();
          }
        }
        place();
        renderer.render(scene, camera);
        if (running) raf = requestAnimationFrame(frame);
      }

      let rt = 0;
      window.addEventListener("resize", () => {
        clearTimeout(rt);
        rt = setTimeout(() => { resize(); }, 180);
      });

      if ("IntersectionObserver" in window) {
        new IntersectionObserver((es) => es.forEach((en) => {
          running = en.isIntersecting;
          if (running && !raf) raf = requestAnimationFrame(frame);
        }), { threshold: 0 }).observe(box);
      }

      resize();
      raf = requestAnimationFrame(frame);
    };

    // Build each form only as it nears the viewport. Creating every WebGL
    // context at load blocked the main thread long enough to swallow the
    // hero's decode animation, and most of these are far below the fold.
    if (!("IntersectionObserver" in window)) { boxes.forEach(build); return; }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        io.unobserve(en.target);
        build(en.target);
      });
    }, { rootMargin: "400px 0px" });
    boxes.forEach((box) => io.observe(box));
  }

  /* ======================================================================
     9. WebGL amber field  (graceful no-op if unsupported)
     ====================================================================== */
  function field() {
    const cvs = $("[data-field]");
    if (!cvs || REDUCED) return;

    // Compile only as the CTA approaches. This lives at the very bottom of
    // every page, and compiling its shader at load stalled the main thread
    // through the whole hero animation.
    if ("IntersectionObserver" in window) {
      const gate = new IntersectionObserver((es) => {
        if (!es.some((en) => en.isIntersecting)) return;
        gate.disconnect();
        build();
      }, { rootMargin: "500px 0px" });
      gate.observe(cvs);
    } else {
      build();
    }

    function build() {
    const gl = cvs.getContext("webgl", { alpha: true, antialias: false, premultipliedAlpha: false });
    if (!gl) return;

    const VS = `attribute vec2 p; void main(){ gl_Position = vec4(p,0.,1.); }`;
    const FS = `
      precision highp float;
      uniform vec2 u_res;
      uniform float u_t;

      float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
      float noise(vec2 p){
        vec2 i = floor(p), f = fract(p);
        vec2 u = f*f*(3.-2.*f);
        return mix(mix(hash(i), hash(i+vec2(1,0)), u.x),
                   mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), u.x), u.y);
      }
      float fbm(vec2 p){
        float v = 0., a = .5;
        for(int i=0;i<5;i++){ v += a*noise(p); p *= 2.03; a *= .5; }
        return v;
      }

      void main(){
        vec2 uv = gl_FragCoord.xy / u_res.xy;
        vec2 q = uv;
        q.x *= u_res.x / u_res.y;

        float t = u_t * 0.035;
        vec2 w = vec2(fbm(q*2.2 + t), fbm(q*2.2 - t + 5.2));
        float n = fbm(q*2.6 + w*1.5 + t*0.7);

        // horizon-style dusk falloff
        float band = smoothstep(0.05, 0.95, uv.y);
        float core = smoothstep(0.62, 0.02, abs(uv.y - 0.42 - n*0.16));

        vec3 deep  = vec3(0.031, 0.027, 0.039);
        vec3 amber = vec3(0.910, 0.588, 0.227);
        vec3 gold  = vec3(0.957, 0.776, 0.478);
        vec3 teal  = vec3(0.475, 0.765, 0.741);

        vec3 col = deep;
        col = mix(col, amber, core * (0.34 + 0.3*n));
        col = mix(col, gold,  core * pow(n, 3.0) * 0.55);
        col = mix(col, teal,  smoothstep(0.55,1.0,uv.y) * n * 0.10);

        // vignette
        vec2 c = uv - 0.5;
        float vig = 1.0 - dot(c,c) * 1.35;
        col *= clamp(vig, 0.0, 1.0);

        float alpha = clamp(core * 0.85 + band * 0.06, 0.0, 1.0);
        gl_FragColor = vec4(col, alpha);
      }`;

    function sh(type, src) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { console.warn(gl.getShaderInfoLog(s)); return null; }
      return s;
    }
    const vs = sh(gl.VERTEX_SHADER, VS), fs = sh(gl.FRAGMENT_SHADER, FS);
    if (!vs || !fs) return;
    const prog = gl.createProgram();
    gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    const uRes = gl.getUniformLocation(prog, "u_res");
    const uT   = gl.getUniformLocation(prog, "u_t");

    let running = true, raf = 0;
    function resize() {
      const r = cvs.getBoundingClientRect();
      const d = Math.min(devicePixelRatio || 1, 1.5);
      cvs.width = Math.max(1, Math.floor(r.width * d));
      cvs.height = Math.max(1, Math.floor(r.height * d));
      gl.viewport(0, 0, cvs.width, cvs.height);
      gl.uniform2f(uRes, cvs.width, cvs.height);
    }
    function frame(t) {
      raf = 0;
      gl.uniform1f(uT, t * 0.001);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      if (running) raf = requestAnimationFrame(frame);
    }
    let rt = 0;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(resize, 180); });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver((es) => es.forEach((en) => {
        running = en.isIntersecting;
        if (running && !raf) raf = requestAnimationFrame(frame);
      }), { threshold: 0 }).observe(cvs);
    }
    resize();
    raf = requestAnimationFrame(frame);
    }
  }

  /* ======================================================================
     10. Videos — play only when visible, honour reduced motion
     ====================================================================== */
  function videos() {
    const vids = $$("video[data-auto]");
    if (!vids.length) return;
    if (REDUCED) { vids.forEach((v) => { v.removeAttribute("autoplay"); v.pause(); }); return; }
    if (!("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((es) => {
      es.forEach((en) => {
        const v = en.target;
        if (en.isIntersecting) { const p = v.play(); if (p && p.catch) p.catch(() => {}); }
        else v.pause();
      });
    }, { threshold: 0.08 });
    vids.forEach((v) => io.observe(v));
  }

  /* ======================================================================
     11. Marquee — duplicate track for a seamless loop
     ====================================================================== */
  function marquee() {
    $$(".marquee__track").forEach((track) => {
      if (track.children.length === 1) track.appendChild(track.firstElementChild.cloneNode(true));
    });
  }

  /* ======================================================================
     12. Contact form (front-end only)
     ====================================================================== */
  function forms() {
    $$("form[data-form]").forEach((f) => {
      f.addEventListener("submit", (e) => {
        e.preventDefault();
        if (!f.reportValidity()) return;
        const ok = $(".form__ok", f.closest("[data-form-wrap]") || f.parentElement);
        const btn = $("button[type=submit]", f);
        if (btn) { btn.disabled = true; btn.textContent = "Sending…"; }
        setTimeout(() => {
          f.reset();
          if (btn) { btn.disabled = false; btn.innerHTML = 'Send inquiry <span class="arw" aria-hidden="true">→</span>'; }
          if (ok) { ok.classList.add("show"); ok.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
        }, 700);
      });
    });
  }

  /* ======================================================================
     12b. Insights index — filter entries by stream
     ====================================================================== */
  function insightFilters() {
    const bar = $(".filters");
    if (!bar) return;
    const btns = $$(".filter", bar);
    const posts = $$("[data-cat]");
    const empty = $("[data-empty]");
    if (!btns.length || !posts.length) return;

    bar.addEventListener("click", (e) => {
      const btn = e.target.closest(".filter");
      if (!btn) return;
      const f = btn.dataset.filter || "all";
      btns.forEach((b) => b.classList.toggle("is-on", b === btn));

      let shown = 0;
      posts.forEach((p) => {
        const hit = f === "all" || p.dataset.cat === f;
        p.classList.toggle("is-hidden", !hit);
        if (hit) shown++;
      });
      if (empty) empty.hidden = shown > 0;
    });

    // pointer glow on entry cards, same as .card
    if (!COARSE) {
      posts.forEach((p) => {
        p.addEventListener("mousemove", (e) => {
          const r = p.getBoundingClientRect();
          p.style.setProperty("--mx", ((e.clientX - r.left) / r.width) * 100 + "%");
          p.style.setProperty("--my", ((e.clientY - r.top) / r.height) * 100 + "%");
        });
      });
    }
  }

  /* ======================================================================
     13. Year stamp
     ====================================================================== */
  function year() {
    $$("[data-year]").forEach((e) => (e.textContent = new Date().getFullYear()));
  }

  /* ---------------------------------------------------------------- init */
  function init() {
    nav(); progress(); reveals(); heroLines(); decode(); parallax();
    cardGlow(); counters(); network(); heroForm(); constellations();
    field(); videos(); marquee();
    forms(); insightFilters(); year();
    document.documentElement.classList.add("js-ready");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
