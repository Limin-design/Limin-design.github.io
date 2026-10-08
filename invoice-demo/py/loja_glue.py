"""Runs the store app's own invoice reader (py/loja/linhas_factura.py and qr_factura.py) in the browser.

At the store the reader gets its text boxes from RapidOCR. Here the boxes come from the same PaddleOCR
models (PP-OCRv4) running in the browser, in the same shape: [x_min, x_max, y_centre, height, text,
confidence, slope]. The only change is where the boxes come from; the reading rules are the store's.
"""
import json
import sys

sys.path.insert(0, "/home/pyodide/py/loja")

import linhas_factura as LF  # noqa: E402
import qr_factura as QF  # noqa: E402

_BOXES = {}


def _ocr_cru(caminho):
    return _BOXES[caminho]


LF._ocr_cru = _ocr_cru  # the boxes come from the page, not from RapidOCR on this machine

TAXAS = {6.0: "reduzida", 13.0: "intermedia", 23.0: "normal"}


def le(paginas_json, qr_text, margem):
    paginas = json.loads(paginas_json)
    nomes = []
    for i, caixas in enumerate(paginas):
        nome = f"pagina_{i + 1}.jpg"
        _BOXES[nome] = caixas
        nomes.append(nome)
    pags = [LF.le_pagina(n) for n in nomes]

    q = QF.interpreta(qr_text) if qr_text else None
    problemas_qr = QF.confere(q) if q else []

    por_taxa = {}
    for p in pags:
        for ln in p["linhas"]:
            if ln.get("iva") is not None:
                por_taxa[ln["iva"]] = por_taxa.get(ln["iva"], 0.0) + ln["valor"]

    prova = []
    if q:
        for taxa, nome in TAXAS.items():
            esperado = q["por_taxa"].get(nome, {}).get("base", 0.0)
            lido = round(por_taxa.get(taxa, 0.0), 2)
            if esperado or lido:
                prova.append({"taxa": taxa, "qr": esperado, "lido": lido, "bate": abs(esperado - lido) <= 0.02})
        if q["base_isenta"] or por_taxa.get(0.0):
            lido = round(por_taxa.get(0.0, 0.0), 2)
            prova.append({"taxa": 0.0, "qr": q["base_isenta"], "lido": lido,
                          "bate": abs(q["base_isenta"] - lido) <= 0.02})

    m = float(margem)
    for p in pags:
        for ln in p["linhas"]:
            iva = ln.get("iva")
            ln["pvp"] = round(ln["preco"] * (1 + m / 100) * (1 + iva / 100) + 1e-9, 2) if iva is not None else None

    if q:
        q = {k: v for k, v in q.items() if not k.startswith("_")}
    return json.dumps({
        "paginas": pags, "qr": q, "problemas_qr": problemas_qr, "prova": prova,
        "provada": bool(q) and bool(prova) and all(x["bate"] for x in prova)
                   and not any(p["duvidosa"] for p in pags),
    }, ensure_ascii=False, default=str)
