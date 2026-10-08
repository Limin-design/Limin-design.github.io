"""Glue between the web page and the invoicepricing package (copied unchanged from the public repo).

Two entry points:
  run(cmd, text)                     the synthetic store: read, price, write, undo, summary, report
  read_real(qr_text, rows, margin)   a real invoice photographed in the browser: QR + OCR rows -> proof
"""
import contextlib
import io
import json
import os
import re
import sys

sys.path.insert(0, "/home/pyodide/py")
os.makedirs("/home/pyodide/work", exist_ok=True)
os.chdir("/home/pyodide/work")

from invoicepricing import cli, demo_data, lines, proof, qr  # noqa: E402
from invoicepricing.db import shelf_price  # noqa: E402

last_log = None

# Rows that summarise the invoice instead of listing a product (they start with these words).
# Their numbers can close by accident ("1 x 10,00 = 10,00"), so they are never read as lines.
_SUMMARY_ROW = re.compile(r"^\W*(sub-?total|total|base|incid|taxa|iva|imposto|resumo|a transportar|transporte"
                          r"|desconto|pagamento|troco|valor)\b", re.IGNORECASE)


def reset():
    demo_data.build(cli.DB, "samples")


def run(cmd, text):
    global last_log
    with open("current.txt", "w", encoding="utf-8") as f:
        f.write(text.rstrip("\n") + "\n")
    if cmd == "write":
        argv = ["price", "current.txt", "--write"]
    elif cmd == "undo":
        if not last_log:
            return "Nada para desfazer: grava primeiro um plano."
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
        except Exception as e:  # the writer refuses by raising: show why
            print("Refused: " + (str(e) or type(e).__name__))
    out = buf.getvalue()
    m = re.search(r"Undo log: (\S+)", out)
    if m and m.group(1) != "None":
        last_log = m.group(1)
    elif m:
        out += "\nNothing was approved, so nothing was written."
    if cmd == "undo" and "Undone" in out:
        last_log = None
    return out


def read_real(qr_text, rows_json, margin):
    rows = [r for r in json.loads(rows_json) if r.strip()]
    out = {"qr": None, "qr_error": None, "proof": None}
    fiscal = None
    if qr_text:
        try:
            fiscal = qr.parse(qr_text)
            out["qr"] = {
                "supplier_nif": fiscal.supplier_nif, "number": fiscal.number, "doc_type": fiscal.doc_type,
                "date": f"{fiscal.date[6:8]}/{fiscal.date[4:6]}/{fiscal.date[:4]}", "total": fiscal.total,
                "total_vat": fiscal.total_vat, "bases": {str(k): v for k, v in fiscal.bases.items()},
            }
        except qr.QRError as e:
            out["qr_error"] = str(e)

    product_rows = [r for r in rows if not _SUMMARY_ROW.search(r)]
    parsed, rejected = lines.parse_invoice(product_rows)

    # With a single VAT rate on the invoice, a line whose rate was not read can only be that rate.
    if fiscal and len(fiscal.bases) == 1:
        only = next(iter(fiscal.bases))
        for ln in parsed:
            if ln.vat is None:
                ln.vat = only
                ln.notes.append(f"IVA {only}% tirado do QR (a factura só tem uma taxa)")

    out["lines"] = [{
        "code": ln.code, "desc": ln.description, "qty": ln.qty, "unit_cost": ln.unit_cost, "value": ln.value,
        "vat": ln.vat, "discount": ln.discount, "doubtful": ln.doubtful, "notes": ln.notes,
        "price": shelf_price(ln.unit_cost, float(margin), ln.vat) if ln.vat else None,
    } for ln in parsed]
    out["rows_read"] = len(rows)
    out["rows_not_closed"] = len(rejected)
    # Rows with money-like numbers that still did not close: probably a product with a misread number.
    out["suspect_rows"] = [t for _, t in rejected if len(re.findall(r"\d+,\d{2,4}\b", t)) >= 2]
    out["sum_read"] = round(sum(ln.value for ln in parsed), 2)

    if fiscal:
        pr = proof.prove(parsed, fiscal)
        out["proof"] = {
            "proven": pr.proven,
            "rates": [{"rate": r.rate, "declared": r.declared, "read": r.read, "lines": r.lines, "gap": r.gap, "ok": r.ok}
                      for r in pr.rates],
            "problems": pr.problems,
        }
    return json.dumps(out, ensure_ascii=False)
