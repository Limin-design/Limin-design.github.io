// Store pricing app, public demo. Everything runs in the visitor's browser:
//   ZXing reads the fiscal QR code, PaddleOCR (the store's OCR models) reads the text, and the store app's
//   own invoice reader (py/loja) runs in Pyodide to tie codes to amounts and prove the invoice against the QR.
//   The Exemplos tab runs the public invoicepricing package on a synthetic store.
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
    py.FS.writeFile(`/home/pyodide/py/invoicepricing/${m}.py`, await (await fetch(`py/invoicepricing/${m}.py?v=8`)).text());
  }
  py.FS.writeFile("/home/pyodide/py/demo_glue.py", await (await fetch("py/demo_glue.py?v=8")).text());
  py.FS.mkdirTree("/home/pyodide/py/loja");
  for (const m of ["linhas_factura", "qr_factura", "loja_config"]) {
    py.FS.writeFile(`/home/pyodide/py/loja/${m}.py`, await (await fetch(`py/loja/${m}.py?v=8`)).text());
  }
  py.FS.writeFile("/home/pyodide/py/loja_glue.py", await (await fetch("py/loja_glue.py?v=8")).text());
  py.runPython("import sys; sys.path.insert(0, '/home/pyodide/py'); import demo_glue, loja_glue; demo_glue.reset()");
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
// Only the fiscal QR counts: some suppliers print an advertising QR in the header too.
const looksFiscal = (t) => typeof t === "string" && /^A:\d{9}\*/.test(t.trim()) && t.includes("*O:");

// Greyscale with automatic contrast (2% of the darkest and lightest pixels clipped). On a real
// photo with soft shadows the QR modules come out grey, and the raw image does not read.
function autocontrast(src) {
  const c = crop(src, 0, 0, src.width, src.height, 1);
  const g = c.getContext("2d");
  const img = g.getImageData(0, 0, c.width, c.height);
  const d = img.data;
  const hist = new Uint32Array(256);
  for (let i = 0; i < d.length; i += 4) hist[(0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) | 0]++;
  const n = d.length / 4, cut = n * 0.02;
  let lo = 0, hi = 255, acc = 0;
  while (lo < 255 && (acc += hist[lo]) < cut) lo++;
  acc = 0;
  while (hi > 0 && (acc += hist[hi]) < cut) hi--;
  const span = Math.max(1, hi - lo);
  for (let i = 0; i < d.length; i += 4) {
    const v = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    d[i] = d[i + 1] = d[i + 2] = Math.max(0, Math.min(255, ((v - lo) * 255) / span));
  }
  g.putImageData(img, 0, 0);
  return c;
}

async function zxingRead(canvas) {
  if (!window.ZXingWASM) return null;
  const img = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
  const found = await ZXingWASM.readBarcodes(img, { formats: ["QRCode"], tryHarder: true, maxNumberOfSymbols: 4 });
  return found.map((f) => f.text).find(looksFiscal) || null;
}

async function findQR(canvas) {
  // As in the store app: the photo as it is, then greyscale with automatic contrast, then half size.
  const versions = [() => canvas, () => autocontrast(canvas), () => crop(canvas, 0, 0, canvas.width, canvas.height, 0.5)];
  for (const make of versions) {
    try {
      const hit = await zxingRead(make());
      if (hit) return hit;
    } catch { /* try the next version, then jsQR */ }
  }
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

// ---------- OCR: the store's models (PaddleOCR PP-OCRv4), running in the browser ----------
const MODELS = "https://cdn.jsdelivr.net/npm/@gutenye/ocr-models@1.4.2/assets/";
let paddle = null;
async function getPaddle() {
  if (!paddle) {
    const { Ocr, ort } = await import("./vendor/paddle-ocr.js");
    ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.20.1/dist/";
    paddle = await Ocr.create({
      models: {
        detectionPath: MODELS + "ch_PP-OCRv4_det_infer.onnx",
        recognitionPath: MODELS + "ch_PP-OCRv4_rec_infer.onnx",
        dictionaryPath: MODELS + "ppocr_keys_v1.txt",
      },
    });
  }
  return paddle;
}

// The store reader takes RapidOCR boxes: [x_min, x_max, y_centre, height, text, confidence, slope].
// The slope of the box's top edge is what lets it straighten a tilted sheet.
function toBoxes(texts) {
  return texts.map((t) => {
    const xs = t.box.map((p) => p[0]), ys = t.box.map((p) => p[1]);
    const dx = t.box[1][0] - t.box[0][0];
    return [Math.min(...xs), Math.max(...xs), ys.reduce((a, b) => a + b, 0) / 4, Math.max(...ys) - Math.min(...ys),
      t.text.normalize("NFKC").trim(), t.mean, dx ? (t.box[1][1] - t.box[0][1]) / dx : 0];
  });
}

// ---------- reading a real invoice ----------
let lastRead = null;
function stage(text) { $("etapa").textContent = text; }

function callLoja(qrText, pages) {
  py.globals.set("_pg", JSON.stringify(pages));
  py.globals.set("_qr", qrText || "");
  py.globals.set("_mg", margin);
  return JSON.parse(py.runPython("loja_glue.le(_pg, _qr, _mg)"));
}

$("botao-ler").onclick = async () => {
  if (!photos.length) return;
  realScreen = "ecra-trabalho";
  show("ecra-trabalho");
  const t0 = Date.now();
  const tick = setInterval(() => ($("relogio").textContent = `${Math.round((Date.now() - t0) / 1000)} s`), 500);
  try {
    stage("a preparar o leitor da loja (da primeira vez descarrega cerca de 45 MB)…");
    await pyReady;
    const ocr = await getPaddle();
    let qrText = null;
    const pages = [];
    for (let i = 0; i < photos.length; i++) {
      const page = `página ${i + 1} de ${photos.length}`;
      if (!qrText) {
        stage(`a procurar o código QR (${page})…`);
        // The fiscal QR is dense: look for it in a sharper copy than the one used for the text.
        qrText = await findQR(await toCanvas(photos[i].file, 3600));
      }
      stage(`a ler o texto (${page})…`);
      const canvas = await toCanvas(photos[i].file, 2400);
      const img = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
      const res = await ocr.detect({ data: img.data, width: img.width, height: img.height });
      pages.push(toBoxes(res.texts));
    }
    stage("a ligar códigos e contas e a provar contra o QR…");
    lastRead = { qrText, pages };
    renderReal(callLoja(qrText, pages));
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
const TAXA_NOME = { reduzida: "6%", intermedia: "13%", normal: "23%" };

function renderReal(r) {
  const q = r.qr;
  // Invoice card
  if (q) {
    const taxas = Object.keys(q.por_taxa || {}).map((k) => TAXA_NOME[k] || k).join(" · ");
    const data = q.data && q.data.length === 10 ? q.data.split("-").reverse().join("/") : q.data;
    const titulo = (q.numero || "").toUpperCase().startsWith((q.tipo || "").toUpperCase()) ? q.numero : `${q.tipo || ""} ${q.numero || ""}`;
    $("cartao-factura").innerHTML = `<h2>Factura ${esc(titulo)}</h2>
      <p class="suave" style="margin:0">Fornecedor NIF ${esc(q.nif_fornecedor)} · ${esc(data)}</p>
      <div class="grelha" style="margin-top:12px">
        <div class="caixinha"><b class="numero">${euro(q.total)}</b><span>total da factura</span></div>
        <div class="caixinha"><b class="numero">${euro(q.total_impostos)}</b><span>impostos</span></div>
        <div class="caixinha"><b>${taxas || "—"}</b><span>taxas de IVA</span></div>
      </div>
      ${q.nao_sujeito ? `<p class="suave" style="margin:10px 0 0">Não sujeito a IVA (ex.: tabaco): ${euro(q.nao_sujeito)}.</p>` : ""}
      ${r.problemas_qr.map((p) => `<div class="aviso-caixa">${esc(p)}</div>`).join("")}`;
  } else {
    $("cartao-factura").innerHTML = `<h2>Código QR</h2><div class="erro">Não encontrei o código QR fiscal nas fotos.</div>
      <p class="suave" style="margin:0">Sem o QR não há com que provar a factura. Fotografa a página onde está o QR,
        de perto, direita e sem sombra. As linhas lidas ficam na mesma em baixo.</p>`;
  }

  // Proof card
  if (q && r.prova.length) {
    const linhasProva = r.prova.map((x) => `<div class="prova"><span class="selo ${x.bate ? "ok" : "falha"}">${x.bate ? "✓" : "!"}</span>
      <div><b>${x.taxa ? `IVA ${num(x.taxa, 0)}%` : "Isento"}</b> · o QR diz <span class="numero">${euro(x.qr)}</span>, as linhas somam
        <span class="numero">${euro(x.lido)}</span>${x.bate ? "" : ` <span class="t-falha">(faltam ${euro(Math.round((x.qr - x.lido) * 100) / 100)})</span>`}</div></div>`).join("");
    $("cartao-provas").innerHTML = `<h2>Prova contra o QR</h2>${linhasProva}
      ${r.provada
        ? `<div class="ok-caixa">✓ Factura provada: as linhas somam o que o QR declara, taxa a taxa. Na loja, só assim os preços vêm pré-aprovados.</div>`
        : `<div class="aviso-caixa">Ainda não provada. Pode faltar uma página, uma linha mal lida ou uma página duvidosa.
            Na loja, uma factura assim nunca tem preços pré-aprovados: uma pessoa vê tudo.</div>`}`;
    $("cartao-provas").hidden = false;
  } else {
    $("cartao-provas").hidden = true;
  }

  // Summary per page
  const linhas = r.paginas.flatMap((p) => p.linhas);
  const semConta = r.paginas.flatMap((p) => p.sem_conta);
  const semCodigo = r.paginas.flatMap((p) => p.sem_codigo);
  const resumoPaginas = r.paginas.map((p, i) => {
    const tr = p.transporte_fim != null
      ? ` · transporte ${euro(p.transporte_inicio || 0)} → ${euro(p.transporte_fim)}` : "";
    return `<div class="prova"><span class="selo ${p.duvidosa ? "aviso" : "ok"}">${p.duvidosa ? "?" : "✓"}</span>
      <div><b>Página ${i + 1}</b> · ${p.linhas.length} linha(s), ligadas por ${esc(p.modo)}${tr}
      ${p.duvidosa ? `<div class="suave">Duvidosa: ${p.sem_conta.length} código(s) sem conta, ${p.sem_codigo.length} conta(s) sem código.</div>` : ""}</div></div>`;
  }).join("");
  $("cartao-resumo").innerHTML = `<h2>Leitura</h2>${resumoPaginas}
    <div class="grelha" style="margin-top:10px">
      <div class="caixinha"><b>${linhas.length}</b><span>artigos lidos</span></div>
      <div class="caixinha"><b>${semConta.length + semCodigo.length}</b><span>por confirmar</span></div>
      <div class="caixinha"><b class="numero">${euro(linhas.reduce((a, l) => a + l.valor, 0))}</b><span>soma das linhas</span></div>
    </div>
    <p class="suave" style="margin:10px 0 0">O leitor da loja liga cada código de artigo à conta da sua linha
      (quantidade × preço = valor). Uma linha que não fecha a conta não passa.</p>`;

  // Lines
  const items = linhas.map((l) => `<div class="artigo">
      <div class="desc">${esc(l.descricao || "(sem descrição)")}</div>
      <div class="conta numero">${l.codigo ? esc(l.codigo) + " · " : ""}${num(l.quantidade, 3)} × ${cost(l.preco)}
        = ${euro(l.valor)} · IVA ${l.iva != null ? num(l.iva, 0) + "%" : "?"}</div>
      <div style="margin-top:6px">${l.pvp != null
        ? `<span class="etiqueta e-subir numero">PVP ${euro(l.pvp)}</span>`
        : `<span class="etiqueta e-nao">sem IVA, sem preço</span>`}
        ${l.prova_iva ? '<span class="etiqueta e-neutro">c/IVA confere</span>' : ""}</div>
    </div>`).join("");
  const porConfirmar = [
    ...semConta.map((k) => `${k.codigo} ${k.descricao || ""} — código sem conta lida`),
    ...semCodigo.map((c) => `${num(c.quantidade, 3)} × ${cost(c.preco)} = ${euro(c.valor)} — conta sem código`),
  ];
  $("cartao-linhas").innerHTML = `<h2>Artigos e preços</h2>
    <div class="margem"><label for="margem">Margem sobre o custo</label>
      <input class="campo-in numero" id="margem" inputmode="decimal" value="${margin}"> %</div>
    <p class="suave" style="margin:8px 0 4px">Na loja, cada artigo é ligado ao produto do back-office e o preço segue a
      margem desse produto. Aqui os artigos não existem numa loja, por isso a margem é igual para todos.</p>
    ${items || '<div class="aviso-caixa">Nenhum artigo lido. Tenta uma foto mais direita, mais perto e sem sombra.</div>'}
    ${porConfirmar.length ? `<div class="aviso-caixa"><b>Por confirmar</b> — o leitor não adivinha; na loja, uma pessoa vê estas linhas.
      <pre class="saida" style="margin-top:6px">${esc(porConfirmar.join("\n"))}</pre></div>` : ""}`;
  $("margem").addEventListener("change", (e) => {
    const v = parseFloat(String(e.target.value).replace(",", "."));
    if (!Number.isFinite(v) || v < 0 || v > 500) return;
    margin = v;
    renderReal(callLoja(lastRead.qrText, lastRead.pages));
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
