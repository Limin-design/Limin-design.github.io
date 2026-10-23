// Cinematic scroll for the portfolio: an opening shot, then one pinned scene per project
// where the program "runs" as you scroll. Without GSAP (or with reduced motion) the page shows every scene finished.
(function () {
  var root = document.documentElement;

  // Deterministic random numbers, so the charts look the same on every visit.
  var seed = 7;
  function rnd() { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }

  buildCharts();
  buildDots();

  if (!window.gsap || !window.ScrollTrigger || !root.classList.contains("anim")) {
    root.classList.remove("anim");
    finalStates();
    return;
  }
  gsap.registerPlugin(ScrollTrigger);

  // ---- Opening: letterbox bars part, title rises
  gsap.timeline({ defaults: { ease: "power3.out" } })
    .to(".letterbox.top-bar", { yPercent: -82, duration: 1.4, ease: "power4.inOut" }, 0.2)
    .to(".letterbox.bottom-bar", { yPercent: 82, duration: 1.4, ease: "power4.inOut" }, 0.2)
    .from(".slate", { opacity: 0, x: -20, duration: .8 }, 1.0)
    .from(".opening h1 .ln > span", { yPercent: 110, duration: 1.1, stagger: .12 }, 1.05)
    .from(".opening .lead", { opacity: 0, y: 20, duration: .9 }, 1.45)
    .from(".opening .actions", { opacity: 0, y: 20, duration: .9 }, 1.6)
    .from(".cue", { opacity: 0, duration: .8 }, 2.0);
  // Leaving the opening: the bars close a little and the title drifts away, like a cut
  gsap.fromTo(".letterbox.top-bar", { yPercent: -82 }, { yPercent: -60, ease: "none", immediateRender: false,
    scrollTrigger: { trigger: ".opening", start: "top top", end: "bottom top", scrub: true } });
  gsap.fromTo(".letterbox.bottom-bar", { yPercent: 82 }, { yPercent: 60, ease: "none", immediateRender: false,
    scrollTrigger: { trigger: ".opening", start: "top top", end: "bottom top", scrub: true } });
  gsap.to(".opening .wrap", { yPercent: -18, opacity: 0, ease: "none",
    scrollTrigger: { trigger: ".opening", start: "top top", end: "bottom top", scrub: true } });

  // Reel progress bar; its colour follows the scene on screen
  var reel = document.querySelector(".reel");
  gsap.to(reel, { scaleX: 1, ease: "none", scrollTrigger: { trigger: "body", start: "top top", end: "bottom bottom", scrub: .3 } });

  gsap.from(".titlecard h2", { opacity: 0, y: 40, filter: "blur(8px)", duration: 1.2, ease: "power3.out",
    scrollTrigger: { trigger: ".titlecard", start: "top 70%" } });

  var builders = { pricing: pricing, accounting: accounting, stratforge: stratforge, kronos: kronos, directory: directory, grid: grid, dashboard: dashboard };

  ScrollTrigger.matchMedia({
    // Desktop: each scene is pinned and the program plays as you scroll
    "(min-width: 961px)": function () {
      document.querySelectorAll(".scene").forEach(function (sc) {
        var stage = sc.querySelector(".stage"), screen = sc.querySelector(".screen");
        var tl = gsap.timeline({ defaults: { ease: "power2.out" } });
        tl.fromTo(sc.querySelectorAll(".copy > *"), { opacity: 0, y: 30 }, { opacity: 1, y: 0, stagger: .08, duration: .6 }, 0)
          .fromTo(screen, { opacity: 0, y: 60, rotateX: 12, scale: .92, transformPerspective: 1400 }, { opacity: 1, y: 0, rotateX: 0, scale: 1, duration: .9 }, 0);
        builders[stage.dataset.scene](tl, stage, 0.6);
        tl.to(screen, { scale: 1.04, duration: 1.2, ease: "none" }, ">-0.2"); // slow push-in at the end of the shot
        ScrollTrigger.create({ trigger: sc, start: "top top", end: "+=170%", pin: true, scrub: 0.8, animation: tl,
          onToggle: function (self) { if (self.isActive) reel.style.background = getComputedStyle(sc).getPropertyValue("--sa"); } });
      });
    },
    // Mobile: no pinning; each scene plays once when it comes into view
    "(max-width: 960px)": function () {
      document.querySelectorAll(".scene").forEach(function (sc) {
        var stage = sc.querySelector(".stage"), screen = sc.querySelector(".screen");
        var tl = gsap.timeline({ defaults: { ease: "power2.out" }, scrollTrigger: { trigger: sc, start: "top 75%" } });
        tl.fromTo(sc.querySelectorAll(".copy > *"), { opacity: 0, y: 24 }, { opacity: 1, y: 0, stagger: .07, duration: .5 }, 0)
          .fromTo(screen, { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: .7 }, .2);
        builders[stage.dataset.scene](tl, stage, .5);
      });
    }
  });

  gsap.from(".credits .wrap > *", { opacity: 0, y: 30, stagger: .1, duration: .9, ease: "power3.out", scrollTrigger: { trigger: ".credits", start: "top 70%" } });

  // ---------- scene timelines ----------
  function counter(tl, el, at, dur) {
    var end = +el.dataset.count, o = { v: 0 };
    tl.to(o, { v: end, duration: dur || 1, ease: "power1.out", onUpdate: function () { el.textContent = Math.round(o.v).toLocaleString("en-US"); } }, at);
  }
  function scanPass(tl, stage, at, dur) {
    var s = stage.querySelector(".scan");
    tl.fromTo(s, { top: -60, opacity: 1 }, { top: 420, duration: dur, ease: "none" }, at).to(s, { opacity: 0, duration: .1 });
  }

  function pricing(tl, st, t) {
    tl.from(st.querySelector(".inv"), { x: -60, rotate: -6, opacity: 0, duration: .7 }, t);
    scanPass(tl, st, t + .5, 1);
    tl.from(st.querySelectorAll(".inv-chips .chip"), { scale: .6, opacity: 0, stagger: .15, duration: .35, ease: "back.out(2)" }, t + 1.3)
      .from(st.querySelector(".props h5"), { opacity: 0, duration: .3 }, t + 1.7)
      .from(st.querySelectorAll(".prop"), { x: 40, opacity: 0, stagger: .15, duration: .45 }, t + 1.8)
      .from(st.querySelectorAll(".prop b"), { color: "#f4c95d", scale: 1.3, stagger: .15, duration: .4 }, t + 2.1)
      .from(st.querySelector(".approve"), { opacity: 0, y: 14, duration: .4 }, t + 2.5)
      .to(st.querySelector(".approve .fill"), { scaleX: 1, duration: .9, ease: "power2.inOut" }, t + 2.9)
      .to(st.querySelector(".approve .pre"), { opacity: 0, duration: .2 }, t + 3.1)
      .to(st.querySelector(".approve .post"), { opacity: 1, duration: .3 }, t + 3.6);
  }

  function accounting(tl, st, t) {
    var rows = st.querySelectorAll(".ledger tr");
    tl.from(rows, { opacity: 0, x: -20, stagger: .05, duration: .3 }, t);
    scanPass(tl, st, t + .5, 1.6);
    var k = 0;
    rows.forEach(function (r) {
      if (!r.dataset.why) return;
      var why = r.querySelector(".why"), cells = r.querySelectorAll("td");
      why.textContent = "⚑ " + r.dataset.why;
      var at = t + .7 + k * .38; k++;
      tl.to(cells, { backgroundColor: "rgba(255,107,107,.10)", duration: .2 }, at)
        .to(why, { opacity: 1, duration: .25 }, at);
    });
    tl.from(st.querySelector(".acc-side"), { opacity: 0, y: 20, duration: .4 }, t + 1.2);
    counter(tl, st.querySelector("[data-count]"), t + 1.3, 1.4);
    tl.to(st.querySelectorAll(".f1 .bar"), { scaleY: 1, stagger: .25, duration: .6, ease: "back.out(1.6)" }, t + 2.2)
      .to(st.querySelector(".cite"), { opacity: 1, duration: .3 }, t + 2.8);
  }

  function stratforge(tl, st, t) {
    tl.from(st.querySelectorAll(".candles g"), { opacity: 0, scaleY: 0, transformOrigin: "50% 50%", stagger: .02, duration: .25 }, t);
    var eq = st.querySelector(".equity"), L = eq.getTotalLength();
    tl.fromTo(eq, { strokeDasharray: L, strokeDashoffset: L }, { strokeDashoffset: 0, duration: 1.4, ease: "power1.inOut" }, t + .8)
      .from(st.querySelectorAll(".fan path"), { opacity: 0, stagger: .06, duration: .4 }, t + 2.0)
      .from(st.querySelectorAll(".badges .chip"), { opacity: 0, y: 10, stagger: .15, duration: .3 }, t + 2.3);
  }

  function kronos(tl, st, t) {
    var a = st.querySelector(".actual"), L = a.getTotalLength();
    tl.fromTo(a, { strokeDasharray: L, strokeDashoffset: L }, { strokeDashoffset: 0, duration: 1.6, ease: "none" }, t)
      .from(st.querySelectorAll(".calls circle"), { opacity: 0, scale: 0, transformOrigin: "50% 50%", stagger: .05, duration: .2 }, t + .2)
      .from(st.querySelectorAll(".badges .chip"), { opacity: 0, y: 10, stagger: .2, duration: .3 }, t + 1.7);
    counter(tl, st.querySelector("[data-count]"), t + 1.8, .8);
    tl.to(st.querySelector(".stamp"), { opacity: 1, scale: 1, duration: .45, ease: "back.out(2.2)" }, t + 2.6);
  }

  function directory(tl, st, t) {
    var dots = st.querySelectorAll(".dots i");
    tl.to(dots, { backgroundColor: function (i) { return dots[i].dataset.c; }, stagger: { each: .008, from: "random" }, duration: .15 }, t);
    counter(tl, st.querySelector("[data-count]"), t, 1.8);
    tl.to(st.querySelectorAll(".term .l"), { opacity: 1, stagger: .35, duration: .2 }, t + .4);
  }

  function grid(tl, st, t) {
    tl.from(st.querySelectorAll(".node"), { opacity: 0, y: 14, stagger: .15, duration: .4 }, t);
    st.querySelectorAll(".links path").forEach(function (p, i) {
      if (i > 2) { tl.from(p, { opacity: 0, duration: .4 }, t + .9 + i * .1); return; }
      var L = p.getTotalLength();
      tl.fromTo(p, { strokeDasharray: L, strokeDashoffset: L }, { strokeDashoffset: 0, duration: .5 }, t + .5 + i * .12);
    });
    tl.to(st.querySelectorAll(".checks div"), { opacity: 1, stagger: .3, duration: .2 }, t + .9)
      .to(st.querySelector(".packet"), { attr: { cx: 300 }, duration: .5, ease: "power1.inOut" }, t + 2.1)
      .to(st.querySelector(".packet"), { attr: { cx: 480 }, duration: .5, ease: "power1.inOut" }, t + 2.6)
      .to(st.querySelector(".packet"), { attr: { r: 11 }, opacity: 0, duration: .3 }, t + 3.1);
  }

  function dashboard(tl, st, t) {
    tl.from(st.querySelectorAll(".kpi"), { opacity: 0, y: 14, stagger: .12, duration: .35 }, t);
    st.querySelectorAll(".kpi [data-count]").forEach(function (el, i) { counter(tl, el, t + .2 + i * .1, 1.2); });
    tl.to(st.querySelectorAll(".bars div"), { scaleY: 1, stagger: .12, duration: .7, ease: "back.out(1.4)" }, t + .6)
      .from(st.querySelectorAll(".bars-l span"), { opacity: 0, stagger: .1, duration: .3 }, t + .9);
  }

  // ---------- drawing ----------
  function buildCharts() {
    // StratForge: random-walk candles, an equity curve, and a Monte Carlo fan of possible futures
    var g = document.querySelector("#s3 .candles"), fan = document.querySelector("#s3 .fan"), eq = document.querySelector("#s3 .equity");
    if (!g) return;
    var p = 150, html = "", N = 38, step = 12.2, x0 = 8;
    for (var i = 0; i < N; i++) {
      var o = p, c = p + (rnd() - .48) * 18, hi = Math.min(o, c) - rnd() * 8, lo = Math.max(o, c) + rnd() * 8, x = x0 + i * step;
      var col = c < o ? "#57d68d" : "#ff6b6b";
      html += '<g><line x1="' + (x + 3) + '" x2="' + (x + 3) + '" y1="' + hi.toFixed(1) + '" y2="' + lo.toFixed(1) + '" stroke="' + col + '"/>' +
              '<rect x="' + x.toFixed(1) + '" y="' + Math.min(o, c).toFixed(1) + '" width="6" height="' + Math.max(2, Math.abs(c - o)).toFixed(1) + '" fill="' + col + '"/></g>';
      p = Math.max(40, Math.min(250, c));
    }
    g.innerHTML = html;
    var y = 250, d = "M" + x0 + " " + y;
    for (i = 1; i <= N; i++) { y -= (rnd() - .35) * 6; d += " L" + (x0 + i * step).toFixed(1) + " " + y.toFixed(1); }
    eq.setAttribute("d", d);
    var xs = x0 + N * step, f = "";
    for (var k = 0; k < 14; k++) {
      var yy = y, pd = "M" + xs.toFixed(1) + " " + y.toFixed(1);
      for (var j = 1; j <= 10; j++) { yy += (rnd() - .55) * 9; pd += " L" + (xs + j * 12).toFixed(1) + " " + yy.toFixed(1); }
      f += '<path d="' + pd + '" stroke="#57d68d" stroke-opacity=".25" fill="none"/>';
    }
    fan.innerHTML = f;

    // Kronos: the real price and the model's up/down calls, roughly half right
    var a = document.querySelector("#s4 .actual"), calls = document.querySelector("#s4 .calls");
    var py = 150, pd2 = "M0 150", pts = [];
    for (i = 1; i <= 60; i++) { py = Math.max(30, Math.min(270, py + (rnd() - .5) * 22)); pts.push(py); pd2 += " L" + (i * 10) + " " + py.toFixed(1); }
    a.setAttribute("d", pd2);
    var c2 = "";
    for (i = 2; i < 58; i += 3) c2 += '<circle cx="' + (i * 10) + '" cy="' + (pts[i - 1] - 14).toFixed(1) + '" r="4.5" fill="' + (rnd() < .5 ? "#57d68d" : "#ff6b6b") + '"/>';
    calls.innerHTML = c2;
  }
  function buildDots() {
    var box = document.querySelector("#s5 .dots");
    if (!box) return;
    var html = "";
    for (var i = 0; i < 220; i++) { var r = rnd(); html += '<i data-c="' + (r < .5 ? "#57d68d" : r < .8 ? "#b28cff" : "#3a3f47") + '"></i>'; }
    box.innerHTML = html;
  }

  // Every scene shown finished (no animation)
  function finalStates() {
    document.querySelectorAll("#s5 .dots i").forEach(function (el) { el.style.background = el.dataset.c; });
    document.querySelectorAll("[data-count]").forEach(function (el) { el.textContent = (+el.dataset.count).toLocaleString("en-US"); });
    document.querySelectorAll(".ledger tr[data-why]").forEach(function (r) { var w = r.querySelector(".why"); w.textContent = "⚑ " + r.dataset.why; w.style.opacity = 1; r.classList.add("flag"); });
    document.querySelectorAll(".f1 .bar, .bars div").forEach(function (b) { b.style.transform = "none"; });
    document.querySelectorAll(".term .l, .checks div, .cite, .approve .post").forEach(function (e) { e.style.opacity = 1; });
    document.querySelectorAll(".approve .pre").forEach(function (e) { e.style.opacity = 0; });
    document.querySelectorAll(".approve .fill").forEach(function (e) { e.style.transform = "none"; });
    document.querySelectorAll(".stamp").forEach(function (e) { e.style.opacity = 1; e.style.transform = "translate(-50%,-50%) rotate(-8deg)"; });
    document.querySelectorAll(".letterbox").forEach(function (e) { e.style.display = "none"; });
  }
})();
