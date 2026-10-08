// Store pricing app, public demo. Everything runs in the visitor's browser:
//   jsQR reads the fiscal QR code, Tesseract.js reads the text, and the invoicepricing
//   Python package (unchanged from the public repo) runs in Pyodide to parse and prove it.
const MODULES = ["__init__", "__main__", "apply", "cli", "db", "demo_data", "lines", "pricing", "proof", "qr", "report"];
const $ = (id) => document.getElementById(id);
const euro = (v) => (v == null ? "—" : v.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €");
const num = (v, d = 4) => Number(v).toLocaleString("pt-PT", { maximumFractionDigits: d });
const cost = (v) => Number(v).toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 4 }) + " €";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// ---------- Python (Pyodide) ----------
let py = null;
const pyReady = (async () => {
  py = await loadPyodide();
  await py.loadPackage("sqlite3");
  py.FS.mkdirTree("/home/pyodide/py/invoicepricing");
  for (const m of MODULES) {
    py.FS.writeFile(`/home/pyodide/py/invoicepricing/${m}.py`, await (await fetch(`py/invoicepricing/${m}.py?v=5`)).text());
  }
  py.FS.writeFile("/home/pyodide/py/demo_glue.py", await (await fetch("py/demo_glue.py?v=5")).text());
  py.runPython("import sys; sys.path.insert(0, '/home/pyodide/py'); import demo_glue; demo_glue.reset()");
  return py;
})();

function callPy(fn, ...args) {
  args.forEach((a, i) => py.globals.set(`_a${i}`, a));
  return py.runPython(`demo_glue.${fn}(${args.map((_, i) => `_a${i}`).join(", ")})`);
}

// ---------- tabs ----------
const screens = ["ecra-factura", "ecra-trabalho", "ecra-resultado", "ecra-exemplos"];
function show(id) {
  screens.forEach((s) => ($(s).hidden = s !== id));
  window.scrollTo({ top: 0 });
}
let realScreen = "ecra-factura";
$("sep-factura").onclick = () => { $("sep-factura").classList.add("activo"); $("sep-exemplos").classList.remove("activo"); show(realScreen); };
$("sep-exemplos").onclick = () => {
  $("sep-exemplos").classList.add("activo"); $("sep-factura").classList.remove("activo"); show("ecra-exemplos");
  startExamples();
};

// ---------- photos ----------
const photos = [];
function renderMinis() {
  $("miniaturas").innerHTML = photos.map((p, i) =>
    `<div class="mini"><img src="${p.url}" alt="página ${i + 1}"><span class="pagina">${i + 1}</span>` +
    `<button class="tira" data-i="${i}" aria-label="tirar página ${i + 1}">×</button></div>`).join("");
  $("botao-ler").disabled = photos.length === 0;
}
$("miniaturas").addEventListener("click", (e) => {
  const b = e.target.closest("button.tira");
  if (!b) return;
  URL.revokeObjectURL(photos[b.dataset.i].url);
  photos.splice(Number(b.dataset.i), 1);
  renderMinis();
});
for (const id of ["camara", "galeria"]) {
  $(id).addEventListener("change", (e) => {
    for (const f of e.target.files) photos.push({ file: f, url: URL.createObjectURL(f) });
    e.target.value = "";
    $("erro-envio").hidden = true;
    renderMinis();
  });
}

async function toCanvas(file, maxSide) {
  const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
  const s = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * s);
  c.height = Math.round(bmp.height * s);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  bmp.close?.();
  return c;
}

function crop(src, x, y, w, h, scale = 1) {
  const c = document.createElement("canvas");
  c.width = Math.round(w * scale);
  c.height = Math.round(h * scale);
  const g = c.getContext("2d");
  g.imageSmoothingEnabled = scale < 1;
  g.drawImage(src, x, y, w, h, 0, 0, c.width, c.height);
  return c;
}

// ---------- fiscal QR ----------
const looksFiscal = (t) => typeof t === "string" && /(^|\*)A:\d{9}\*/.test(t) && t.includes("*O:");
async function findQR(canvas) {
  if ("BarcodeDetector" in window) {
    try {
      const found = await new BarcodeDetector({ formats: ["qr_code"] }).detect(canvas);
      const hit = found.map((f) => f.rawValue).find(looksFiscal);
      if (hit) return hit;
    } catch { /* fall back to jsQR */ }
  }
  const W = canvas.width, H = canvas.height;
  // Whole page first, then the regions where the fiscal QR usually sits, enlarged.
  const tries = [
    [0, 0, W, H, Math.min(1, 1400 / Math.max(W, H))],
    [0, H / 2, W, H / 2, 1], [W / 2, H / 2, W / 2, H / 2, 1.6], [0, H / 2, W / 2, H / 2, 1.6],
    [W / 2, 0, W / 2, H / 2, 1.6], [0, 0, W / 2, H / 2, 1.6], [0, 0, W, H, 1],
  ];
  for (const [x, y, w, h, s] of tries) {
    const c = crop(canvas, x, y, w, h, s);
    const img = c.getContext("2d").getImageData(0, 0, c.width, c.height);
    const r = jsQR(img.data, img.width, img.height, { inversionAttempts: "attemptBoth" });
    if (r && looksFiscal(r.data)) return r.data;
    await new Promise((res) => setTimeout(res, 0)); // keep the page responsive
  }
  return null;
}

// ---------- OCR ----------
let worker = null;
let ocrProgress = () => {};
async function getWorker() {
  if (!worker) {
    worker = await Tesseract.createWorker("por", 1, {
      logger: (m) => m.status === "recognizing text" && ocrProgress(m.progress),
    });
    await worker.setParameters({ preserve_interword_spaces: "1" });
  }
  return worker;
}
function forOcr(canvas) {
  // Greyscale with a little contrast: the paper gets lighter, the print darker.
  const c = crop(canvas, 0, 0, canvas.width, canvas.height, 1);
  const g = c.getContext("2d");
  const img = g.getImageData(0, 0, c.width, c.height);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const v = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    const k = Math.max(0, Math.min(255, (v - 128) * 1.35 + 140));
    d[i] = d[i + 1] = d[i + 2] = k;
  }
  g.putImageData(img, 0, 0);
  return c;
}

// ---------- reading a real invoice ----------
let lastRead = null;
function stage(text) { $("etapa").textContent = text; }

$("botao-ler").onclick = async () => {
  if (!photos.length) return;
  realScreen = "ecra-trabalho";
  show("ecra-trabalho");
  const t0 = Date.now();
  const tick = setInterval(() => ($("relogio").textContent = `${Math.round((Date.now() - t0) / 1000)} s`), 500);
  try {
    stage("a preparar o leitor (só da primeira vez demora mais)…");
    await pyReady;
    let qrText = null;
    const rows = [];
    for (let i = 0; i < photos.length; i++) {
      const page = `página ${i + 1} de ${photos.length}`;
      const canvas = await toCanvas(photos[i].file, 2400);
      if (!qrText) {
        stage(`a procurar o código QR (${page})…`);
        qrText = await findQR(canvas);
      }
      stage(`a ler o texto (${page})…`);
      ocrProgress = (p) => stage(`a ler o texto (${page}): ${Math.round(p * 100)}%`);
      const { data } = await (await getWorker()).recognize(forOcr(canvas));
      rows.push(...data.text.split("\n").map((r) => r.replace(/\s+/g, " ").trim()).filter(Boolean));
    }
    stage("a provar a factura contra o QR…");
    lastRead = { qrText, rows };
    renderReal(JSON.parse(callPy("read_real", qrText || "", JSON.stringify(rows), currentMargin())), rows);
    realScreen = "ecra-resultado";
    show("ecra-resultado");
  } catch (err) {
    realScreen = "ecra-factura";
    show("ecra-factura");
    $("erro-envio").textContent = "Não foi possível ler: " + (err?.message || err);
    $("erro-envio").hidden = false;
  } finally {
    clearInterval(tick);
  }
};

$("botao-outra").onclick = () => {
  photos.splice(0).forEach((p) => URL.revokeObjectURL(p.url));
  renderMinis();
  realScreen = "ecra-factura";
  show("ecra-factura");
};

let margin = 30;
const currentMargin = () => margin;

function renderReal(r, rows) {
  // Invoice card
  if (r.qr) {
    const q = r.qr;
    const title = q.number.toUpperCase().startsWith(q.doc_type.toUpperCase()) ? q.number : `${q.doc_type} ${q.number}`;
    $("cartao-factura").innerHTML = `<h2>Factura ${esc(title)}</h2>
      <p class="suave" style="margin:0">Fornecedor NIF ${esc(q.supplier_nif)} · ${esc(q.date)}</p>
      <div class="grelha" style="margin-top:12px">
        <div class="caixinha"><b class="numero">${euro(q.total)}</b><span>total da factura</span></div>
        <div class="caixinha"><b class="numero">${euro(q.total_vat)}</b><span>IVA</span></div>
        <div class="caixinha"><b>${Object.keys(q.bases).map((k) => k + "%").join(" · ") || "—"}</b><span>taxas de IVA</span></div>
      </div>`;
  } else {
    $("cartao-factura").innerHTML = `<h2>Código QR</h2><div class="erro">${
      r.qr_error ? "O código QR foi lido mas não bate certo consigo próprio: " + esc(r.qr_error)
                 : "Não encontrei o código QR fiscal nas fotos."}</div>
      <p class="suave" style="margin:0">Sem o QR não há com que provar a factura. Fotografa a página onde está o QR,
        de perto, direita e sem reflexo. As linhas lidas ficam na mesma em baixo.</p>`;
  }

  // Proof card
  const pf = r.proof;
  if (pf) {
    const ratesHtml = pf.rates.map((x) => `<div class="prova"><span class="selo ${x.ok ? "ok" : "falha"}">${x.ok ? "✓" : "!"}</span>
      <div><b>IVA ${x.rate}%</b> · o QR diz <span class="numero">${euro(x.declared)}</span>, as linhas somam
        <span class="numero">${euro(x.read)}</span>${x.ok ? "" : ` <span class="t-falha">(faltam ${euro(x.gap)})</span>`}
        <div class="suave">${x.lines} linha(s)</div></div></div>`).join("");
    $("cartao-provas").innerHTML = `<h2>Prova contra o QR</h2>${ratesHtml}
      ${pf.proven
        ? `<div class="ok-caixa">✓ Factura provada: as linhas somam o que o QR declara, taxa a taxa. Na loja, só assim os preços vêm pré-aprovados.</div>`
        : `<div class="aviso-caixa">Ainda não provada. Pode faltar uma página, uma linha mal lida ou uma linha sem IVA.
            Na loja, uma factura assim nunca tem preços pré-aprovados: uma pessoa vê tudo.</div>`}`;
    $("cartao-provas").hidden = false;
  } else {
    $("cartao-provas").hidden = true;
  }

  // Summary
  $("cartao-resumo").innerHTML = `<h2>Resumo</h2><div class="grelha">
      <div class="caixinha"><b>${r.lines.length}</b><span>linhas com a conta certa</span></div>
      <div class="caixinha"><b>${r.rows_not_closed}</b><span>linhas de texto que não fecham</span></div>
      <div class="caixinha"><b class="numero">${euro(r.sum_read)}</b><span>soma das linhas lidas</span></div>
    </div>
    <p class="suave" style="margin:10px 0 0">Uma linha só conta quando quantidade × preço = valor, ao cêntimo.
      As outras (cabeçalhos, moradas, totais) ficam de fora.</p>`;

  // Lines
  const items = r.lines.map((l) => `<div class="artigo">
      <div class="desc">${esc(l.desc || "(sem descrição)")} ${l.doubtful ? '<span class="etiqueta e-neutro">dúvida</span>' : ""}</div>
      <div class="conta numero">${l.code ? esc(l.code) + " · " : ""}${num(l.qty, 3)} × ${cost(l.unit_cost)}${l.discount ? ` (−${num(l.discount, 2)}%)` : ""}
        = ${euro(l.value)} · IVA ${l.vat ?? "?"}%</div>
      <div style="margin-top:6px">${l.price != null
        ? `<span class="etiqueta e-subir numero">PVP ${euro(l.price)}</span>`
        : `<span class="etiqueta e-nao">sem IVA, sem preço</span>`}</div>
      ${l.notes.length ? `<div class="porque">${l.notes.map(esc).join(" · ")}</div>` : ""}
    </div>`).join("");
  $("cartao-linhas").innerHTML = `<h2>Artigos e preços</h2>
    <div class="margem"><label for="margem">Margem sobre o custo</label>
      <input class="campo-in numero" id="margem" inputmode="decimal" value="${margin}"> %</div>
    <p class="suave" style="margin:8px 0 4px">Na loja, cada artigo é ligado ao produto do back-office e o preço segue a
      margem desse produto. Aqui os artigos não existem numa loja, por isso a margem é igual para todos.</p>
    ${items || '<div class="aviso-caixa">Nenhuma linha fechou a conta. Tenta uma foto mais direita e mais perto.</div>'}
    ${r.suspect_rows.length ? `<div class="aviso-caixa"><b>Linhas que não fecharam a conta</b> — provavelmente um número mal lido.
      O programa não adivinha: na loja, uma pessoa confirma estas linhas.
      <pre class="saida" style="margin-top:6px">${esc(r.suspect_rows.join("\n"))}</pre></div>` : ""}
    <details><summary>Texto lido da foto (${rows.length} linhas)</summary><pre class="saida">${esc(rows.join("\n"))}</pre></details>`;
  $("margem").addEventListener("change", (e) => {
    const v = parseFloat(String(e.target.value).replace(",", "."));
    if (!Number.isFinite(v) || v < 0 || v > 500) return;
    margin = v;
    renderReal(JSON.parse(callPy("read_real", lastRead.qrText || "", JSON.stringify(lastRead.rows), margin)), lastRead.rows);
  });
}

// ---------- examples: the synthetic store, full flow ----------
let examplesStarted = false;
let current = "samples/invoice_01_clean.txt";
function colour(text) {
  return text.split("\n").map((line) => {
    const e = esc(line);
    if (/^PROVEN|: ok$| ok$|^Written|^Undone/.test(line)) return `<span class="t-ok">${e}</span>`;
    if (/NOT PROVEN|GAP|did not close|^Refused|nothing is pre-approved/i.test(line)) return `<span class="t-falha">${e}</span>`;
    if (/needs_decision|refused|unlinked/.test(line)) return `<span class="t-aviso">${e}</span>`;
    return e;
  }).join("\n");
}
function loadSample(path) {
  current = path;
  $("exemplo-texto").value = py.FS.readFile("/home/pyodide/work/" + path, { encoding: "utf8" });
  document.querySelectorAll("#exemplos button").forEach((b) => b.classList.toggle("activo", b.dataset.f === path));
}
function runExample(cmd) {
  if (cmd === "reset") {
    py.runPython("demo_glue.reset()");
    loadSample(current);
    $("exemplo-saida").textContent = "Loja reposta.";
    return;
  }
  $("exemplo-saida").innerHTML = colour(callPy("run", cmd, $("exemplo-texto").value));
}
async function startExamples() {
  if (examplesStarted) return;
  examplesStarted = true;
  $("exemplo-saida").textContent = "A carregar o Python no browser…";
  await pyReady;
  loadSample(current);
  runExample("read");
}
$("exemplos").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-f]");
  if (!b || !py) return;
  loadSample(b.dataset.f);
  runExample("read");
});
document.querySelectorAll("button[data-cmd]").forEach((b) => b.addEventListener("click", () => py && runExample(b.dataset.cmd)));

// Start loading Python right away so the first reading is quicker.
pyReady.catch((err) => {
  $("erro-envio").textContent = "Este browser não conseguiu carregar o Python: " + err;
  $("erro-envio").hidden = false;
});
