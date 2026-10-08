"""Cruza as linhas das facturas com o que o T-BackOffice sabe de cada artigo. So LEITURA.

A LIGACAO, descoberta a 2026-09-14: a coluna do codigo de fornecedor esta vazia ('0' em todos os
20.827 codigos), mas muitos artigos da loja tem como CODIGO o codigo do Recheio com um "R" a
frente — o 731210.0 da factura e o R731210 da loja, o 744337.0 e o R744337. Alguem os criou a
partir do catalogo do Recheio. Para esses a ligacao e exacta, sem adivinhar pela descricao.
O sufixo ".0/.1/.2" do Recheio fica de fora da comparacao.

O QUE SE CONFERE EM CADA LINHA LIGADA, e porque:
  IVA da factura contra IVA do artigo. Uma diferenca quer dizer uma de duas coisas, e ambas
    interessam: ou a ligacao esta errada, ou o artigo esta com a taxa errada na caixa — e a caixa
    esta a cobrar o IVA errado ao cliente.
  Custo da factura contra o custo medio. Muito longe (metade, o dobro) e quase sempre uma
    embalagem contada de maneira diferente: a factura traz o preco por iogurte e a loja vende o
    pack de 4, ou ao contrario. Nao se propoe preco nenhum em cima disso.
  Margem que o PVP actual da com o custo desta factura — o numero que interessa para decidir.

A ligacao pelo codigo NAO prova que o artigo e o mesmo — prova que alguem, algum dia, o criou
com aquele codigo. As duas verificacoes de cima sao o que apanha uma ligacao errada. As provas
de soma das facturas (linha, TRANSPORTE, QR) provam os numeros; nao provam o artigo.

Uso:  python\\python.exe cruza.py
"""
import csv
import io
import os
import re
import sys
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import linhas_factura as LF
import motor_precos as MP

FACTURAS = {   # por agora a mao; mais tarde vem da pagina do telemovel, uma factura de cada vez
    "Pao de Mafra FT FA.2026/9571 (14/09)": ["2026-09-14_pao_mafra.jpg"],
    "Recheio FR .../0000020398 (12/09)": ["2026-09-12_recheio_p1.jpg", "2026-09-12_recheio_p2.jpg"],
    "Recheio FR .../0000072816 (11/09)": ["2026-09-11_recheio72816_p%d.jpg" % i
                                          for i in (3, 4, 5, 6)],
}

# Custo da factura / custo medio fora disto: nao se confia na ligacao para propor preco.
RAZAO_MIN, RAZAO_MAX = 0.6, 1.7


def artigos_por_id(c):
    q = """
    SELECT a.ArtigoID, a.ArtDes, a.FamCodigo, a.PrecComMedio, v.PVP, i.IVA
    FROM Artigo a
    LEFT JOIN PrecoVenda v ON v.ArtigoID = a.ArtigoID AND v.PrecoNum = 1
    LEFT JOIN IVA i ON i.CodIVA = v.CodIVA"""
    return {r.ArtigoID: {"desc": (r.ArtDes or "").strip(), "fam": r.FamCodigo or "",
                         "custo": float(r.PrecComMedio or 0), "pvp": float(r.PVP or 0),
                         "iva": float(r.IVA) if r.IVA is not None else None}
            for r in c.execute(q)}


def liga(codigo, arts):
    """Artigo da loja para um codigo de fornecedor. So a via exacta, por agora: "R" + codigo."""
    base = codigo.split(".")[0]
    for cand in ("R" + base,):
        if cand in arts:
            return cand
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    c = MP.ligar()
    arts = artigos_por_id(c)
    vend = MP.vendas(c)
    # margem habitual da familia, a mesma referencia do motor de precos
    lista = [dict(id=k, desc=v["desc"], fam=v["fam"], custo=v["custo"], pvp=v["pvp"],
                  iva=v["iva"] or 0.0, fam_desc="", ean="") for k, v in arts.items()]
    fams, loja = MP.referencias(lista)
    n_r = sum(1 for k in arts if re.match(r"^R\d{6}$", k))
    print("artigos da loja com codigo 'R' + 6 algarismos: %d de %d" % (n_r, len(arts)))

    saida = []
    for nome, fotos in FACTURAS.items():
        fac = LF.le_factura([os.path.join(AQUI, "facturas", f) for f in fotos])
        linhas = [l for p in fac["paginas"] for l in p["linhas"]]
        ligadas = 0
        print("\n== %s — %d linhas lidas" % (nome, len(linhas)))
        for l in linhas:
            aid = liga(l["codigo"], arts)
            a = arts.get(aid) if aid else None
            r = {"factura": nome, "cod_fornecedor": l["codigo"], "desc_factura": l["descricao"],
                 "qtd": l["quantidade"], "custo_factura": l["preco"], "iva_factura": l["iva"],
                 "artigo": aid or "", "desc_loja": a["desc"] if a else "",
                 "custo_medio": a["custo"] if a else None, "pvp": a["pvp"] if a else None,
                 "iva_loja": a["iva"] if a else None, "vendidos_90d": vend.get(aid, 0) if aid else 0}
            estado = "sem ligacao"
            if a:
                ligadas += 1
                avisos = []
                if l["iva"] is not None and a["iva"] is not None and abs(l["iva"] - a["iva"]) > 0.01:
                    avisos.append("IVA %g%% na factura, %g%% na loja" % (l["iva"], a["iva"]))
                razao = (l["preco"] / a["custo"]) if a["custo"] > 0 else None
                r["razao_custo"] = razao
                if razao is None:
                    avisos.append("artigo sem custo medio")
                elif not (RAZAO_MIN <= razao <= RAZAO_MAX):
                    avisos.append("custo %.2fx o medio (embalagem diferente?)" % razao)
                if a["pvp"] > 0 and a["iva"] is not None:
                    base = a["pvp"] / (1 + a["iva"] / 100.0)
                    r["margem_actual"] = base / l["preco"] - 1
                    ref = (fams.get(a["fam"]) or loja)["mediana"]
                    r["margem_habitual"] = ref
                    r["pvp_sugerido"] = l["preco"] * (1 + ref) * (1 + a["iva"] / 100.0)
                estado = "; ".join(avisos) if avisos else "ok"
            r["estado"] = estado
            saida.append(r)
        print("   ligadas pelo codigo: %d de %d (%.0f%%)"
              % (ligadas, len(linhas), 100.0 * ligadas / max(1, len(linhas))))

    # --- resumo e folha
    lig = [r for r in saida if r["artigo"]]
    ok = [r for r in lig if r["estado"] == "ok"]
    print("\nno total: %d linhas, %d ligadas, %d sem nenhum aviso" % (len(saida), len(lig), len(ok)))
    tipos = defaultdict(int)
    for r in lig:
        for a in r["estado"].split("; "):
            if a != "ok":
                tipos[re.sub(r"[\d.,]+", "#", a)] += 1
    for k, v in sorted(tipos.items(), key=lambda x: -x[1]):
        print("   %-50s %d" % (k, v))

    print("\nas ligadas que vendem, com a margem que o PVP actual da ao custo desta factura:")
    for r in sorted(lig, key=lambda r: -(r["vendidos_90d"] or 0))[:15]:
        m = r.get("margem_actual")
        print("   %-8s %-30s custo fact %6.2f | medio %6.2f | PVP %5.2f | margem %6s | %s"
              % (r["artigo"], r["desc_loja"][:30], r["custo_factura"], r["custo_medio"] or 0,
                 r["pvp"] or 0, ("%.0f%%" % (m * 100)) if m is not None else "?", r["estado"]))

    dest = os.path.join(AQUI, "cruzamento_facturas.csv")
    cols = ["factura", "estado", "cod_fornecedor", "desc_factura", "artigo", "desc_loja", "qtd",
            "custo_factura", "custo_medio", "razao_custo", "iva_factura", "iva_loja", "pvp",
            "margem_actual", "margem_habitual", "pvp_sugerido", "vendidos_90d"]

    def fmt(v):
        if isinstance(v, float):
            return ("%.4f" % v).rstrip("0").rstrip(".").replace(".", ",")
        return "" if v is None else str(v)

    with io.open(dest, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for r in saida:
            w.writerow([fmt(r.get(k)) for k in cols])
    print("\nfolha: %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
