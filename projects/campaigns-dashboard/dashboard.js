// Web replica of the Power BI report "campanhas de energia".
// Same data and the same measures; clicking a channel, product, month or matrix cell filters the other visuals.
(function () {
  "use strict";
  const D = window.PBI_DATA;
  const root = document.getElementById("pbi");
  if (!D || !root) return;

  const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const nf = new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 0, useGrouping: "always" });
  const pf = new Intl.NumberFormat("pt-PT", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pf0 = new Intl.NumberFormat("pt-PT", { style: "percent", maximumFractionDigits: 1 });
  const fmtN = (x) => nf.format(x);
  const fmtP = (x) => (x == null ? "" : pf.format(x));
  const fmtE = (x) => nf.format(Math.round(x)) + " €";
  const monthLabel = (i) => {
    const [y, m] = D.months[i].split("-");
    const n = MESES[+m - 1];
    return n.charAt(0).toUpperCase() + n.slice(1) + " " + y;
  };
  const product = (c) => D.campaigns[c][1];
  const PRODUCTS = [...new Set(D.campaigns.map((c) => c[1]))];

  // row = [month, campaign, channel, region, contacts, conversions, revenue]
  const state = { m: null, ch: null, pr: null, ca: null, rg: null };

  function rows(except) {
    const ex = new Set(except || []);
    return D.rows.filter((r) =>
      (state.m === null || ex.has("m") || r[0] === state.m) &&
      (state.ch === null || ex.has("ch") || r[2] === state.ch) &&
      (state.pr === null || ex.has("pr") || product(r[1]) === state.pr) &&
      (state.ca === null || ex.has("ca") || r[1] === state.ca) &&
      (state.rg === null || ex.has("rg") || r[3] === state.rg));
  }
  function sum(rs) {
    const t = { n: 0, k: 0, v: 0 };
    for (const r of rs) { t.n += r[4]; t.k += r[5]; t.v += r[6]; }
    t.rate = t.n ? t.k / t.n : null;
    return t;
  }
  function group(rs, keyFn) {
    const g = new Map();
    for (const r of rs) {
      const k = keyFn(r);
      if (!g.has(k)) g.set(k, []);
      g.get(k).push(r);
    }
    const out = new Map();
    for (const [k, v] of g) out.set(k, sum(v));
    return out;
  }

  // ---------- layout ----------
  root.innerHTML = `
    <div class="pbi-bar"><span class="pbi-hint">Clique num canal, produto, mês ou célula da matriz para filtrar.</span>
      <button type="button" class="pbi-reset" hidden>Limpar seleção</button></div>
    <div class="pbi-grid">
      <div class="pbi-cards">
        <div class="pbi-box pbi-card"><span>Contactos</span><b data-k="n"></b></div>
        <div class="pbi-box pbi-card"><span>Conversoes</span><b data-k="k"></b></div>
        <div class="pbi-box pbi-card"><span>Taxa de conversao</span><b data-k="rate"></b></div>
        <div class="pbi-box pbi-card"><span>Receita</span><b data-k="v"></b></div>
      </div>
      <div class="pbi-box pbi-matrix"></div>
      <div class="pbi-box pbi-line"><p class="pbi-title">Conversoes</p><p class="pbi-subtitle">por mês</p><svg class="pbi-chart" data-c="line"></svg></div>
      <div class="pbi-box pbi-bars"><p class="pbi-title">Taxa de conversao</p><p class="pbi-subtitle">por canal</p><svg class="pbi-chart" data-c="canal"></svg></div>
      <div class="pbi-box pbi-bars"><p class="pbi-title">Taxa de conversao</p><p class="pbi-subtitle">por produto</p><svg class="pbi-chart" data-c="produto"></svg></div>
    </div>
    <div class="pbi-tip" hidden></div>`;

  const tip = root.querySelector(".pbi-tip");
  const resetBtn = root.querySelector(".pbi-reset");
  const hint = root.querySelector(".pbi-hint");
  resetBtn.addEventListener("click", () => { for (const k in state) state[k] = null; render(); });

  function showTip(evt, title, lines) {
    tip.innerHTML = `<b>${title}</b>` + lines.map(([a, b]) => `<div><span>${a}</span>${b}</div>`).join("");
    tip.hidden = false;
    const box = root.getBoundingClientRect();
    let x = evt.clientX - box.left + 14, y = evt.clientY - box.top + 14;
    if (x + tip.offsetWidth > box.width - 6) x = evt.clientX - box.left - tip.offsetWidth - 14;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  const hideTip = () => { tip.hidden = true; };
  const tipLines = (t) => [["Taxa de conversao", fmtP(t.rate)], ["Contactos", fmtN(t.n)], ["Conversoes", fmtN(t.k)], ["Receita", fmtE(t.v)]];

  const NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, parent, text) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function niceMax(v, ticks) {
    if (v <= 0) return { max: 1, step: 1 / ticks };
    const raw = v / ticks, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((s) => s * mag).find((s) => s >= raw);
    return { max: Math.ceil(v / step) * step, step };
  }

  // ---------- cards ----------
  function renderCards() {
    const t = sum(rows());
    root.querySelector('[data-k="n"]').textContent = fmtN(t.n);
    root.querySelector('[data-k="k"]').textContent = fmtN(t.k);
    root.querySelector('[data-k="rate"]').textContent = t.rate == null ? "—" : fmtP(t.rate);
    root.querySelector('[data-k="v"]').textContent = fmtE(t.v);
  }

  // ---------- matrix ----------
  const MIN_C = [252, 220, 203], MAX_C = [203, 232, 248];
  const mix = (a, b, f) => `rgb(${a.map((x, i) => Math.round(x + (b[i] - x) * f)).join(",")})`;
  function renderMatrix() {
    const box = root.querySelector(".pbi-matrix");
    const rs = rows(["ca", "rg"]);
    const cell = group(rs, (r) => r[1] + "|" + r[3]);
    const byCa = group(rs, (r) => r[1]);
    const byRg = group(rs, (r) => r[3]);
    const tot = sum(rs);
    const camps = D.campaigns.map((c, i) => i).filter((i) => byCa.has(i));
    const regs = D.regions.map((r, i) => i);
    const rates = [...cell.values()].map((t) => t.rate).filter((x) => x != null);
    const lo = Math.min(...rates), hi = Math.max(...rates);
    const sel = (ca, rg) => (state.ca === null && state.rg === null) ? "" :
      ((state.ca === null || state.ca === ca) && (state.rg === null || state.rg === rg)) ? "" : "dim";
    let h = `<table><thead><tr><th>regiao</th>`;
    for (const g of regs) h += `<th colspan="2" class="reg" data-rg="${g}">${D.regions[g]}</th>`;
    h += `<th colspan="2" class="tot">Total</th></tr><tr><th>campanha</th>`;
    for (const g of regs) h += `<th>Taxa de conversao</th><th>Contactos</th>`;
    h += `<th class="tot">Taxa de conversao</th><th class="tot">Contactos</th></tr></thead><tbody>`;
    for (const c of camps) {
      h += `<tr><th class="camp" data-ca="${c}">${D.campaigns[c][0]}</th>`;
      for (const g of regs) {
        const t = cell.get(c + "|" + g);
        const isSel = state.ca === c && state.rg === g ? " sel" : "";
        if (!t) { h += `<td class="${sel(c, g)}"></td><td class="${sel(c, g)}"></td>`; continue; }
        const f = hi > lo ? (t.rate - lo) / (hi - lo) : 0.5;
        h += `<td class="v ${sel(c, g)}${isSel}" data-ca="${c}" data-rg="${g}" style="background:${mix(MIN_C, MAX_C, f)}">${fmtP(t.rate)}</td>`;
        h += `<td class="v ${sel(c, g)}" data-ca="${c}" data-rg="${g}">${fmtN(t.n)}</td>`;
      }
      const t = byCa.get(c);
      h += `<td class="tot">${fmtP(t.rate)}</td><td class="tot">${fmtN(t.n)}</td></tr>`;
    }
    h += `<tr class="total"><th class="camp">Total</th>`;
    for (const g of regs) {
      const t = byRg.get(g) || { rate: null, n: 0 };
      h += `<td>${fmtP(t.rate)}</td><td>${fmtN(t.n)}</td>`;
    }
    h += `<td>${fmtP(tot.rate)}</td><td>${fmtN(tot.n)}</td></tr></tbody></table>`;
    box.innerHTML = h;
    box.querySelectorAll("td.v").forEach((td) => {
      const c = +td.dataset.ca, g = +td.dataset.rg;
      td.addEventListener("click", () => {
        const same = state.ca === c && state.rg === g;
        state.ca = same ? null : c; state.rg = same ? null : g; render();
      });
      td.addEventListener("mousemove", (e) => showTip(e, `${D.campaigns[c][0]} · ${D.regions[g]}`, tipLines(cell.get(c + "|" + g))));
      td.addEventListener("mouseleave", hideTip);
    });
    box.querySelectorAll("th.camp[data-ca]").forEach((th) => th.addEventListener("click", () => {
      const c = +th.dataset.ca; const same = state.ca === c && state.rg === null;
      state.ca = same ? null : c; state.rg = null; render();
    }));
    box.querySelectorAll("th.reg").forEach((th) => th.addEventListener("click", () => {
      const g = +th.dataset.rg; const same = state.rg === g && state.ca === null;
      state.rg = same ? null : g; state.ca = null; render();
    }));
  }

  // ---------- line chart ----------
  function smoothPath(pts) {
    if (pts.length < 2) return "";
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
      const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += ` C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${p2[0]},${p2[1]}`;
    }
    return d;
  }
  function renderLine() {
    const svg = root.querySelector('svg[data-c="line"]');
    svg.innerHTML = "";
    const W = svg.clientWidth || 400, H = svg.clientHeight || 260;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const g = group(rows(["m"]), (r) => r[0]);
    const vals = D.months.map((_, i) => (g.get(i) || { k: 0 }).k);
    const { max, step } = niceMax(Math.max(...vals), 4);
    const L = 34, R = 10, T = 8, B = 24, w = W - L - R, h = H - T - B;
    const x = (i) => L + (D.months.length === 1 ? w / 2 : (i / (D.months.length - 1)) * w);
    const y = (v) => T + h - (v / max) * h;
    for (let v = 0; v <= max + 1e-9; v += step) {
      el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: "#edebe9" }, svg);
      el("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end" }, svg, fmtN(v));
    }
    const every = Math.max(1, Math.ceil(64 / (w / Math.max(1, D.months.length - 1))));
    D.months.forEach((_, i) => {
      if ((D.months.length - 1 - i) % every !== 0) return;
      const anchor = x(i) > W - R - 30 ? "end" : x(i) < L + 30 ? "start" : "middle";
      el("text", { x: x(i), y: H - 6, "text-anchor": anchor }, svg, monthLabel(i));
    });
    const pts = vals.map((v, i) => [x(i), y(v)]);
    el("path", { d: smoothPath(pts), fill: "none", stroke: "#118dff", "stroke-width": 2.2 }, svg);
    if (state.m !== null) {
      el("line", { x1: x(state.m), x2: x(state.m), y1: T, y2: T + h, stroke: "#252423", "stroke-dasharray": "3 3" }, svg);
      el("circle", { cx: pts[state.m][0], cy: pts[state.m][1], r: 4.5, fill: "#118dff", stroke: "#fff", "stroke-width": 2 }, svg);
    }
    const slot = w / Math.max(1, D.months.length - 1);
    D.months.forEach((_, i) => {
      const hit = el("rect", { class: "hit", x: x(i) - slot / 2, y: T, width: slot, height: h }, svg);
      hit.addEventListener("click", () => { state.m = state.m === i ? null : i; render(); });
      hit.addEventListener("mousemove", (e) => showTip(e, monthLabel(i), tipLines(g.get(i) || sum([]))));
      hit.addEventListener("mouseleave", hideTip);
    });
  }

  // ---------- bar charts ----------
  function renderBars(kind) {
    const svg = root.querySelector(`svg[data-c="${kind}"]`);
    svg.innerHTML = "";
    const W = svg.clientWidth || 400, H = svg.clientHeight || 260;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const key = kind === "canal" ? "ch" : "pr";
    const rs = rows([key]);
    const g = kind === "canal" ? group(rs, (r) => r[2]) : group(rs, (r) => product(r[1]));
    const names = kind === "canal" ? D.channels.map((n, i) => [i, n]) : PRODUCTS.map((p) => [p, p]);
    const items = names.filter(([k]) => g.has(k)).map(([k, n]) => ({ k, n, t: g.get(k) }))
      .sort((a, b) => (b.t.rate || 0) - (a.t.rate || 0));
    const { max, step } = niceMax(Math.max(0.0001, ...items.map((i) => i.t.rate || 0)), 4);
    const L = 64, R = 12, T = 6, B = 22, w = W - L - R, h = H - T - B;
    const x = (v) => L + (v / max) * w;
    for (let v = 0; v <= max + 1e-9; v += step) {
      el("line", { x1: x(v), x2: x(v), y1: T, y2: T + h, stroke: "#edebe9" }, svg);
      el("text", { x: x(v), y: H - 6, "text-anchor": "middle" }, svg, pf0.format(v));
    }
    const band = h / Math.max(1, items.length), bh = Math.min(30, band * 0.45);
    items.forEach((it, i) => {
      const cy = T + band * i + band / 2;
      el("text", { class: "cat", x: L - 8, y: cy + 4, "text-anchor": "end" }, svg, it.n);
      const active = state[key] === null || state[key] === it.k;
      const bar = el("rect", { class: "bar", x: L, y: cy - bh / 2, width: Math.max(0, x(it.t.rate || 0) - L), height: bh,
        fill: "#118dff", opacity: active ? 1 : 0.3 }, svg);
      const hit = el("rect", { class: "hit", x: 0, y: cy - band / 2, width: W, height: band }, svg);
      for (const t of [bar, hit]) {
        t.addEventListener("click", () => { state[key] = state[key] === it.k ? null : it.k; render(); });
        t.addEventListener("mousemove", (e) => showTip(e, it.n, tipLines(it.t)));
        t.addEventListener("mouseleave", hideTip);
      }
    });
  }

  function renderHint() {
    const parts = [];
    if (state.m !== null) parts.push(monthLabel(state.m));
    if (state.ch !== null) parts.push(D.channels[state.ch]);
    if (state.pr !== null) parts.push(state.pr);
    if (state.ca !== null) parts.push(D.campaigns[state.ca][0]);
    if (state.rg !== null) parts.push(D.regions[state.rg]);
    resetBtn.hidden = parts.length === 0;
    hint.innerHTML = parts.length ? `A filtrar: <b>${parts.join(" · ")}</b>` : "Clique num canal, produto, mês ou célula da matriz para filtrar.";
  }

  function render() {
    hideTip();
    renderHint();
    renderCards();
    renderMatrix();
    renderLine();
    renderBars("canal");
    renderBars("produto");
  }

  render();
  let raf = 0;
  new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => { renderLine(); renderBars("canal"); renderBars("produto"); }); })
    .observe(root);
})();
