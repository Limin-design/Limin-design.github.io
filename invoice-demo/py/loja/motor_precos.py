"""Revisao de precos da loja, a partir do que o T-BackOffice ja sabe. So LEITURA.

O que isto responde, sem fotos nenhumas: que artigos estao a vender abaixo do custo, que artigos
tem uma margem muito fora do que a propria loja pratica naquela familia, e quanto dinheiro isso
representou nos ultimos 90 dias. E o motor que a leitura das facturas vai alimentar: quando uma
factura trouxer um custo novo, e aqui que se decide se o preco tem de mudar.

REGRAS QUE ESTE FICHEIRO SEGUE, e porque:

  So leitura, e sem travar a caixa. A ligacao corre em READ UNCOMMITTED: le sem pedir bloqueios,
  para uma consulta nossa nunca deixar um cliente a espera na caixa. Nao ha um unico UPDATE, INSERT
  ou DELETE neste ficheiro — o preco muda-o o Pedro no T-BackOffice, nunca nos.

  A margem de referencia e a DA LOJA, familia a familia. Nao ha uma percentagem inventada aqui: a
  mediana de cada familia sai dos precos que ja estao na caixa. Se a loja pratica 22% nos
  lacticinios, e contra 22% que um lacticinio e comparado.

  Ordenado por DINHEIRO EM JOGO, nao por numero de casos. Um artigo abaixo do custo que se vende
  500 vezes por mes importa mais do que um que se vendeu duas vezes. E o principio da
  materialidade (ISA 320) que o swarm ja usa, aplicado a caixa.

  Nao se propoe preco sem custo. Um artigo sem custo medio aparece como tal, e nao com uma
  sugestao calculada sobre zero.

LIMITES QUE TEM DE SER DITOS:

  O custo e o CUSTO MEDIO do T-BackOffice. Com os precos a subir, a media fica abaixo da ultima
  compra, e a margem real e PIOR do que a que aqui aparece. E exactamente por isso que a leitura
  das facturas vale a pena: traz o custo de hoje, nao a media.

  So o preco de nivel 1 (o PVP normal). Os niveis 2 e 3 existem na base de dados e ficam de fora.

  Na base de dados nao ha historico de precos: a data de alteracao e reescrita todas as noites
  pela sincronizacao, e o "preco anterior" nunca foi preenchido. O historico passa a ser nosso.

Uso:  python\\python.exe motor_precos.py
"""
import csv
import io
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))

if AQUI not in sys.path:
    sys.path.insert(0, AQUI)
try:                                  # a base das caixas DESTA loja (config\loja.json)
    import loja_config as _LC
    LIGACAO = _LC.sql_ligacao()
except ImportError:
    LIGACAO = ("DRIVER={SQL Server};SERVER=.;DATABASE=NewPosserver;Trusted_Connection=yes;")

# Documentos que sao VENDA e movem stock (TipoDoc.DocStock = 1): 001 e o talao da caixa, 004 a
# factura-recibo. O 006 (talao de pagamento) e o registo do pagamento do mesmo talao — conta-lo
# era contar cada venda duas vezes.
DOCS_VENDA = ("001", "004")

DIAS_VENDAS = 90
MIN_FAMILIA = 5            # abaixo disto a mediana e um acaso: usa-se a da loja inteira

# "Abaixo do custo" so a partir de 1 centimo por unidade. A primeira corrida acusou um artigo
# 0,35 centimos abaixo, com 1 unidade vendida — arredondamento, nao prejuizo. Chamar ABAIXO DO
# CUSTO a isso gasta a palavra, e da proxima vez que ela aparecer ja ninguem olha.
TOLERANCIA_CUSTO = 0.01


def ligar():
    import pyodbc
    c = pyodbc.connect(LIGACAO, autocommit=True, timeout=15)
    c.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
    return c


def artigos(c):
    """Um registo por artigo: custo medio, PVP de nivel 1, IVA, familia e um codigo de barras."""
    q = """
    SELECT a.ArtigoID, a.ArtDes, a.FamCodigo, f.FamDes, a.PrecComMedio, v.PVP, i.IVA,
           (SELECT TOP 1 k.CodBarras FROM ArtigoCodigo k
             WHERE k.ArtigoID = a.ArtigoID ORDER BY k.Principal DESC, k.CodBarras) AS ean
    FROM Artigo a
    LEFT JOIN Familia f   ON f.FamCodigo = a.FamCodigo
    LEFT JOIN PrecoVenda v ON v.ArtigoID = a.ArtigoID AND v.PrecoNum = 1
    LEFT JOIN IVA i       ON i.CodIVA = v.CodIVA
    WHERE ISNULL(a.descontinuado, 0) = 0
    """
    fora = []
    for r in c.execute(q):
        fora.append({"id": r.ArtigoID, "desc": (r.ArtDes or "").strip(),
                     "fam": r.FamCodigo or "", "fam_desc": (r.FamDes or "").strip(),
                     "custo": float(r.PrecComMedio or 0), "pvp": float(r.PVP or 0),
                     "iva": float(r.IVA or 0), "ean": r.ean or ""})
    return fora


def vendas(c, dias=DIAS_VENDAS):
    """Quantidade vendida por artigo nos ultimos `dias`, tal como a caixa a regista."""
    q = """
    SELECT l.ArtigoID, SUM(l.Quantidade) AS qtd
    FROM LinhaArtigos l
    JOIN Documentos d ON d.DocID = l.DocID AND d.DocTyp = l.DocTyp AND d.DocPosID = l.DocPosID
    WHERE d.DataDoc >= DATEADD(day, ?, GETDATE())
      AND d.DocTyp IN (%s)
      AND ISNULL(d.Anulado, 0) = 0
    GROUP BY l.ArtigoID
    """ % ",".join("?" * len(DOCS_VENDA))
    return {r.ArtigoID: float(r.qtd or 0) for r in c.execute(q, -dias, *DOCS_VENDA)}


def base_sem_iva(a):
    return a["pvp"] / (1.0 + a["iva"] / 100.0) if a["pvp"] > 0 else 0.0


def markup(a):
    """Margem sobre o CUSTO (base sem IVA / custo - 1). None quando nao ha como calcular."""
    b = base_sem_iva(a)
    if a["custo"] <= 0 or b <= 0:
        return None
    return b / a["custo"] - 1.0


def referencias(arts):
    """A margem que a loja pratica, por familia: mediana e limites de 'fora do normal'.

    Os limites sao os de Tukey (Q1 - 1,5 x IQR e Q3 + 1,5 x IQR): o criterio classico para dizer
    'isto e invulgar AQUI', que se ajusta sozinho a familias de margem apertada e larga."""
    por_fam = defaultdict(list)
    todos = []
    for a in arts:
        m = markup(a)
        if m is not None:
            por_fam[a["fam"]].append(m)
            todos.append(m)

    def resumo(xs):
        xs = sorted(xs)
        q = statistics.quantiles(xs, n=4) if len(xs) >= 4 else [xs[0], statistics.median(xs), xs[-1]]
        iqr = q[2] - q[0]
        return {"mediana": statistics.median(xs), "baixo": q[0] - 1.5 * iqr,
                "alto": q[2] + 1.5 * iqr, "n": len(xs)}

    loja = resumo(todos)
    fams = {f: resumo(xs) for f, xs in por_fam.items() if len(xs) >= MIN_FAMILIA}
    return fams, loja


def arredonda_5(v):
    """Para cima, ao proximo multiplo de 5 centimos — o final da maioria dos precos da loja."""
    import math
    return math.ceil(round(v * 100, 6) / 5.0) * 5 / 100.0


def analisa(arts, vend, fams, loja):
    linhas = []
    for a in arts:
        ref = fams.get(a["fam"])
        origem = "familia" if ref else "loja (familia com poucos artigos)"
        ref = ref or loja
        m = markup(a)
        qtd = vend.get(a["id"], 0.0)
        b = base_sem_iva(a)
        sugerido = a["custo"] * (1 + ref["mediana"]) * (1 + a["iva"] / 100.0) if a["custo"] > 0 else None

        if a["pvp"] <= 0 and a["custo"] <= 0 and qtd > 0:
            # PRECO ABERTO: o preco escreve-se na caixa (legumes, peixe, "diversos"). Nao e um
            # erro — e uma pratica valida. A primeira versao chamava-lhe "sem preco de venda".
            # O que tem de se dizer e outra coisa: estas vendas nao tem margem visivel nenhuma.
            motivo, prio, em_jogo = "preco aberto na caixa (margem invisivel)", 4, None
        elif a["pvp"] <= 0:
            motivo, prio, em_jogo = "sem preco de venda", 2, None
        elif a["custo"] <= 0:
            motivo, prio, em_jogo = "sem custo medio (nao se calcula margem)", 4, None
        elif a["custo"] - b > TOLERANCIA_CUSTO:
            # prejuizo por unidade vezes o que se vendeu: dinheiro que SAIU
            motivo, prio, em_jogo = "ABAIXO DO CUSTO", 1, (a["custo"] - b) * qtd
        elif m < ref["baixo"]:
            base_sug = a["custo"] * (1 + ref["mediana"])
            motivo, prio, em_jogo = "margem muito abaixo do habitual", 3, (base_sug - b) * qtd
        elif m > ref["alto"]:
            motivo, prio, em_jogo = "margem muito acima do habitual (erro de preco?)", 5, None
        else:
            continue
        linhas.append(dict(a, motivo=motivo, prio=prio, markup=m, ref=ref["mediana"],
                           origem=origem, qtd=qtd, em_jogo=em_jogo, sugerido=sugerido))
    # O QUE VENDE a frente, o catalogo PARADO no fim. Medido a 2026-09-14: dos 1.795 alertas da
    # primeira corrida, so 155 eram de artigos com vendas nos ultimos 90 dias — o catalogo tem
    # 16.832 artigos e vendem 1.603 por trimestre. Uma folha ordenada so por gravidade abria com
    # centenas de artigos que ninguem compra, e o que importava ficava enterrado. Os parados nao
    # desaparecem (podem voltar a vender com o preco errado); vao para segundo plano.
    # Dentro de cada grupo: dinheiro em jogo primeiro, depois a gravidade.
    linhas.sort(key=lambda x: (x["qtd"] <= 0, x["em_jogo"] is None, -(x["em_jogo"] or 0),
                               x["prio"]))
    return linhas


def _n(v, casas=2):
    if v is None:
        return ""
    return ("%.*f" % (casas, v)).replace(".", ",")


def escreve(linhas, caminho):
    cols = ["Estado", "Motivo", "Artigo", "Descricao", "Codigo de barras", "Familia",
            "Custo medio (s/ IVA)", "PVP actual", "Margem s/ custo %", "Margem habitual %",
            "Referencia", "PVP que repoe a margem", "PVP arredondado (5 cent.)",
            "Vendidos 90 dias", "EUR em jogo 90 dias"]
    # utf-8-sig e ';' com virgula decimal: abre no Excel portugues com duplo clique
    with io.open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for x in linhas:
            w.writerow(["vende" if x["qtd"] > 0 else "parado 90 dias",
                        x["motivo"], x["id"], x["desc"], x["ean"],
                        ("%s %s" % (x["fam"], x["fam_desc"])).strip(),
                        _n(x["custo"]), _n(x["pvp"]),
                        _n(x["markup"] * 100, 1) if x["markup"] is not None else "",
                        _n(x["ref"] * 100, 1), x["origem"],
                        _n(x["sugerido"]), _n(arredonda_5(x["sugerido"])) if x["sugerido"] else "",
                        _n(x["qtd"], 0), _n(x["em_jogo"])])
    return caminho


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    c = ligar()
    arts = artigos(c)
    vend = vendas(c)
    fams, loja = referencias(arts)
    linhas = analisa(arts, vend, fams, loja)
    dest = os.path.join(AQUI, "revisao_precos_%s.csv" % datetime.now().strftime("%Y-%m-%d"))
    escreve(linhas, dest)

    from collections import Counter
    activos = [x for x in linhas if x["qtd"] > 0]
    cont_a = Counter(x["motivo"] for x in activos)
    cont_p = Counter(x["motivo"] for x in linhas if x["qtd"] <= 0)
    perda = sum(x["em_jogo"] or 0 for x in linhas if x["prio"] == 1)
    falta = sum(x["em_jogo"] or 0 for x in linhas if x["prio"] == 3)
    print("artigos analisados: %d | com vendas nos ultimos %d dias: %d"
          % (len(arts), DIAS_VENDAS, sum(1 for a in arts if vend.get(a["id"]))))
    print("margem mediana da loja: %.1f%% | familias com referencia propria: %d"
          % (loja["mediana"] * 100, len(fams)))
    print()
    print("  %-50s %7s %7s" % ("", "vendem", "parados"))
    for k in sorted(set(cont_a) | set(cont_p), key=lambda k: -cont_a.get(k, 0)):
        print("  %-50s %7d %7d" % (k, cont_a.get(k, 0), cont_p.get(k, 0)))
    print()
    print("vendido abaixo do custo nos ultimos %d dias: %.2f EUR perdidos" % (DIAS_VENDAS, perda))
    print("margem que ficou por fazer nos de margem muito baixa: %.2f EUR" % falta)
    print()
    print("folha: %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
