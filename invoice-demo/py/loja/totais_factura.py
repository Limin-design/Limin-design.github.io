"""OS TOTAIS IMPRESSOS NA FACTURA — a prova de quem nao tem QR legivel.

O QR fiscal e a melhor referencia que existe: vem lido por maquina e confere-se consigo proprio. Mas
cinco dos documentos que temos nao tem QR que se leia (o rolo de caixa amassado, as A4 fotografadas
de lado), e sem referencia nenhuma nada fica provado — por melhor que a leitura pareca. O Pedro
decidiu a 25/09: "quando n ha qr temos de ir a olho e pelos totais".

Entao le-se O RESUMO DO IVA — a tabelinha do fundo, "Taxa | Valor s/IVA | Valor IVA". Da a base de
cada taxa, que e exactamente o que a prova compara. Medido na factura de 591,49 EUR
(20260923_113358): 6% -> 118,24 / 7,09 e 23% -> 378,99 / 87,17, que e o que o QR da outra foto do
mesmo documento diz ao centimo.

(O outro numero impresso destas facturas, o "TRANSPORTE" acumulado das A4 do Recheio, ja e lido por
linhas_factura.transportes e nao se le outra vez aqui.)

O QUE NAO SE PODE FAZER e confiar num numero lido por OCR so porque tem a forma certa: um algarismo
trocado provava a factura errada. Duas coisas guardam isto, e as duas foram medidas a 25/09 contra as
28 facturas que tem QR:

  1. A ANCORA. So contam as filas logo abaixo do cabecalho do resumo, no fundo da pagina. Sem ancora,
     filas de ARTIGO passavam por filas do resumo — "216948.1 LASANHA BOLONHESA 6 6,000 1,95" tem um
     "6" que parece uma taxa e dois numeros que por acaso fecham a 6%. Cinco facturas ficavam com o
     papel a contradizer o QR.
  2. A CONTA DE CADA FILA: base x taxa = imposto, ao centimo. Sao dois numeros independentes a ter de
     concordar, e e isso que distingue um numero lido de um numero adivinhado. A fila da taxa 0 so
     entra se trouxer o imposto (0,00) impresso ao lado — aceitar ali um numero solto foi a causa de
     quatro leituras erradas.

Uma tabela a que o OCR perdeu uma fila declara MENOS do que as linhas lidas: a prova ve a diferenca e
a factura fica sem prova. E o comportamento certo, e e a razao por que isto e seguro — o erro cai
sempre para o lado de pedir ajuda, nunca para o lado de gravar um preco errado.

Uso:  python\\python.exe totais_factura.py facturas\\*.jpg
"""
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

# As taxas que existem no continente. A mesma lista do leitor das linhas: uma "taxa" de 15% nao existe
# e e sinal de leitura errada, nao de uma taxa nova.
TAXAS = (0.0, 6.0, 13.0, 23.0)
TOLERANCIA = 0.02          # dois centimos por fila
FOLGA_TOTAL = 0.05         # e cinco no total, onde os arredondamentos de todas as filas se somam

# "6%", "23%", "6,00", "23,00" — a taxa na primeira coluna do resumo
TAXA = re.compile(r"^(\d{1,2})(?:[.,]0{1,2})?\s*%?$")
# um valor em euros: leva sempre virgula (ou ponto) e dois decimais. "118,24", "1.021,27", "87.17"
VALOR = re.compile(r"^\(?-?(\d{1,3}(?:[.\s]\d{3})*|\d+)[.,](\d{2})\)?$")
# as palavras que anunciam a tabela do resumo, em qualquer das grafias que os fornecedores usam
# (o OCR come espacos e troca o "m" por "B": "ResuBo doIVA" e o que sai na factura do Recheio)
CABECA_RESUMO = re.compile(r"RES[UO][MB]?[O0]?\s*D[O0]?\s*IVA|TAXA\s*.*(?:INCID|VALOR\s*S/?\s*IVA)"
                           r"|INCIDENCIAS?", re.I)


def _num(t):
    """"1.021,27" -> 1021.27. None se nao for um valor em euros."""
    m = VALOR.match((t or "").strip())
    if not m:
        return None
    inteiro = re.sub(r"[.\s]", "", m.group(1))
    return float("%s.%s" % (inteiro, m.group(2)))


def _taxa(t):
    """"23%" -> 23.0, e so se for uma taxa que exista. None se nao for taxa."""
    m = TAXA.match((t or "").strip())
    if not m:
        return None
    v = float(m.group(1))
    return v if v in TAXAS else None


def _filas(caixas, passo=None):
    """As caixas do OCR agrupadas por fila (mesma altura), cada fila ordenada da esquerda para a
    direita. O passo e a altura tipica do texto: duas caixas mais proximas do que isso sao a mesma
    fila. Sem passo, calcula-se pela mediana das alturas — a mesma regra do leitor das linhas."""
    if not caixas:
        return []
    if passo is None:
        alturas = sorted(c[2] for c in caixas if c[2] > 0)
        passo = (alturas[len(alturas) // 2] if alturas else 12) * 0.7
    filas, actual, y0 = [], [], None
    for c in sorted(caixas, key=lambda c: c[1]):
        if y0 is None or abs(c[1] - y0) <= passo:
            actual.append(c)
            y0 = c[1] if y0 is None else y0
        else:
            filas.append(sorted(actual, key=lambda c: c[0]))
            actual, y0 = [c], c[1]
    if actual:
        filas.append(sorted(actual, key=lambda c: c[0]))
    return filas


def _numeros_da_fila(fila):
    """Os valores em euros de uma fila, pela ordem em que aparecem. Numeros colados pelo OCR
    ("118,247,09") nao se separam aqui: uma fila assim nao fecha a conta e e recusada, que e o
    comportamento certo — nao se adivinha onde acaba um numero e comeca o outro."""
    return [(_num(c[3]), c[0]) for c in fila if _num(c[3]) is not None]


FILAS_ABAIXO = 8           # a tabela do resumo tem 1 a 4 filas; 8 ja e folga a mais


def _cabeca(filas):
    """O indice da fila que anuncia o resumo ("Resumo do IVA", "IVA Incidencias Imposto"), ou None.

    ANCORAR AQUI E O QUE FAZ ISTO FUNCIONAR, e foi medido a 25/09. Sem a ancora, procurava-se uma
    fila com uma taxa e dois numeros que fizessem base x taxa = imposto em qualquer parte da pagina,
    e as filas de ARTIGO passavam: na factura 134427, "216948.1 LASANHA BOLONHESA 6 6,000 1,95 ..."
    tem um "6" (a quantidade) e dois numeros que por acaso fecham a 6%. Cinco facturas ficavam com o
    papel a contradizer o QR. As filas verdadeiras do resumo estao SEMPRE logo abaixo do cabecalho,
    no fundo da pagina (88% a 94% da altura, medido) — as de artigo estao a meio."""
    for i, fila in enumerate(filas):
        if CABECA_RESUMO.search(" ".join(c[3] for c in fila)):
            return i
    return None


def _fila_do_resumo(fila):
    """(taxa, base, imposto, x_taxa) de uma fila do resumo, ou None.

    A base e o imposto sao os DOIS PRIMEIROS valores a direita da taxa, e base x taxa tem de dar o
    imposto. Nao se procura mais longe: na pagina 6 do Recheio a fila "23,0 697,75 160,48 17,60"
    tem um quarto numero, que e da coluna dos Totais ao lado e nao desta tabela."""
    nums = _numeros_da_fila(fila)
    for c in fila:
        taxa = _taxa(c[3])
        if taxa is None:
            continue
        direita = [(v, x) for v, x in nums if x > c[0]]
        if len(direita) < 2:
            # A FILA DA TAXA 0 SO VALE COM O IMPOSTO IMPRESSO AO LADO (0,00). Aceitar a taxa 0 com um
            # numero solto a direita foi a causa de quatro leituras erradas a 25/09: ficava com o
            # primeiro numero que viesse depois de um "0,0" — na factura 122947 apanhou 61,09, que e
            # a soma das bases, e declarava uma base isenta que nao existe. Sem imposto ao lado nao
            # ha nada que confirme o numero, e um numero sem confirmacao nao entra.
            return None
        base, imposto = direita[0][0], direita[1][0]
        if base <= 0:
            return None
        folga = TOLERANCIA + 0.005 * max(1.0, base / 50.0)
        if abs(base * taxa / 100.0 - imposto) > folga:
            return None
        return (taxa, round(base, 2), round(imposto, 2), c[0])
    return None


def resumo_do_iva(caixas):
    """{taxa: base} da tabela "Resumo do IVA" impressa no fundo da pagina, ou None.

    A tabela encontra-se pelo cabecalho (`_cabeca`) e le-se para baixo, fila a fila, enquanto cada
    uma fizer base x taxa = imposto. Uma fila que tenha taxa e NAO feche para a tabela ali: ou foi
    mal lida, ou aquilo ja nao e a tabela, e em qualquer dos casos nao se continua a adivinhar.

    UMA TABELA INCOMPLETA NAO ENGANA A PROVA, e por isso nao e preciso recusa-la: se o OCR perdeu a
    fila dos 23%, as bases declaradas ficam a MENOS do que as linhas lidas, a prova ve uma diferenca
    e a factura fica sem prova — que e o que se quer. O perigo era o contrario, bases a mais ou
    trocadas, e disso trata a conta de cada fila (dois numeros tem de concordar) e a ancora."""
    filas = _filas(caixas)
    i = _cabeca(filas)
    if i is None:
        return None
    achado, x_taxas = {}, []
    for fila in filas[i:i + 1 + FILAS_ABAIXO]:
        r = _fila_do_resumo(fila)
        if r is None:
            continue
        taxa, base, _imposto, x_taxa = r
        if taxa in achado:
            continue
        # A MESMA COLUNA: as filas de uma tabela tem a taxa toda a mesma distancia da margem. A
        # primeira manda; uma fila com a taxa noutro sitio nao e desta tabela.
        if x_taxas and abs(x_taxa - x_taxas[0]) > 80:
            continue
        x_taxas.append(x_taxa)
        achado[taxa] = base
    return achado or None


def _todos_os_numeros(caixas):
    """Todos os valores em euros da pagina — os candidatos a TOTAL do documento."""
    return sorted({round(v, 2) for fila in _filas(caixas) for v, _x in _numeros_da_fila(fila)})


def total_impresso(caixas):
    """O total do documento, quando o resumo do IVA fecha com um numero impresso na pagina.

    E uma CONFIRMACAO A MAIS, nao uma condicao: ha facturas certas onde o total nao entra no
    enquadramento da foto (a de 591,49 EUR e uma). Quando existe e bate, sabe-se que a tabela foi
    lida inteira; quando nao aparece, as contas de cada fila continuam a valer."""
    r = resumo_do_iva(caixas)
    if not r:
        return None
    impostos = sum(b * t / 100.0 for t, b in r.items())
    esperado = round(sum(r.values()) + impostos, 2)
    for v in _todos_os_numeros(caixas):
        if abs(v - esperado) <= FOLGA_TOTAL:
            return v
    return None


def declarado_impresso(paginas_caixas):
    """O que o PAPEL declara, a partir das caixas de OCR de cada pagina.

    {"por_taxa": {taxa: base} ou None, "total": x ou None, "pagina": i, "de": ...}. Procura-se em
    todas as paginas e fica a primeira que tenha o resumo: numa factura de varias folhas ele vem so na
    ultima, e e o resumo do DOCUMENTO INTEIRO. Por isso so prova quando se fotografaram TODAS as
    paginas — senao declara mais do que se leu, a prova ve a diferenca e nao prova, que e o certo.

    O OUTRO NUMERO IMPRESSO, o "TRANSPORTE" das A4 do Recheio, nao se le aqui: ja e lido por
    linhas_factura.transportes, que trata as armadilhas dele (o OCR le o "O" como zero; "Inicio
    transporte" e uma data e nao um valor) e po-lo em cada pagina como transporte_inicio/fim."""
    fora = {"por_taxa": None, "total": None, "pagina": None, "de": None}
    for i, caixas in enumerate(paginas_caixas):
        r = resumo_do_iva(caixas)
        if r:
            fora.update(por_taxa=r, total=total_impresso(caixas), pagina=i, de="resumo do IVA")
            break
    return fora


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    import glob
    import linhas_factura as E
    fotos = [f for arg in sys.argv[1:] for f in sorted(glob.glob(arg))]
    if not fotos:
        print(__doc__)
        return 2
    for f in fotos:
        caixas = E.ocr(f)
        r = resumo_do_iva(caixas)
        print("%s" % os.path.basename(f))
        print("   resumo do IVA: %s" % (", ".join("%g%% -> %.2f" % (t, b) for t, b in sorted(r.items()))
                                        if r else "nao se leu"))
        print("   total impresso: %s" % total_impresso(caixas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
