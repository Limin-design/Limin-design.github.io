// Runs the invoicepricing package (copied unchanged from the public repo) in Pyodide.
const MODULES = ["__init__", "__main__", "apply", "cli", "db", "demo_data", "lines", "pricing", "proof", "qr", "report"];
const statusEl = document.getElementById("status");
const out = document.getElementById("out");
const inv = document.getElementById("inv");
let py = null;
let current = "samples/invoice_01_clean.txt";

const GLUE = `
import contextlib, io, os, re, sys, traceback
sys.path.insert(0, "/home/pyodide/py")
os.makedirs("/home/pyodide/work", exist_ok=True)
os.chdir("/home/pyodide/work")
from invoicepricing import cli, demo_data

last_log = None

def reset():
    demo_data.build(cli.DB, "samples")

def run(cmd, text):
    global last_log
    with open("current.txt", "w", encoding="utf-8") as f:
        f.write(text.rstrip("\\n") + "\\n")
    if cmd == "write":
        argv = ["price", "current.txt", "--write"]
    elif cmd == "undo":
        if not last_log:
            return "Nothing to undo yet: write a plan first."
        argv = ["undo", last_log]
    elif cmd == "report":
        os.makedirs("powerbi/data", exist_ok=True)
        argv = ["report"]
    else:
        argv = [cmd, "current.txt"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            cli.main(argv)
        except SystemExit:
            pass
        except Exception as e:
            print("Refused: " + (str(e) or type(e).__name__))
    text_out = buf.getvalue()
    m = re.search(r"Undo log: (\\S+)", text_out)
    if m and m.group(1) != "None":
        last_log = m.group(1)
    elif m:
        text_out += "\\nNothing was approved, so nothing was written."
    if cmd == "undo" and "Undone" in text_out:
        last_log = None
    return text_out
`;

function setReady(on) {
  document.querySelectorAll("button[disabled], button[data-cmd], #picker button").forEach(b => (b.disabled = !on));
}

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function colour(text) {
  return text.split("\n").map(line => {
    const e = esc(line);
    if (/^PROVEN|: ok$| ok$|^Written|^Undone/.test(line)) return `<span class="ok">${e}</span>`;
    if (/NOT PROVEN|GAP|did not close|^Refused|nothing is pre-approved/i.test(line)) return `<span class="bad">${e}</span>`;
    if (/needs_decision|refused|unlinked|\?$| \? /.test(line)) return `<span class="warn">${e}</span>`;
    return e;
  }).join("\n");
}

function show(label, text) {
  out.innerHTML = `<span class="cmd">$ python -m invoicepricing ${esc(label)}</span>\n` + colour(text);
}

function loadSample(path) {
  current = path;
  inv.value = py.FS.readFile("/home/pyodide/work/" + path, { encoding: "utf8" });
  document.querySelectorAll("#picker button").forEach(b => b.classList.toggle("on", b.dataset.f === path));
}

async function main() {
  try {
    py = await loadPyodide();
    statusEl.textContent = "Loading the database module…";
    await py.loadPackage("sqlite3");
    py.FS.mkdirTree("/home/pyodide/py/invoicepricing");
    for (const m of MODULES) {
      const src = await (await fetch(`py/invoicepricing/${m}.py`)).text();
      py.FS.writeFile(`/home/pyodide/py/invoicepricing/${m}.py`, src);
    }
    statusEl.textContent = "Building the synthetic store…";
    await py.runPythonAsync(GLUE + "\nreset()\n");
    loadSample(current);
    setReady(true);
    statusEl.textContent = "Ready. Python is running in this tab.";
    runCmd("read");
  } catch (err) {
    statusEl.textContent = "Could not start Python in this browser: " + err;
  }
}

function runCmd(cmd) {
  if (cmd === "reset") {
    py.runPython("reset()");
    loadSample(current);
    show("build", "Store rebuilt: demo.sqlite and samples/ created again.");
    return;
  }
  py.globals.set("_text", inv.value);
  py.globals.set("_cmd", cmd);
  const text = py.runPython("run(_cmd, _text)");
  const label = { write: "price invoice.txt --write", undo: "undo <last log>", report: "report" }[cmd] || `${cmd} invoice.txt`;
  show(label, text);
}

document.getElementById("picker").addEventListener("click", e => {
  const b = e.target.closest("button[data-f]");
  if (!b || !py) return;
  loadSample(b.dataset.f);
  runCmd("read");
});
document.querySelectorAll("button[data-cmd]").forEach(b => b.addEventListener("click", () => runCmd(b.dataset.cmd)));

main();
