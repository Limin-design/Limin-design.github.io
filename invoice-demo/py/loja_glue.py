"""Runs the store app's own invoice reading in the browser: py/loja/ holds the store's modules, unchanged.

At the store the reader gets its text boxes from RapidOCR. Here the boxes come from the same PaddleOCR
models (PP-OCRv4) running in the browser, in the same shape: [x_min, x_max, y_centre, height, text,
confidence, slope]. Everything after the boxes is the store's: linhas_factura reads each page,
propoe.sem_sobreposicao / iva_da_referencia / _tenta_com_iva / _so_se_ajudar finish the invoice, and
prova.avalia decides whether it is proved.

Two things differ from the store, and both come from the OCR engine, not from the rules:
  - The store reads each page twice (the photo as taken and flattened by the UVDoc model, endireita.py).
    The browser has no UVDoc, so each page is read once, from the photo.
  - The browser's text detector sometimes keeps a whole table row in one box ("2564300010001 GOMAS ...
    1,000 UN 7,6800 10,00 23,00"), where RapidOCR at the store cuts it at the column gaps. So the invoice
    is read with the boxes as they came and with each box cut into words, and the reading that the QR
    proves is the one that stays. Without proof, the one closest to the QR stays, and it stays unproved.
"""
import json
import re
import sys

sys.path.insert(0, "/home/pyodide/py/loja")

import linhas_factura as LF  # noqa: E402
import propoe as P  # noqa: E402
import prova as PR  # noqa: E402
import qr_factura as QF  # noqa: E402

_BOXES = {}


def _ocr_cru(caminho):
    return _BOXES[caminho]


LF._ocr_cru = _ocr_cru  # the boxes come from the page, not from RapidOCR on this machine


class _UmaLeitura:
    """What propoe expects from endireita.py, without the flattening model: one reading per page."""

    @staticmethod
    def le_pagina_dupla(caminho, formato=None):
        return LF.le_pagina(caminho, formato)


# A word is "a number" when it starts with a digit and has only digits and separators: "1,000", "7,6800",
# "2564300010001", "31/07/2028", "6,4523,0". "12x90G" or "250GR" stay with the description.
_NUMERO = re.compile(r"^[-+(]?\d[\d.,/:%-]*\)?$")
_ZERO_O = re.compile(r"(?<!\S)\d{1,7},[\dO]{1,3}C?(?!\S)")


def _partida(caixas):
    """Each box cut into words, with x shared out by character position; neighbouring words that are not
    numbers stay together (a description is one box, as at the store). A first word with digits followed
    by more words is the supplier's reference ("TCC45P6W4000 LAMPADA..."): it gets its own box, which is
    what lets the generic reader measure where the description column starts."""
    fora = []
    for x0, x1, y, h, texto, conf, incl in caixas:
        palavras = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", texto)]
        if len(palavras) < 2 or not any(_NUMERO.match(p) for _, _, p in palavras):
            fora.append([x0, x1, y, h, texto, conf, incl])
            continue
        n = max(1, len(texto))
        grupos = []
        # (longer than the reader's 25 characters, it is a reference glued to the description: the generic
        # reader cuts it at the description column, as at the store)
        referencia = bool(re.search(r"\d", palavras[0][2])) and len(palavras[0][2]) <= 25
        for a, b, p in palavras:
            if len(grupos) == 1 and referencia:
                grupos.append((a, b, p))
            elif grupos and not _NUMERO.match(p) and not _NUMERO.match(grupos[-1][2]):
                grupos[-1] = (grupos[-1][0], b, grupos[-1][2] + " " + p)
            else:
                grupos.append((a, b, p))
        for a, b, p in grupos:
            fora.append([x0 + (x1 - x0) * a / n, x0 + (x1 - x0) * b / n, y, h, p, conf, incl])
    return fora


def _le_factura(nomes, qr):
    """propoe.le_factura, with one reading per page instead of two (see the module docstring)."""
    fac = {"paginas": P.sem_sobreposicao([LF.le_pagina(n) for n in nomes]), "qr": qr, "formato": None,
           "impresso": P.totais_impressos(nomes, qr)}
    P.iva_da_referencia(fac)
    return P._so_se_ajudar(P._tenta_com_iva(fac, nomes, None, _UmaLeitura))


def _distancia(r):
    return sum(abs(v) for v in (r.get("faltam") or {}).values()) if r.get("declarado") else float("inf")


def _provas(fac):
    """The proofs as the store's phone screen lists them (servidor.provas): per VAT rate, the exempt base
    (deposits) and the 'not subject' base (tobacco)."""
    q = fac.get("qr")
    if not q:
        return []
    linhas = [l for p in fac["paginas"] for l in p["linhas"]]
    por_taxa = {}
    for l in linhas:
        if l["iva"] is not None:
            por_taxa[l["iva"]] = por_taxa.get(l["iva"], 0.0) + l["valor"]
    fora = []
    for taxa, nome in ((6.0, "reduzida"), (13.0, "intermedia"), (23.0, "normal")):
        esperado = q["por_taxa"].get(nome, {}).get("base", 0.0)
        lido = round(por_taxa.get(taxa, 0.0), 2)
        if esperado or lido:
            fora.append({"nome": "IVA %g%%" % taxa, "qr": esperado, "lido": lido, "bate": abs(esperado - lido) <= 0.02})
    if q.get("base_isenta") or por_taxa.get(0.0):
        esperado, lido = q.get("base_isenta") or 0.0, round(por_taxa.get(0.0, 0.0), 2)
        fora.append({"nome": "Isento (depósitos)", "qr": esperado, "lido": lido, "bate": abs(esperado - lido) <= 0.02})
    if q.get("nao_sujeito"):
        lido = round(sum(l["valor"] for l in linhas if l["iva"] is None), 2)
        fora.append({"nome": "Não sujeito (tabaco)", "qr": q["nao_sujeito"], "lido": lido,
                     "bate": abs(q["nao_sujeito"] - lido) <= 0.02})
    return fora


def le(paginas_json, qr_text, margem):
    paginas = json.loads(paginas_json)
    q = QF.interpreta(qr_text) if qr_text else None
    _BOXES.clear()

    # the browser's recogniser reads some zeros in a number as the letter O ("23,OC" for "23,0C"); RapidOCR at
    # the store does not, so the store's rules only expect the C ("ZERO_LETRA_FIM")
    paginas = [[c[:4] + [_ZERO_O.sub(lambda m: m.group().replace("O", "0"), c[4])] + c[5:] for c in p] for p in paginas]
    leituras = []
    for como, prepara in (("caixas como vieram", lambda c: c), ("caixas partidas em palavras", _partida)):
        nomes = []
        for i, caixas in enumerate(paginas):
            nome = "pagina_%d_%d.jpg" % (len(leituras), i + 1)
            _BOXES[nome] = prepara(caixas)
            nomes.append(nome)
        fac = _le_factura(nomes, q)
        r = PR.avalia(fac["paginas"], q, fac.get("impresso"))
        leituras.append((como, fac, r))
    # proved first; then closest to the QR; then the most lines (only to break a tie)
    como, fac, r = min(leituras, key=lambda t: (not t[2]["provada"], _distancia(t[2]), -t[2]["linhas"]))

    avisos = []
    soltos = [str(k.get("codigo") or "?") for p in fac["paginas"] for k in (p.get("sem_conta") or [])]
    if soltos and r.get("declarado") and not r.get("faltam"):
        avisos.append("As somas batem, mas %d código(s) ficaram sem números (%s)." % (len(soltos), ", ".join(soltos[:6])))
    if not r["provada"]:
        for i, p in enumerate(fac["paginas"]):
            px = LF.letra_px(p["ficheiro"])
            if px and px < LF.LETRA_MINIMA and (p["linhas"] or p.get("sem_conta") or p.get("sem_codigo")):
                avisos.append("A letra está pequena na página %d (%s px por letra; lê-se bem a partir de %g): "
                              "a foto foi tirada de longe. Tira outra mais de perto." % (i + 1, px, LF.LETRA_MINIMA))

    m = float(margem)
    for p in fac["paginas"]:
        for ln in p["linhas"]:
            iva = ln.get("iva")
            ln["pvp"] = round(ln["preco"] * (1 + m / 100) * (1 + iva / 100) + 1e-9, 2) if iva is not None else None

    problemas_qr = QF.confere(q) if q else []
    if q:
        q = {k: v for k, v in q.items() if not k.startswith("_")}
    return json.dumps({
        "paginas": fac["paginas"], "qr": q, "problemas_qr": problemas_qr,
        "prova": _provas(fac), "provada": r["provada"], "porque": r["porque"], "avisos": avisos,
        "leitura": como,
    }, ensure_ascii=False, default=str)
