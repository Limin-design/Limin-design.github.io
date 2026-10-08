"""Le as LINHAS de uma factura em papel a partir de fotografias. Tudo local, sem modelo de IA.

O problema: as facturas desta loja chegam em papel, de fornecedores com impressoes diferentes
(o Pao de Mafra imprime "Qtd. Un. Pr.Unitario Desc.% IVA Valor"; o Recheio imprime "Vol.
Qt./Vol. Qt.Total Preco Uni. Valor Mercadoria %IVA Preco Uni. c/IVA"). Um leitor por fornecedor
partia no primeiro fornecedor novo.

A IDEIA QUE O TORNA GERAL: nao se procuram colunas pelo cabecalho. Em cada linha procuram-se os
tres numeros que fazem QUANTIDADE x PRECO = VALOR. A conta identifica as colunas sozinha, em
qualquer layout — e prova, ao mesmo tempo, que o OCR nao trocou um algarismo. Um 8 lido como 3
no preco deixa de bater com o valor, e a linha fica marcada em vez de passar com um custo errado.

TRES PROVAS, de dentro para fora, e todas vem do proprio papel:
  1. Por linha: quantidade x preco = valor (e, no Recheio, preco x (1+IVA) = preco c/IVA).
  2. Por pagina: o "TRANSPORTE" do Recheio e o acumulado das linhas ate ali.
  3. Pela factura inteira: o QR code, com a base de cada taxa de IVA (qr_factura.py).
Se as linhas lidas nao somarem o que o QR diz, nao se propoe preco nenhum a partir delas.

O QUE LIGA OS NUMEROS A DESCRICAO: o codigo do artigo do fornecedor, a esquerda. Nas fotos do
Recheio os numeros saem meia linha desalinhados das descricoes, e entre os artigos de peixe ha
blocos de rastreabilidade (Lote, Origem, Fornecedor...) sem codigo. Juntar por altura na pagina
punha o preco do robalo na linha "Fornecedor: GAMBASTAR". Por isso cada linha de artigo e
definida pelo codigo, e as contas atribuem-se aos codigos por ORDEM — um desvio constante na foto
nao troca nada. Se o numero de codigos e de contas nao bater, a pagina fica marcada como duvidosa.

NOTA (medido nas primeiras facturas): o codigo do fornecedor NAO identifica o artigo sozinho. O
Pao de Mafra usa 1021 para "Rosquinhas comp." e para "Rosquinhas red.". A chave tem de ser
fornecedor + codigo + descricao.

Uso:
  python\\python.exe linhas_factura.py pagina1.jpg [pagina2.jpg ...]   (todas da MESMA factura,
                                                                         pela ordem das paginas)
"""
import json
import os
import re
import sys
from collections import Counter

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

# Virgula decimal, como nas facturas PT — e ponto de MILHARES nos valores grandes: o TRANSPORTE
# "1.021,27" era rejeitado e as paginas 5 e 6 da factura 72816 ficavam sem prova. O ponto so
# conta como milhares quando separa grupos de 3 algarismos e ha virgula: os codigos do Recheio
# ("117627.1") nunca passam por aqui.
# Ate 6 casas (01/10): o Primavera escreve o preco unitario com 5 ("5,00000", Quinta da Cidadoura) e com
# o limite de 4 a unica linha da factura nao era numero, nao fechava a conta e a factura nao se provava.
NUM = re.compile(r"^-?(?:\d{1,7}|\d{1,3}(?:\.\d{3})+)(?:,\d{1,6})?$")
# 1084 no Pao de Mafra, 117627.1 no Recheio — seguido de espaco ou do fim, e nada mais. Com um
# simples \b, o codigo postal "2640-202 Encarnacao" do cabecalho passava por artigo 2640 e
# empurrava todas as contas uma linha abaixo (medido na primeira factura real).
CODIGO = re.compile(r"^(\d{3,7}(?:\.\d)?)(?=\s|$)")
# O codigo com ponto do Recheio (120655.1) pode vir COLADO a descricao: o OCR leu
# "120655.1FLOCOS DE MEL". Com o ponto e um algarismo o formato e inconfundivel, por isso pode
# vir seguido de letra; o codigo sem ponto continua a exigir espaco, por causa do codigo postal.
CODIGO_PONTO = re.compile(r"^(\d{4,7}\.\d)(?=[^\d,]|$)")
# Na Poupanca (software PHC) o codigo e a descricao estao tao juntos que o OCR le "6919CERVEJA
# SAGRESTP33CL" numa caixa so: das 20 linhas da pagina 1 so 5 tinham espaco e so essas entravam.
# Colado conta como codigo se a seguir vier uma PALAVRA (duas letras e mais): o codigo postal tem
# hifen e nao passa, e uma medida no inicio de uma continuacao ("250GR", "75CL") tambem nao.
# Uma letra SOZINHA tambem e palavra: "24938V BRANCO FRISANTE" (V de vinho) perdia a linha.
CODIGO_COLADO = re.compile(r"^(\d{4,6})(?=[A-Z](?:[A-Z(]|\s))"
                           r"(?!(?:GR|KG|CL|ML|LT|LTS|UN|CX|PK|G|L|K|X)(?![A-Z]))")
TAXAS_IVA = (0.0, 6.0, 13.0, 23.0)


def _f(t):
    return float(t.replace(".", "").replace(",", "."))


# ---------------------------------------------------------------- OCR (com cache)
VERSAO_CACHE = 2       # a 2 guarda a inclinacao de cada caixa; a 1 nao, e tem de se reler


def _ocr_cru(caminho):
    """Caixas do OCR com a inclinacao de cada uma, guardadas ao lado da foto.

    O OCR demora dezenas de segundos neste i3 — a mesma foto nao se le duas vezes."""
    cache = os.path.join(os.path.dirname(caminho), ".ocr", os.path.basename(caminho) + ".json")
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(caminho):
        with open(cache, encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, dict) and dados.get("v") == VERSAO_CACHE:
            return dados["caixas"]
    from PIL import Image, ImageOps
    from rapidocr_onnxruntime import RapidOCR
    img = ImageOps.exif_transpose(Image.open(caminho)).convert("RGB")
    res, _ = RapidOCR()(img)
    caixas = []
    for box, texto, conf in (res or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        # aresta de cima da caixa (canto 0 -> canto 1): a inclinacao da linha de texto
        dx = box[1][0] - box[0][0]
        incl = (box[1][1] - box[0][1]) / dx if dx else 0.0
        caixas.append([min(xs), max(xs), sum(ys) / 4.0, max(ys) - min(ys), texto.strip(),
                       float(conf), incl])
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump({"v": VERSAO_CACHE, "caixas": caixas}, f, ensure_ascii=False)
    return caixas


def ocr(caminho):
    """Caixas de texto da foto, com a altura JA ENDIREITADA: [(x_min, y, altura, texto, conf)].

    A FOLHA VEM TORTA. Na foto do Recheio o lado direito das linhas (valor e IVA) fica mais
    alto do que o esquerdo, e os numeros da primeira linha apareciam ao nivel do "CARRO No. 2",
    uma linha acima do codigo a que pertencem. Agrupar pela altura crua misturava linhas
    vizinhas. A inclinacao mede-se nas proprias caixas de texto largas (a aresta de cima de uma
    caixa de 20 caracteres e uma regua), e a altura de cada caixa corrige-se pela sua posicao
    horizontal: y' = y - inclinacao x x."""
    cru = _ocr_cru(caminho)
    incl = _inclinacao(cru)
    # (x_min, y, altura, texto, conf, x_max) — o x_max serve para repartir numeros colados
    return [(c[0], c[2] - incl * (c[0] + c[1]) / 2.0, c[3], c[4], c[5], c[1]) for c in cru]


def _inclinacao(cru):
    """A inclinacao com que ocr() endireita as alturas. Quem precisar de voltar as coordenadas da
    FOTO (para recortar um pedaco dela) tem de a desfazer: y_na_foto = y + inclinacao x x."""
    import statistics
    largas = [c[6] for c in cru if c[1] - c[0] > 150]
    return statistics.median(largas) if largas else 0.0


# ---------------------------------------------------------------- linhas visuais
def filas(caixas):
    """Agrupa caixas em filas pela altura. Tolerancia = metade da altura tipica de uma caixa."""
    if not caixas:
        return []
    alturas = sorted(c[2] for c in caixas if c[2] > 0)
    tol = 0.5 * (alturas[len(alturas) // 2] if alturas else 20)
    fora = []
    for c in sorted(caixas, key=lambda c: c[1]):
        if fora and abs(c[1] - fora[-1]["y"]) <= tol:
            fora[-1]["caixas"].append(c)
            fora[-1]["y"] = sum(k[1] for k in fora[-1]["caixas"]) / len(fora[-1]["caixas"])
        else:
            fora.append({"y": c[1], "caixas": [c]})
    for f in fora:
        f["caixas"].sort(key=lambda c: c[0])
    return fora


# Valor e taxa de IVA COLADOS pelo OCR: no Recheio as duas colunas estao quase encostadas e
# saem como um so pedaco — "5,9523,0" e "5,95" + "23,0", "6,876,0" e "6,87" + "6,0". O valor tem
# sempre 2 casas (e dinheiro); o que sobra tem de ser uma taxa legal, senao nao se separa.
COLADO = re.compile(r"^(\d{1,7},\d{2})(\d{1,2},\d{1,2})$")


def _partes(p):
    m = COLADO.match(p)
    if m and _f(m.group(2)) in TAXAS_IVA:
        return [m.group(1), m.group(2)]
    # "0.59": o OCR trocou a virgula por ponto (1.a linha da Poupanca, e a conta perdia-se).
    # Com DUAS casas nao ha duvida — o separador de milhares leva sempre tres ("1.234").
    if PONTO_DECIMAL.match(p):
        return [p.replace(".", ",")]
    # "6,80c)" / "50,10a)": o valor colado a letra da nota de isencao (deposito e tabaco no Recheio)
    m = NOTA_COLADA.match(p)
    if m:
        return [m.group(1), m.group(2)]
    # "23,0C": o ultimo zero da taxa lido como C ou O (Carceluz)
    m = ZERO_LETRA_FIM.match(p)
    if m:
        return [m.group(1) + "0"]
    # "12,00UN": a quantidade colada a unidade (Carceluz)
    m = UNIDADE_COLADA.match(p)
    if m:
        return [m.group(1), m.group(2)]
    # "10KG": a mesma coisa SEM casas decimais. Na factura da Lusiaves de 23/09 a linha da
    # jardineira trazia "10KG" na coluna da quantidade (as outras traziam "1,957KG") e
    # desaparecia inteira: sem quantidade nao ha conta, e sem conta nao ha linha.
    m = UNIDADE_COLADA_INTEIRA.match(p)
    if m:
        return [m.group(1), m.group(2)]
    return [p]


NOTA_COLADA = re.compile(r"^(\d{1,7},\d{2})([a-z]\))$")
ZERO_LETRA_FIM = re.compile(r"^(\d{1,2},\d)[CO]$")
# "5,00UN/" — a Dulcesol (29/09) imprime uma barra a seguir a unidade, e o OCR cola-a: sem isto a
# quantidade nao era numero e a linha perdia-se inteira.
UNIDADE_COLADA = re.compile(r"^(\d{1,6},\d{2,3})(UN|KG|LT|CX|PK|MT|M2|GR)/?$")
# O GR fica DE FORA da versao sem decimais: "500GR" e quase sempre o tamanho da embalagem dentro
# do nome do produto ("FIAMBRE 500GR"), nao uma quantidade da linha.
UNIDADE_COLADA_INTEIRA = re.compile(r"^(\d{1,4})(UN|KG|LT|CX|PK|MT|M2)$")


PONTO_DECIMAL = re.compile(r"^\d{1,4}\.\d{2}$")
# Taxa impressa com percentagem ("23%", Poupanca) e motivo de isencao no lugar da taxa ("M99",
# o deposito Volta). Entram como numeros so para o IVA: nao tem virgula, logo nunca sao preco
# nem valor da linha.
TAXA_PCT = re.compile(r"^(\d{1,2})%$")
# percentagem com casas decimais ("1,00%", "10,50%"): quase sempre o desconto da linha
PCT_DECIMAL = re.compile(r"^(\d{1,2},\d{1,2})%$")
ISENCAO = re.compile(r"^M\d{2}$")
# a coluna "VOL x UNID" da Poupanca ("2x6", "1x24", "3x"): nao e descricao
VOL_UNID = re.compile(r"^\d{1,3}\s*[x×]\s*\d{0,3}$", re.I)


def _numeros(fila):
    """Numeros da fila, da esquerda para a direita: [(x, valor, texto, conf, y)].

    Cada numero guarda a altura da SUA caixa, e nao a da fila: perto do fundo do Recheio o papel
    curva e duas linhas chegam a cair na mesma fila. A altura de cada numero e o que permite
    separa-las outra vez."""
    return _tokens(fila["caixas"])


def _tokens(caixas):
    """Os numeros de um conjunto de caixas, cada um com a sua posicao: (x, valor, texto, conf, y)."""
    fora = []
    for x, y, h, texto, conf, x2 in caixas:
        partes = [q for p in texto.split() for q in _partes(p)]
        n = len(partes)
        for i, p in enumerate(partes):
            # uma caixa pode trazer varios numeros: reparte-os pela largura, pela ordem
            xi = x + (x2 - x) * (i + 0.5) / n if n > 1 else x
            if NUM.match(p):
                fora.append((xi, _f(p), p, conf, y))
            elif TAXA_PCT.match(p) and float(TAXA_PCT.match(p).group(1)) in TAXAS_IVA:
                fora.append((xi, float(TAXA_PCT.match(p).group(1)), p, conf, y))
            elif PCT_DECIMAL.match(p):
                # "1,00%": um DESCONTO (Dulcesol, 29/09: 4 x 0,68 - 1% = 2,69). So pode servir de
                # desconto ou de taxa, nunca de quantidade, preco ou valor (ver _triplos)
                fora.append((xi, _f(PCT_DECIMAL.match(p).group(1)), p, conf, y))
            elif ISENCAO.match(p):
                fora.append((xi, 0.0, p, conf, y))
    return fora


def _casas(t):
    return len(t.split(",")[1]) if "," in t else 0


def contas_da_fila(fila):
    """Todas as contas da fila — pode haver duas, quando o papel curva e junta duas linhas.

    Procura a melhor conta, retira os numeros que ela usou, e volta a procurar."""
    ns = _numeros(fila)
    fora = []
    for _ in range(3):
        c = _melhor_conta(ns)
        if not c:
            break
        usados = c.pop("_usados")
        fora.append(c)
        ns = [n for k, n in enumerate(ns) if k not in usados]
    return fora


def _valor_tres_casas(ns, l):
    """O TOTAL COM TRES CASAS, a ultima zero: "6,800". Dinheiro impresso com uma casa a mais.

    A Dulcesol imprime o total assim (medido a 29/09, duas facturas). O leitor so aceitava valores com
    duas casas — e de proposito, ver _triplos — e todas as linhas com caixa partida (0,50CX) se
    perdiam: 6,80 + 5,45 = 12,25 a 6% faltava nas duas facturas, ao centimo. As linhas com 1,00CX
    liam-se POR COINCIDENCIA, porque o preco por caixa e o total sao o mesmo numero.

    So vale na ULTIMA coluna da fila, que e onde fica o total, e so com a ultima casa a zero. Uma
    quantidade de tres casas ("6,000" do Recheio) nunca e a ultima da fila."""
    t = ns[l][2]
    return l == len(ns) - 1 and _casas(t) == 3 and t.rstrip()[-1] == "0"


def _triplos(ns, com_iva=False, tres_casas=False):
    """Todas as contas que batem na fila: [(pontos, i, j, l, d)] — quantidade i, preco j, valor l,
    desconto d. Quem escolhe entre elas e _melhor_conta (ou a coluna do valor da pagina).

    TRES_CASAS: aceita tambem o total com tres casas na ultima coluna (_valor_tres_casas). So o
    _melhor_conta o pede, e so quando a fila nao fechou de maneira nenhuma sem ele — as decisoes da
    pagina inteira (valor_com_iva, coluna_do_valor) continuam a contar so as contas de sempre.

    COM_IVA: o talao do Recheio (a fatura simplificada em rolo, a que sai na caixa) imprime
    "Valor C/IVA" — 24 x 0,13 da 3,12, e o que esta impresso e 3,53, que e 3,12 x 1,13. Nesse modo
    a conta fecha com uma taxa legal pelo meio, e a taxa fica PROVADA pela propria conta: das
    quatro taxas so uma da o valor impresso. Quem decide se a pagina e assim e `valor_com_iva`,
    olhando para a pagina toda — uma linha sozinha a bater nao chega."""
    fora = []
    pct = [n[2].endswith("%") and "," in n[2] for n in ns]      # "1,00%": so desconto ou taxa
    for i in range(len(ns)):
        if pct[i]:
            continue
        for j in range(i + 1, len(ns)):
            q, p = ns[i][1], ns[j][1]
            # o PRECO e dinheiro: tem virgula. "Vol" e "Qt./Vol." sao inteiros e nunca sao preco
            if q <= 0 or p <= 0 or "," not in ns[j][2] or pct[j]:
                continue
            for l in range(j + 1, len(ns)):
                if pct[l]:
                    continue
                v = ns[l][1]
                # o VALOR da linha e dinheiro: exactamente 2 casas. E isto que afasta a outra
                # multiplicacao do Recheio, Vol x Qt./Vol = Qt.Total, porque a Qt.Total tem 3
                # casas ("5,000"). A primeira versao apanhava-a e dizia "7 x 1 = 7,00".
                if v <= 0 or (_casas(ns[l][2]) != 2 and not (tres_casas and _valor_tres_casas(ns, l))):
                    continue
                # Folga = arredondamento do valor (meio centimo) + o do preco impresso vezes a
                # quantidade. Depende das CASAS com que o preco vem: com uma folga fixa de 1
                # centimo passava "1,000 x 1,000 = 0,99" no espinafre, e "2,000 x 2,000 = 3,99"
                # na margarina — duas quantidades tomadas por preco.
                # NUNCA MENOS DE 2 CASAS (06/10, E0008): no talao do Recheio tirado de longe o OCR leu "0,8"
                # (era "0,78", um algarismo perdido); com folga de decimas (9 x 0,05 = 0,45) "9 x 0,8 = 6,97"
                # fechava e a TIRAS DE MILHO ficava com 0,77 em vez de 0,63. Um preco de factura nunca vem
                # arredondado a menos de um centimo: com menos casas, falta um algarismo.
                tol = 0.0051 + q * 0.5 * 10 ** (-max(2, _casas(ns[j][2])))
                descontos = [0.0] + [ns[m][1] for m in range(j + 1, l) if 0 < ns[m][1] < 100]
                achou = False
                for d in descontos:
                    erro = abs(q * p * (1 - d / 100.0) - v)
                    if erro <= tol:
                        # quanto mais encostados e mais exacta a conta, melhor
                        fora.append(((j - i) + (l - j) + erro, i, j, l, d, None))
                        achou = True
                        break
                if achou or not com_iva:
                    continue
                # a taxa que faz a conta fechar. So UMA pode fechar: entre 6%, 13% e 23% a diferenca
                # no valor e muito maior do que a folga do arredondamento.
                for t in sorted(TAXAS_IVA):
                    if not t:
                        continue
                    if abs(q * p * (1 + t / 100.0) - v) <= tol * (1 + t / 100.0) + 0.0051:
                        fora.append(((j - i) + (l - j), i, j, l, 0.0, t))
                        break
    return fora


def coluna_do_valor(cadeias):
    """A coluna do TOTAL desta pagina e a ULTIMA da linha? Decide-se pela pagina inteira e nao linha
    a linha: se em quase todas as linhas a conta pode acabar no ultimo numero, entao e ali a coluna
    do valor. Medido nas 24 paginas guardadas: Gelpeixe, Batista, Pao de Mafra e a Poupanca do
    WhatsApp dao 100%; o Recheio e a Poupanca do telemovel dao 0-18%, porque tem colunas DEPOIS do
    valor (preco c/IVA) — ai nao se aplica nada e fica tudo como estava."""
    com = podem = 0
    for ns in cadeias:
        ts = _triplos(ns)
        if not ts:
            continue
        com += 1
        podem += any(t[3] == len(ns) - 1 for t in ts)
    return "ultima" if com >= 3 and podem >= 0.9 * com else None


def _taxa_da_linha(ns, i, j, l):
    """Qual dos numeros da linha e a TAXA DE IVA (indice), ou None. i/j/l sao quantidade/preco/valor.

    PREFERE uma taxa diferente de zero: no Pao de Mafra a coluna do desconto (0,00) vem antes da do
    IVA (6,00), e a primeira versao apanhava o desconto e dizia IVA 0%. Zero so fica quando e o unico
    candidato. A prova final da taxa e o QR, que tem a base por taxa.

    Isto serve os DOIS leitores (o normal e o generico). Ate 23/09 o generico tinha uma regra so
    dele, que exigia virgula ou "%" e so olhava para a direita do valor — e na factura da Lusiaves,
    onde a taxa vem impressa "6"/"23" seca e ANTES da coluna do valor, todas as linhas saiam sem IVA."""
    candidatos = [k for k in range(j + 1, len(ns))
                  if k != l and ns[k][1] in TAXAS_IVA
                  and ("," in ns[k][2] or TAXA_PCT.match(ns[k][2]) or ISENCAO.match(ns[k][2]))]
    # TAXA SEM CASAS DECIMAIS ("6", "23" na Gelpeixe e na Lusiaves), as vezes impressa ANTES do preco
    # liquido, por isso tambem se procura a esquerda do preco. So conta se houver UMA taxa legal na
    # linha: dois numeros diferentes que sejam taxas seria adivinhar qual.
    inteiros = [k for k in range(i + 1, len(ns))
                if k not in (j, l) and "," not in ns[k][2] and ns[k][1] in TAXAS_IVA and ns[k][1] > 0]
    if len({ns[k][1] for k in inteiros}) != 1:
        inteiros = []
    # As duas listas juntas, e so depois a preferencia pelo nao-zero. Na Lusiaves as colunas de
    # desconto trazem "0,00" e nenhuma taxa com virgula: olhando so para a primeira lista, o zero
    # ganhava e todas as linhas ficavam com IVA 0%. Quem traz virgula ou "%" continua a ir primeiro.
    candidatos = candidatos + inteiros
    # "6,00%" E QUASE SEMPRE O DESCONTO (PCT_DECIMAL, Dulcesol 29/09): so serve de taxa quando a linha nao
    # tiver outra. Auditoria 29/09, M4: "10 | 1,50 | 6,00% | 14,10 | 23" dava IVA 6 — o desconto — e a
    # taxa impressa, 23, perdia; num artigo novo criado dessa linha o IVA vinha pre-preenchido a 6%.
    pct = [k for k in candidatos if PCT_DECIMAL.match(ns[k][2])]
    if len(pct) < len(candidatos):
        candidatos = [k for k in candidatos if k not in pct]
    nao_zero = [k for k in candidatos if ns[k][1] > 0]
    return nao_zero[0] if nao_zero else (candidatos[0] if candidatos else None)


def valor_com_iva(cadeias):
    """Esta pagina imprime o VALOR COM IVA? Decide-se pela pagina inteira, nunca linha a linha.

    A fatura simplificada do Recheio (o rolo da caixa) tem a coluna "Valor C/IVA": 24 x 0,13 = 3,12
    e o impresso e 3,53. Ate 23/09 essas linhas ficavam TODAS "sem conta" — a fatura de 591,49 EUR
    de hoje deu zero linhas, e a de 66,51 EUR deu uma so (o deposito, que e a unica isenta e por
    isso a unica onde as duas contas sao a mesma).

    So se aceita se a pagina inteira concordar: pelo menos 3 filas onde a conta SO fecha com IVA, e
    essas terem de ser a maioria das que fecham de alguma maneira. Uma linha sozinha a bater com
    23% pelo meio e coincidencia; dez linhas seguidas nao sao. A prova final continua a ser o
    resumo do IVA da propria factura (e o QR, quando o ha).

    Devolve None quando a pagina NAO CHEGA PARA DECIDIR — poucas filas fecham de uma maneira ou da
    outra. E ai, e so ai, que a memoria do formato do fornecedor tem uma palavra a dizer. Sem esta
    distincao a memoria mandava contra a evidencia da propria pagina: a 24/09 o formato aprendido
    da factura A4 do Recheio foi imposto ao talao de caixa do mesmo Recheio, que traz o valor COM
    IVA, e a leitura passou de 39 linhas para zero."""
    so_com = so_sem = 0
    for ns in cadeias:
        sem = bool(_triplos(ns))
        com = bool([t for t in _triplos(ns, com_iva=True) if t[5]])
        so_sem += sem
        so_com += com and not sem
    if so_com >= 3 and so_com > so_sem:
        return True
    if so_sem >= 3 and so_com == 0:
        return False
    return None


def _melhor_conta(ns, coluna_valor=None, com_iva=False):
    """Procura quantidade x preco (x (1 - desconto)) = valor. None se nenhuma combinacao bater.

    Entre varias combinacoes validas escolhe a de quantidade mais proxima do preco: no Recheio
    '5 1 5,000 1,19 5,95' tanto o Vol (5) como a Qt.Total (5,000) batem, mas no molho bechamel
    '1 6 6,000 1,19 7,14' so a Qt.Total bate — e a coluna certa e sempre a encostada ao preco.

    COLUNA_VALOR ("ultima"): a pagina ja disse onde esta a coluna do total (ver coluna_do_valor) e
    so contam as contas que acabam la. Sem isto, na Gelpeixe "8,00 1,00 2,88 23 2,65 2,65 21,20"
    dava 1 x 2,65 = 2,65 (as colunas Preco liq. e Preco UN sao iguais) em vez de 8 x 2,65 = 21,20."""
    todos = _triplos(ns, com_iva)
    if not todos:
        # SO QUANDO NADA FECHOU: o total com tres casas na ultima coluna (Dulcesol, "6,800").
        # "5,00UN 0,50CX 1,360 13,60 6% 6,800" fecha de duas maneiras — 5 unidades a 1,36 e meia caixa
        # a 13,60 — com o mesmo total. Fica a da MAIOR quantidade, que e a unidade que a loja vende; a
        # outra e a mesma linha contada em caixas, nao um segundo preco para escolher.
        extra = _triplos(ns, com_iva, tres_casas=True)
        maior = {}
        for t in extra:
            if t[3] not in maior or ns[t[1]][1] > ns[maior[t[3]][1]][1]:
                maior[t[3]] = t
        todos = list(maior.values())
    escolha = [t for t in todos if t[3] == len(ns) - 1] if coluna_valor == "ultima" else todos
    if not escolha:
        escolha = todos
    if not escolha:
        return None
    validas = [(t[3], ns[t[2]][1], _casas(ns[t[2]][2])) for t in todos]
    _, i, j, l, d, taxa_da_conta = min(escolha)
    q, p, v = ns[i][1], ns[j][1], ns[l][1]
    # DOIS PRECOS PARA O MESMO VALOR. Na Gelpeixe o choco traz "10,00 1,00 8,00 8.10/KG 6 8.10
    # 6,48 64.80": 8 kg x 8,10 e 10 caixas x 6,48 dao ambos 64,80. O custo confirmado era 6,48 e
    # a leitura escolhia 8,10 — uma subida falsa de 25%. Nao se adivinha: a linha leva os dois
    # precos e a proposta fica em "nao mexer" ate alguem olhar.
    # So conta um preco a serio: com 2 casas (um "5,000" de 3 casas e quantidade — paio York no
    # Recheio) e diferente em mais de 2 centimos e 2% (espinafre 0,99 contra 1,00 nao e duvida).
    # PRECO POR UNIDADE IMPRESSO: a coluna logo antes do total ("Preco UN" da Gelpeixe) da o MESMO
    # total com outra quantidade — a mesma linha vista a unidade. Nao e ambiguidade nenhuma: os custos
    # confirmados da loja dizem que o choco custa 6,48 a caixa de 800g (e nao 8,10 o kg) e as tiras
    # 3,85 o pacote. Fica ao lado do preco da linha; quem escolhe e a proposta, pelo custo da loja.
    unidade = next((ns[t[2]][1] for t in todos if t[3] == l and t[2] == l - 1 and t[2] != j), None)
    alternativas = sorted({round(pp, 2) for ll, pp, casas in validas
                           if ll == l and casas == 2 and abs(pp - p) > 0.02 and abs(pp - p) > 0.02 * p
                           and (unidade is None or abs(pp - unidade) > 0.005)})
    k_iva = _taxa_da_linha(ns, i, j, l)
    iva = ns[k_iva][1] if k_iva is not None else None
    usados = {i, j, l} | ({k_iva} if k_iva is not None else set())
    impresso = None
    if taxa_da_conta:
        # A conta so fechou com IVA pelo meio (talao do Recheio, coluna "Valor C/IVA"). A taxa fica
        # provada pela propria conta — e mais forte do que a ler da coluna, que pode nem estar lida.
        # O VALOR guardado e sempre SEM IVA, como em todas as outras facturas, para que as somas por
        # taxa continuem a poder ser comparadas com as bases do QR. O impresso vai ao lado.
        impresso, v = v, round(q * p, 2)
        iva = taxa_da_conta
    com_iva_ok = None
    if impresso is not None:
        com_iva_ok = True
    # prova extra do Recheio: preco x (1 + IVA) = preco c/IVA, na coluna a seguir
    elif iva is not None:
        alvo = p * (1 + iva / 100.0)
        for k in range(l + 1, len(ns)):
            if k not in usados and abs(ns[k][1] - alvo) <= 0.011:
                com_iva_ok = True
                usados.add(k)
                break
    # NUMEROS QUE SOBRAM na linha (lote, referencia, validade sem barras): nao servem para a conta,
    # mas o LOTE tambem esta impresso na embalagem — e isso liga a foto do produto a linha certa sem
    # adivinhar nada (GENIALIS 17/09: "L.2643103" no saco e 2643103 na coluna Lote da factura).
    livres = sorted({ns[k][2] for k in range(len(ns)) if k not in usados and "," not in ns[k][2]
                     and len(re.sub(r"\D", "", ns[k][2])) >= 4})
    return {"quantidade": q, "preco": p, "desconto": d, "valor": v, "iva": iva,
            "valor_impresso_com_iva": impresso,
            # onde estavam, nesta pagina, os numeros desta conta. As linhas que fecham ensinam
            # assim as colunas as linhas que nao fecham (ver _segunda_vista).
            "x_colunas": (ns[i][0], ns[j][0], ns[l][0]),
            # e a ALTURA de cada uma: cada coluna tem o seu desvio (no Recheio o valor sai impresso
            # um terco de linha acima da quantidade), e as linhas que fecham ensinam-no (pela_grelha)
            "y_colunas": (ns[i][4], ns[j][4], ns[l][4]),
            "prova_iva": com_iva_ok, "conf_min": min(ns[i][3], ns[j][3], ns[l][3]),
            "precos_alternativos": alternativas, "preco_unidade": unidade, "outros_numeros": livres,
            # a altura da CONTA e a media das caixas que a formam, nao a da fila
            "y": (ns[i][4] + ns[j][4] + ns[l][4]) / 3.0, "_usados": usados}


_leitor_celula = None

# Realce opcional aplicado a CADA CELULA antes de a reler (segunda vista). E um sitio diferente do
# detector: aqui e o reconhecedor a olhar para um numero sozinho, e um talao termico e cinzento
# sobre cinzento. Serve para medir se dar contraste ajuda a ler algarismos esborratados — ver
# ferramentas\ensaio_contraste.py. None = nao mexer na imagem, que e o que esta em producao ate a
# medicao dizer o contrario.
REALCE_CELULA = None


def _celulas(faixa, minimo=4):
    """Onde comeca e acaba cada coluna de numeros dentro da faixa, pelos vazios de tinta.

    MINIMO e o maior vazio que ainda se atravessa sem cortar. Tem de ser MENOR do que o espaco
    entre colunas e maior do que o espaco entre algarismos: com 16 px, "10,000" e "0,44" sairam
    colados num so pedaco ("100000,44") e nao havia conta nenhuma."""
    import numpy as np
    a = np.asarray(faixa.convert("L"), dtype=float)
    fundo = np.percentile(a, 80)
    cheio = (a < fundo - 25).sum(axis=0) > 0
    fora, i = [], 0
    while i < len(cheio):
        if not cheio[i]:
            i += 1
            continue
        j = i
        while j < len(cheio) and (cheio[j] or cheio[j:j + minimo].any()):
            j += 1
        if j - i >= 18:
            fora.append((max(0, i - 4), min(len(cheio), j + 4)))
        i = j
    return fora


def colunas_das_linhas(linhas, folga=0.18):
    """As faixas de x das colunas quantidade/preco/valor, medidas nas linhas QUE JA FECHARAM.

    Uma linha que fecha a conta provou onde estao as suas tres colunas. Juntando as que fecharam,
    a pagina diz onde procurar as que nao fecharam — sem adivinhar formato nenhum e sem depender
    de saber o fornecedor."""
    import statistics as _st
    colunas = []
    for i in range(3):
        xs = [l["x_colunas"][i] for l in linhas if l.get("x_colunas")]
        if len(xs) < 3:
            return None
        meio = _st.median(xs)
        largo = max(24.0, (max(xs) - min(xs)) or 24.0)
        colunas.append((meio - largo * (0.5 + folga), meio + largo * (0.5 + folga)))
    return colunas if colunas[0][1] < colunas[2][1] else None


def completa_colunas(caminho, codigos, area, colunas, passo, desvio, largura):
    """ENCHE OS BURACOS DAS COLUNAS: para cada codigo sem numero numa coluna, le essa celula.

    Medido a 24/09: quando as tres colunas tem o MESMO numero de numeros, emparelha-las pela ordem
    acerta TODAS (14 de 14, 19 de 19, 8 de 8 em tres paginas). Quando tem buracos — a factura
    dificil tem 58 quantidades, 44 precos e 46 valores — nenhum metodo de emparelhamento safa,
    porque os numeros que faltam nao existem para ser emparelhados.

    Entao o trabalho nao e emparelhar melhor, e ENCHER. A segunda vista ja sabia recortar uma
    celula e le-la; faltava corre-la celula a celula em vez de so nas filas perdidas por inteiro.
    Nao inventa nada: le o que esta impresso naquele sitio, e o que nao se ler fica por ler.

    Devolve os numeros novos, no mesmo formato de _tokens, para juntar a area."""
    global _leitor_celula
    if not colunas or not codigos:
        return []
    try:
        from PIL import Image, ImageOps
        from rapidocr_onnxruntime import RapidOCR
    except Exception:                                    # noqa: BLE001
        return []
    if _leitor_celula is None:
        _leitor_celula = RapidOCR()
    img = ImageOps.exif_transpose(Image.open(caminho)).convert("RGB")
    incl = _inclinacao(_ocr_cru(caminho))
    alto = max(12, int(0.45 * passo))
    novos = []
    for k in codigos:
        alvo = k["y"] + desvio
        for x_de, x_ate in colunas:
            if any(x_de <= t[0] <= x_ate and abs(t[4] - alvo) <= 0.55 * passo for t in area):
                continue                                 # essa celula ja tem numero, nao se mexe
            cy = alvo + incl * ((x_de + x_ate) / 2.0)
            cel = img.crop((max(0, int(x_de) - 12), int(cy) - int(alto * 1.35),
                            min(int(largura), int(x_ate) + 12), int(cy) + int(alto * 1.35)))
            try:
                r, _ = _leitor_celula(REALCE_CELULA(cel) if REALCE_CELULA else cel,
                                      use_det=False, use_cls=False, use_rec=True)
            except Exception:                            # noqa: BLE001
                continue
            texto = (r[0][0] if r else "").strip().replace(" ", "").replace("，", ",").replace(".", ",")
            for p in _partes(texto):
                if NUM.fullmatch(p):
                    novos.append(((x_de + x_ate) / 2.0, _f(p), p,
                                  float(r[0][1]) if r else 0.0, alvo))
                    break                                # um numero por celula
    return novos


def _pela_grelha_por_coluna(sem_conta, area, colunas, passo, coluna, com_iva, linhas):
    """A grelha com o DESVIO DE CADA COLUNA aprendido nas linhas vizinhas que ja fecharam.

    Tres regras, e cada uma veio de um caso medido a 25/09:

      1. O DESVIO E LOCAL. Para cada codigo perdido usam-se as linhas fechadas mais perto dele em
         altura, e nao a mediana da pagina: o papel curva, e na factura 152114 o desvio da mesma
         coluna vai de -50 a +25 px conforme a zona da folha.
      2. A JANELA E APERTADA (um terco de linha a volta de onde a coluna diz que o numero esta). Com a
         janela larga, na factura de 29/09 apareciam contas "que fecham" feitas com numeros de duas
         linhas abaixo — era inventar.
      3. SO UMA CONTA POSSIVEL, E CADA NUMERO SO SERVE UMA VEZ. Na 152114 dois codigos diferentes
         agarravam o mesmo 7,76. Se um codigo tem duas contas diferentes a fechar, ou se dois codigos
         querem o mesmo numero, nao se escolhe: fica por ler, e a prova e a cloud tratam dele.

    E no fim, as linhas daqui continuam a passar pelo juiz de sempre (propoe._so_se_ajudar): so ficam
    se aproximarem as somas do que a factura declara."""
    ref = [(l["y_codigo"], [yc - l["y_codigo"] for yc in l["y_colunas"]])
           for l in linhas if l.get("y_colunas") and l.get("y_codigo") is not None]
    if len(ref) < 2:
        return []                    # nao ha vizinhos que ensinem: fica so o metodo de sempre
    chave = lambda t: (round(t[0], 1), round(t[4], 1))
    # os numeros que ja pertencem a uma linha fechada nao podem servir outra
    usados = {(round(x, 1), round(y, 1)) for l in linhas if l.get("y_colunas")
              for x, y in zip(l["x_colunas"], l["y_colunas"])}
    janela = passo / 3.0
    propostas = []
    for k in sem_conta:
        y0 = k.get("fim_y") or k["y"]
        viz = sorted(ref, key=lambda r: abs(r[0] - y0))[:4]
        esperado = [y0 + sum(r[1][i] for r in viz) / len(viz) for i in range(3)]
        cand = []
        for i, (x_de, x_ate) in enumerate(colunas):
            c = [t for t in area if x_de <= t[0] <= x_ate and abs(t[4] - esperado[i]) <= janela
                 and chave(t) not in usados]
            cand.append(sorted(c, key=lambda t: abs(t[4] - esperado[i]))[:4])
        if not all(cand):
            continue
        depois = sorted((t for t in area if t[0] > colunas[-1][1] and abs(t[4] - esperado[2]) <= janela),
                        key=lambda t: t[0])[:2]
        fecham = {}
        for q in cand[0]:
            for p in cand[1]:
                for v in cand[2]:
                    c = _melhor_conta(sorted([q, p, v] + depois, key=lambda t: t[0]), coluna, com_iva)
                    if not c:
                        continue
                    # a conta tem de ser FEITA COM ESTES TRES, e nao com outra combinacao dos numeros
                    # dados (o _melhor_conta pode escolher a taxa como quantidade)
                    v_lido = c.get("valor_impresso_com_iva") or c["valor"]
                    if (abs(c["quantidade"] - q[1]) > 1e-6 or abs(c["preco"] - p[1]) > 1e-6
                            or abs(v_lido - v[1]) > 1e-6):
                        continue
                    fecham.setdefault((q[1], p[1], v[1]), (c, {chave(q), chave(p), chave(v)}))
        if len(fecham) == 1:
            c, toks = next(iter(fecham.values()))
            propostas.append((k, c, toks, esperado))
    # um numero pedido por dois codigos: nenhum dos dois fica com ele
    conta = Counter(t for _k, _c, toks, _e in propostas for t in toks)
    fora = []
    for k, c, toks, esperado in propostas:
        if any(conta[t] > 1 for t in toks):
            continue
        c.pop("_usados", None)
        c["y"] = sum(esperado) / 3.0
        c["da_grelha"] = True
        c["grelha_por_coluna"] = True
        fora.append((k, c))
    return fora


def pela_grelha(sem_conta, area, colunas, passo, desvio, coluna, com_iva, linhas=None):
    """A TABELA, montada a partir dos numeros QUE JA FORAM LIDOS: linha = codigo, coluna = faixa de x.

    Porque e preciso, e porque nao chega encadear: na factura dificil a linha do QUEIJO MOZZ tem os
    tres numeros lidos — 5,000 / 1,42 / 7,53, e 5 x 1,42 x 1,06 da 7,53 ao centimo — mas espalhados
    por 34 px de altura, quase uma linha inteira, e nem por ordem. O encadeamento (_cadeias) liga
    cada numero ao vizinho da direita com 19 px de tolerancia, por isso parte a fila em duas e a
    cadeia que fecha acaba a usar a quantidade da linha SEGUINTE.

    Aqui nao se encadeia: para cada codigo procura-se UM numero em cada coluna, o mais perto em
    altura, e a conta e que diz se o conjunto serve. Quem manda continua a ser a aritmetica — se os
    numeros forem de linhas diferentes, a conta nao fecha e nao sai linha nenhuma.

    CADA COLUNA TEM O SEU DESVIO (Pedro, 25/09: "analisar coluna a coluna"). Medido nas linhas que
    fecharam da pagina 2 do Recheio 73442: a quantidade sai a altura do codigo, o preco um decimo de
    linha acima, e o VALOR um terco de linha acima — e o papel curva, por isso mais ainda nas filas
    de baixo. Com um desvio so para a pagina toda, o numero "mais perto" na coluna do valor era o da
    linha de cima, a conta nao fechava, e tres linhas perdiam-se com os numeros certos todos la
    (2 x 6,79 = 13,58; 3 x 1,44 = 4,32; 8 x 0,32 = 2,56). Quando ha `linhas` fechadas que o digam,
    ver `_pela_grelha_por_coluna`."""
    if not colunas:
        return []
    if linhas:
        # PRIMEIRO COLUNA A COLUNA, depois o de sempre para o que sobrar. A leitura por coluna nao
        # substitui a antiga: na 152114 a coluna do PRECO esta meia linha abaixo das outras numa zona
        # da folha, os vizinhos nao o previam, e a janela apertada perdia o PESSEGO (2 x 2,19 = 4,38),
        # que o metodo antigo apanhava. Os numeros que a primeira usou ja nao servem a segunda.
        primeiro = _pela_grelha_por_coluna(sem_conta, area, colunas, passo, coluna, com_iva, linhas)
        feitos = {id(k) for k, _c in primeiro}
        gastos = {(round(x, 1), round(y, 1)) for _k, c in primeiro
                  for x, y in zip(c.get("x_colunas") or (), c.get("y_colunas") or ())}
        resto = [t for t in area if (round(t[0], 1), round(t[4], 1)) not in gastos]
        return primeiro + pela_grelha([k for k in sem_conta if id(k) not in feitos], resto, colunas,
                                      passo, desvio, coluna, com_iva)
    fora = []
    for k in sem_conta:
        alvo = (k.get("fim_y") or k["y"]) + desvio
        escolhidos = []
        for x_de, x_ate in colunas:
            na_coluna = [t for t in area if x_de <= t[0] <= x_ate and abs(t[4] - alvo) <= 0.9 * passo]
            if na_coluna:
                escolhidos.append(min(na_coluna, key=lambda t: abs(t[4] - alvo)))
        if len(escolhidos) < 3:
            continue
        # e o que vem DEPOIS da coluna do valor, que e onde mora a taxa de IVA. Sem isto as linhas
        # montadas pela grelha saiam sem taxa, e uma linha sem taxa nao tem balde nas somas — a
        # prova deixava de as poder contar e a factura afastava-se em vez de se aproximar.
        depois = sorted((t for t in area
                         if t[0] > colunas[-1][1] and abs(t[4] - alvo) <= 0.9 * passo),
                        key=lambda t: t[0])[:2]
        escolhidos += depois
        escolhidos.sort(key=lambda t: t[0])
        c = _melhor_conta(escolhidos, coluna, com_iva)
        if c:
            c.pop("_usados", None)
            c["y"] = alvo
            c["da_grelha"] = True
            fora.append((k, c))
    return fora


def _segunda_vista(caminho, sem_conta, desvio, passo, largura, coluna, com_iva, colunas=None):
    """Volta a olhar SO para as linhas que ficaram sem conta, e so para a faixa dos numeros.

    PORQUE E PRECISO: o detector do OCR parte os numeros na virgula e come algarismos — no talao do
    Recheio de 23/09 (66,51 EUR) quatro linhas ficaram sem conta por lhes faltar UM numero cada:
    "5,38" saiu "38", "3,34" e "4,68" nao sairam de todo, "0,44" desapareceu. O reconhecedor, esse,
    le bem uma imagem que ja seja uma linha so — o que falha e a deteccao, nao a leitura.

    ISTO NAO INVENTA NADA. Podia-se calcular o numero que falta a partir dos outros dois (4 x 1,19
    x 1,13 da 5,38 ao centimo) e seria sempre a resposta certa; nao se faz, porque seria escrever um
    numero que ninguem leu. Aqui recorta-se o sitio onde ele esta impresso e le-se outra vez. Se a
    releitura nao der, ou se a conta nao fechar, a linha fica sem conta como estava.

    A altura da faixa vem do DESVIO que a propria pagina ja mediu entre cada codigo e os seus
    numeros, para nao ir buscar algarismos a linha de cima ou de baixo."""
    global _leitor_celula
    try:
        from PIL import Image, ImageOps
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return []
    if _leitor_celula is None:
        _leitor_celula = RapidOCR()
    img = ImageOps.exif_transpose(Image.open(caminho)).convert("RGB")
    incl = _inclinacao(_ocr_cru(caminho))
    alto = max(12, int(0.45 * passo))
    fora = []
    for k in sem_conta:
        x0 = int(k.get("fim_x") or 0) + 4        # rente a descricao: com 15 cortava-se o 1.o algarismo
        if x0 >= largura - 60:
            continue
        alvo = (k.get("fim_y") or k["y"]) + desvio       # altura ja endireitada, como as outras contas
        # as alturas vem de ocr(), ja endireitadas; para RECORTAR A FOTO ha que as desfazer
        def na_foto(x, y=alvo):
            return y + incl * x
        if colunas:
            # AS COLUNAS VEM DAS LINHAS QUE FECHARAM NESTA MESMA PAGINA. E a regua mais fiavel que
            # ha: nao e um palpite sobre o formato, e onde os numeros estiveram nas linhas que se
            # provaram a si proprias. Recorta-se cada coluna em vez de adivinhar os cortes pelo
            # branco do papel, que num talao apertado ora cola duas colunas ora parte um numero.
            ns = []
            for x_de, x_ate in colunas:
                cy = na_foto((x_de + x_ate) / 2.0)
                cel = img.crop((max(0, int(x_de) - 12), int(cy) - int(alto * 1.35),
                                min(int(largura), int(x_ate) + 12), int(cy) + int(alto * 1.35)))
                try:
                    r, _ = _leitor_celula(REALCE_CELULA(cel) if REALCE_CELULA else cel,
                                          use_det=False, use_cls=False, use_rec=True)
                except Exception:                    # noqa: BLE001
                    continue
                texto = (r[0][0] if r else "").strip().replace(" ", "").replace("，", ",").replace(".", ",")
                for p in _partes(texto):
                    if NUM.fullmatch(p):
                        ns.append((x_de, _f(p), p, float(r[0][1]) if r else 0.0, alvo))
            if len(ns) >= 3:
                c = _melhor_conta(ns, coluna, com_iva)
                if c:
                    c.pop("_usados", None)
                    c["y"] = alvo
                    c["segunda_vista"] = True
                    fora.append((k, c))
                    continue
        meio = int(na_foto((x0 + largura) / 2.0))
        faixa = img.crop((x0, meio - alto, int(largura), meio + alto))
        # VARIAS MANEIRAS DE CORTAR AS COLUNAS, e fica a que fecha a conta. Nenhum valor unico serve
        # para todas as linhas: com vazios de 4 px liam-se duas linhas e perdia-se outra, com 6 px
        # era ao contrario. Isto nao e adivinhar — sao leituras diferentes dos MESMOS pixeis, e quem
        # aceita continua a ser a conta, que e uma prova independente.
        for vazio, folga in ((4, 1.35), (6, 1.35), (9, 1.35), (4, 1.0), (6, 1.0)):
            ns = []
            for a, b in _celulas(faixa, vazio):
                if b - a < 12:
                    continue
                # a celula le-se com mais folga em cima e em baixo do que a banda usada para a
                # cortar: apertada, o reconhecedor perde a virgula decimal ("5,38" saia "538")
                cy = na_foto(x0 + (a + b) / 2.0)
                meia = max(10, int(alto * folga))
                cel = img.crop((x0 + a, int(cy) - meia, x0 + b, int(cy) + meia))
                try:
                    r, _ = _leitor_celula(REALCE_CELULA(cel) if REALCE_CELULA else cel,
                                          use_det=False, use_cls=False, use_rec=True)
                except Exception:
                    continue
                texto = (r[0][0] if r else "").strip().replace(" ", "").replace("，", ",")
                # o reconhecedor escreve a virgula decimal como ponto ("0.44"). Aqui le-se UMA celula
                # de uma coluna de numeros, e nestas facturas o separador de milhares nao e impresso.
                # Enganar-se nisto nao inventa nada: um numero mal pontuado nao fecha conta nenhuma e
                # a linha fica por ligar, como estava.
                texto = texto.replace(".", ",")
                conf = float(r[0][1]) if r else 0.0
                for p in _partes(texto):
                    if not NUM.fullmatch(p):
                        continue                   # so os numeros contam
                    ns.append((x0 + a, _f(p), p, conf, alvo))
            if len(ns) < 3:
                continue
            c = _melhor_conta(ns, coluna, com_iva)
            if c:
                c.pop("_usados", None)
                c["y"] = alvo
                c["segunda_vista"] = True
                fora.append((k, c))
                break
    return fora


def _e_codigo(texto):
    return CODIGO.match(texto) or CODIGO_PONTO.match(texto) or CODIGO_COLADO.match(texto)


def _codigos_da_fila(fila, largura):
    """Codigos de artigo na zona esquerda da fila, cada um com a descricao e a SUA altura.

    Pode haver dois: quando o papel curva, duas linhas caem na mesma fila (medido no Recheio:
    "AIPO CORTADO 500G RCH" e "251704.0 FRANGO" juntaram-se e o frango perdia-se).

    A caixa de codigo nao tem de ser a primeira da fila. Na foto do Pao de Mafra ha outro papel
    por baixo da factura, e o texto "LOGINSUL" a beira da imagem ficava como primeira caixa da
    linha do artigo 1099, que se perdia."""
    fora = []
    cx = fila["caixas"]
    for idx, (x, y, h, texto, conf, x2) in enumerate(cx):
        if x > 0.30 * largura:
            break
        m = _e_codigo(texto)
        if not m:
            continue
        resto = texto[m.end():].strip()
        # a descricao pode vir na mesma caixa (Recheio) ou nas seguintes (Pao de Mafra), e
        # acaba no primeiro numero ou no proximo codigo
        desc = [resto] if resto else []
        fim_x, fim_y = x2, y
        for c in cx[idx + 1:]:
            t = c[3]
            if _e_codigo(t) and c[0] <= 0.30 * largura:
                break
            primeira = t.split()[0] if t.split() else ""
            if NUM.match(primeira) or VOL_UNID.match(t.strip()):
                break
            # a QUANTIDADE COLADA A UNIDADE ("5,00UN", "0,50CX") ja e a coluna seguinte, nao o nome: sem
            # isto a Dulcesol ficava com "PaodeForma ... 5,00UN 0,50CX" na descricao, que e o que se
            # compara com os nomes da loja. So com casas decimais: "10KG" pode ser parte do nome.
            if UNIDADE_COLADA.match(primeira):
                break
            # as ETIQUETAS do peixe e da carne ("Lote:", "Origem:", "Fornecedor:", "Nome Cientifico:")
            # vem por baixo da linha e nao fazem parte do nome: "DOURADA 300/400 TURQUIA Fornecedor"
            if ETIQUETA_POR_BAIXO.match(t.strip()) or t.strip().startswith((":", "：", "..")):
                break
            desc.append(t)
            fim_x, fim_y = c[5], c[1]
        fora.append({"codigo": m.group(1), "descricao": _limpa(" ".join(d for d in desc if d)),
                     "y": y, "fim_x": fim_x, "fim_y": fim_y})
    return fora


ZERO_LETRA = re.compile(r"(?<![0-9])0(?=[A-Za-z])|(?<=[A-Za-z])0(?![0-9])")


DATA_NA_DESCRICAO = re.compile(r"(?<!\d)\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}(?!\d)")


def _limpa(desc):
    """Um zero rodeado de letras e um O. A fonte do Recheio faz o OCR ler "SALMA0", "0STRA",
    "ROBAL0", "TUB0" — e para ligar a descricao ao artigo da loja o nome tem de estar certo.
    Um zero com um algarismo ao lado fica zero: "4X200GR" e "30/50" nao mudam.

    A DATA DE VALIDADE tambem sai: e uma coluna da factura, nao faz parte do nome do produto — sem
    isto o artigo novo dos marshmallows chamava-se "GOMAS 31/01/2028" (GENIALIS, 17/09)."""
    desc = DATA_NA_DESCRICAO.sub(" ", desc or "")
    return re.sub(r"\s{2,}", " ", ZERO_LETRA.sub("O", desc)).strip()


def _y_cabecalho(fs):
    """Altura do cabecalho da tabela de linhas. Os codigos de artigo so existem abaixo dele —
    acima estao a morada, os NIF e as datas, que tambem comecam por algarismos."""
    for f in fs:
        junto = " ".join(c[3] for c in f["caixas"]).lower()
        # "CARRO | PRODUTO" e o cabecalho da Poupanca (PHC); as duas palavras juntas so ali
        if "descri" in junto or ("produto" in junto and "carro" in junto):
            return f["y"]
    return None


def transportes(fs):
    """Os 'TRANSPORTE' impressos na pagina, por ordem de altura: [(y, valor)].

    Numa pagina do meio ha DOIS: o de cima traz o acumulado da pagina anterior e o de baixo leva
    o desta. A primeira versao lia so o primeiro, e na pagina 2 comparava as linhas com o
    acumulado da pagina 1. Com os dois, cada pagina confere-se sozinha: fim - inicio."""
    caixas = [c for f in fs for c in f["caixas"]]
    alturas = sorted(c[2] for c in caixas if c[2] > 0)
    tol = 1.5 * (alturas[len(alturas) // 2] if alturas else 20)
    tokens = _tokens(caixas)
    fora = []
    for c in caixas:
        # a fonte do Recheio faz o OCR ler O como zero ("SALMA0", "0STRA")
        if "TRANSPORTE" not in c[3].upper().replace("0", "O"):
            continue
        # "Inicio transporte: 2026-09-15" (Poupanca) e a data da carga, nao um valor transportado
        if "INICIO" in c[3].upper() or "INÍCIO" in c[3].upper():
            continue
        # O NUMERO MAIS PROXIMO A DIREITA — nao o da mesma fila. No fim da pagina 2 do Recheio
        # "296,73" ficou 18 pixeis acima de "TRANSPORTE" (os numeros saem impressos acima do
        # texto, como nas linhas), caiu noutra fila, e a pagina ficava por conferir.
        cand = [(abs(t[4] - c[1]), t[1]) for t in tokens if t[0] > c[0] and abs(t[4] - c[1]) <= tol]
        if cand:
            fora.append((c[1], min(cand)[1]))
    return sorted(fora)


def _cadeias(tokens, passo, largura):
    """As LINHAS DE NUMEROS da pagina, construidas sem olhar para os codigos.

    Cada numero liga-se ao vizinho mais proximo a direita (salto curto, quase a mesma altura), e
    cada numero so tem um vizinho de cada lado. As ligacoes aceitam-se da mais certa para a
    menos certa. O que sai sao as linhas impressas, inteiras, mesmo com a folha curvada — cada
    salto e uma coluna, e numa coluna a curvatura e de poucos pixeis."""
    salto_max = 0.22 * largura
    tol = 0.45 * passo
    arestas = []
    for a, ta in enumerate(tokens):
        for b, tb in enumerate(tokens):
            dx = tb[0] - ta[0]
            dy = abs(tb[4] - ta[4])
            if 2 < dx <= salto_max and dy <= tol:
                arestas.append((dy + 0.02 * dx, a, b))
    arestas.sort()
    seguinte, anterior = {}, {}
    for _, a, b in arestas:
        if a in seguinte or b in anterior:
            continue
        seguinte[a], anterior[b] = b, a
    cadeias = []
    for inicio in (k for k in range(len(tokens)) if k not in anterior):
        cadeia, k = [], inicio
        while k is not None:
            cadeia.append(k)
            k = seguinte.get(k)
        cadeias.append(cadeia)
    return cadeias


# "VALOR DEPOSITO SDR", "DepOsito SDR:9575911634501 7UPZERO" — o deposito de embalagens (Volta). O OCR
# le o "o" como zero ("DepOsito"), e junta as palavras.
DEPOSITO_NA_FILA = re.compile(r"DEP[O0]S[I1]T[O0]")


def depositos(caixas, passo):
    """AS LINHAS DE DEPOSITO, lidas directamente da fila. [(y, quantidade, preco, valor)].

    O deposito de embalagens nao e mercadoria — nao leva preco nem etiqueta — mas CONTA PARA A PROVA:
    a factura declara-o na base isenta (ou "nao sujeito"), e sem ele as somas nunca fecham. Medido a
    25/09 em duas facturas: faltavam 3,60 e 4,00 na taxa 0, e eram exactamente os depositos.

    Le-se a parte porque o caminho normal nao lhes chega, por duas razoes diferentes:
      - a fila do deposito nao tem codigo de artigo (diz "VALOR DEPOSITO SDR"), por isso a conta dela
        ficava orfa em `sem_codigo`;
      - e numa das facturas as filas do deposito vem TODAS DEPOIS do ultimo codigo, fora da zona da
        tabela, onde as contas nem sequer se procuram.

    A fila tem de fechar a conta (quantidade x preco = valor) como qualquer outra: e isso que impede
    que uma palavra parecida com "deposito" no meio de uma descricao invente uma linha.

    E QUANDO O VALOR NAO SE LE, a conta faz-se. Numa das facturas o OCR devolveu "09'0" no lugar de
    "0,60" em duas filas — mas leu a quantidade (6,000) e o preco (0,1000). O preco do deposito e o
    mesmo em toda a factura, e aprende-se nas filas que fecharam: onde ele aparece, o valor e
    quantidade x preco. Nao se inventa numero nenhum — multiplicam-se dois que estao impressos, e a
    prova contra a base isenta declarada diz logo se a conta ficou errada."""
    candidatas = []
    for f in filas(caixas):
        texto = " ".join(c[3] for c in f["caixas"]).upper().replace(" ", "")
        if not DEPOSITO_NA_FILA.search(texto):
            continue
        ns = _numeros(f)
        achado = None
        for i in range(len(ns)):
            for j in range(i + 1, len(ns)):
                for k in range(j + 1, len(ns)):
                    q, p, v = ns[i][1], ns[j][1], ns[k][1]
                    if q > 0 and p > 0 and v > 0 and abs(q * p - v) <= 0.005 + 0.001 * q:
                        # o VALOR e o maior numero que fecha: numa fila com "0,00 (NS) 0,00 2,80" ha
                        # zeros pelo meio que nao sao a conta
                        if achado is None or v > achado[2]:
                            achado = (q, p, v)
        candidatas.append((f["y"], achado, [n[1] for n in ns]))
    # O PRECO DO DEPOSITO, aprendido nas filas que fecharam. So vale se TODAS concordarem: com precos
    # diferentes nao se sabe qual e o desta fila e nao se arrisca.
    precos = {a[1] for _y, a, _ns in candidatas if a}
    unitario = precos.pop() if len(precos) == 1 else None
    fora = []
    for y, achado, ns in candidatas:
        if achado:
            fora.append((y, achado[0], achado[1], achado[2]))
        elif unitario is not None and any(abs(n - unitario) < 0.0005 for n in ns):
            # o valor nao se leu: a quantidade e o maior numero inteiro da fila que nao e o preco
            qs = [n for n in ns if n >= 1 and abs(n - round(n)) < 0.0005 and abs(n - unitario) >= 0.0005]
            if qs:
                q = max(qs)
                fora.append((y, q, unitario, round(q * unitario, 2)))
    # a mesma fila lida duas vezes (duas caixas quase a mesma altura) nao conta duas vezes
    limpo = []
    for y, q, p, v in sorted(fora):
        if limpo and abs(y - limpo[-1][0]) < passo * 0.5:
            continue
        limpo.append((y, q, p, v))
    return limpo


def le_pagina(caminho, formato=None):
    """Uma pagina: cada codigo de artigo fica com a conta da sua linha.

    FORMATO (opcional, ver formatos.py): o que ja se sabe deste fornecedor de uma factura dele que
    ficou provada. Por agora usa-se uma coisa so, mas e a que mais custa descobrir sozinho: se a
    coluna do valor traz IVA. A deteccao automatica precisa de TRES linhas que so fechem com IVA
    para se decidir, e numa pagina onde poucas linhas fecham nunca la chega — que e exactamente o
    caso dos taloes dificeis. Sabendo-o do fornecedor, vale desde a primeira linha.

    HISTORIA DA LIGACAO numero-descricao, porque cada tentativa ensinou uma coisa:
      por ORDEM (i-esimo codigo com a i-esima conta) — bastava faltar um codigo para tudo o que
        vinha a seguir ficar com o preco do vizinho;
      por PROXIMIDADE na altura, com o desvio calibrado — funcionava nas linhas de cima e falhava
        a partir do meio, porque a folha esta curvada e o desvio cresce;
      SEGUINDO A LINHA (`_cadeias`) — cada salto e uma coluna, e a curvatura num salto e pouca."""
    caixas = ocr(caminho)
    largura = max((c[5] for c in caixas), default=1000) + 1
    fs = filas(caixas)
    topo = _y_cabecalho(fs)
    codigos = [k for f in fs for k in _codigos_da_fila(f, largura)]
    if topo is not None:
        codigos = [k for k in codigos if k["y"] > topo]
    codigos.sort(key=lambda k: k["y"])
    passo = 40.0
    if len(codigos) > 1:
        passo = (codigos[-1]["y"] - codigos[0]["y"]) / (len(codigos) - 1) or 40.0
    # as linhas de numeros, SO na zona da tabela: abaixo do cabecalho e ate uma fila e meia
    # depois do ultimo codigo (o quadro de totais no fundo tambem tem contas, e nao sao artigos)
    lo = topo if topo is not None else -1e9
    hi = (codigos[-1]["y"] + 1.5 * passo) if codigos else 1e9
    area = [t for t in _tokens(caixas) if lo < t[4] <= hi]
    contas = []
    conta_colunas = None
    cadeias = [[area[k] for k in cadeia] for cadeia in _cadeias(area, passo, largura)]
    coluna = coluna_do_valor(cadeias)                     # onde esta o total nesta pagina
    # A EVIDENCIA DESTA PAGINA MANDA SEMPRE; a memoria do fornecedor entra quando a pagina nao
    # chega para decidir; e quando nem uma nem outra sabem, NAO SE ASSUME — leem-se as duas
    # maneiras e fica a que fechar mais linhas.
    #
    # Assumir custava caro: a 24/09, ao ler o rolo do Recheio em bocados, cada bocado tinha poucas
    # filas e a deteccao nao decidia; assumia-se "sem IVA", e como aquele talao e c/IVA nao fechava
    # UMA linha — 59 codigos lidos e zero contas. Tentar as duas nao arrisca nada: quem aceita
    # continua a ser a conta de cada linha.
    def contas_de(com):
        fora = []
        for ns in cadeias:
            c = _melhor_conta(ns, coluna, com)
            if c:
                c.pop("_usados")
                c["y"] = ns[0][4]   # a ponta esquerda da linha, a que fica junto a descricao
                fora.append(c)
        return fora

    com_iva = valor_com_iva(cadeias)
    if com_iva is None and formato and formato.get("valor_com_iva") is not None:
        com_iva = bool(formato["valor_com_iva"])
    if com_iva is None:
        # Quando nem a pagina nem o fornecedor sabem, fica-se pelo caso comum (valor SEM IVA).
        # NAO se escolhe "a maneira que da mais linhas": a 24/09 essa regra leu uma pagina da
        # Poupanca como se fosse c/IVA, ganhou quatro linhas e estragou as outras — a factura
        # passou de faltar 1,90 EUR para faltar 26,82 e ainda inventou um escalao de 13% que ela
        # nao tem. Mais linhas nao e o mesmo que linhas certas.
        # Quem experimenta a outra maneira e o le_factura, que tem o QR para julgar o resultado.
        com_iva = False
    contas = contas_de(com_iva)
    contas.sort(key=lambda c: c["y"])
    linhas, sem_conta, sem_codigo, modo = _junta(codigos, contas, passo)
    if sem_conta and linhas:
        # segunda vista: reler a faixa dos numeros das linhas que ficaram sem conta
        import statistics as _st
        desvio = _st.median([l["y"] - l["y_codigo"] for l in linhas])
        faixas = colunas_das_linhas(linhas)
        # PRIMEIRO ENCHER AS COLUNAS (ler as celulas vazias), so depois emparelhar. Enquanto
        # faltarem numeros, nenhum metodo de emparelhamento os pode arranjar — ver completa_colunas.
        # SO AS FILAS PERDIDAS, e nao todos os codigos — medido a 24/09 e contra o que eu esperava.
        # Encher tambem as celulas das filas que ja fecharam completa as colunas (de 48 para 49
        # numeros em 54 codigos) mas PIORA a leitura: 44 linhas passaram a 43 e o buraco dos 23%
        # aumentou 11 EUR. Os numeros lidos nas celulas dessas filas entram na area e dao a grelha
        # candidatos errados para as filas vizinhas. Encher tudo nao compensa; encher onde falta,
        # sim.
        novos = completa_colunas(caminho, sem_conta, area, faixas, passo, desvio, largura)
        area = area + novos
        if faixas:
            # quantos numeros tem cada coluna depois de cheias, e quantos codigos tem a pagina.
            # Iguais = emparelhar por ordem e exacto (medido a 24/09 em tres paginas: 14/14, 19/19,
            # 8/8). Serve de diagnostico e e o que diz se a tabela esta completa.
            conta_colunas = [sum(1 for t in area if x0 <= t[0] <= x1) for x0, x1 in faixas]
        else:
            conta_colunas = None
        # depois a releitura da fila inteira, e por fim a grelha com o que ja ha
        recuperadas = _segunda_vista(caminho, sem_conta, desvio, passo, largura, coluna, com_iva,
                                     faixas)
        ja = {id(k) for k, _ in recuperadas}
        recuperadas += pela_grelha([k for k in sem_conta if id(k) not in ja], area, faixas,
                                   passo, desvio, coluna, com_iva, linhas=linhas)
        for k, c in recuperadas:
            linhas.append(dict(c, codigo=k["codigo"], descricao=k["descricao"], y_codigo=k["y"]))
        achadas = {id(k) for k, _ in recuperadas}
        sem_conta = [k for k in sem_conta if id(k) not in achadas]
        linhas.sort(key=lambda l: l["y_codigo"])
        if recuperadas:
            modo += " + %d de segunda vista" % len(recuperadas)
    _promocoes(caixas, linhas)
    _texto_por_baixo(codigos, linhas)
    precos_por_unidade(linhas)
    for l in linhas:
        l.setdefault("outros_numeros", [])
    # O deposito Volta do Recheio nao traz taxa, so a remissao para a nota de isencao ("6,00 c)").
    # Sem taxa e com DEPOSITO na descricao, e isento — e o QR (base isenta) confirma ou desmente.
    for l in linhas:
        if l["iva"] is None and "DEPOSITO" in l["descricao"].upper().replace(" ", ""):
            l["iva"] = 0.0
    # O LEITOR GENERICO DECIDE-SE PELA MERCADORIA, e por isso os depositos so entram DEPOIS. Postos
    # antes, uma pagina onde o leitor normal so apanhasse o deposito deixava de parecer vazia e o
    # generico nunca corria: foi o que aconteceu a 25/09 na factura 191054, que passou de 3 linhas
    # (pelo generico) para uma so, a do deposito.
    if not linhas:
        g = le_pagina_generica(caminho, caixas)
        if g["linhas"]:
            return _com_depositos(g, caixas, passo)
    tr = transportes(fs)
    inicio = fim = None
    if tr and codigos:
        acima = [v for y, v in tr if y < codigos[0]["y"]]
        abaixo = [v for y, v in tr if y > codigos[-1]["y"]]
        inicio = acima[-1] if acima else 0.0
        fim = abaixo[0] if abaixo else None
    return _com_depositos({"ficheiro": os.path.basename(caminho), "linhas": linhas,
                           "sem_conta": sem_conta, "sem_codigo": sem_codigo, "modo": modo,
                           "colunas_cheias": conta_colunas, "codigos": len(codigos),
                           "duvidosa": bool(sem_conta or sem_codigo or modo not in MODOS_FIAVEIS),
                           "transporte_inicio": inicio, "transporte_fim": fim}, caixas, passo)


def _com_depositos(pagina, caixas, passo):
    """Acrescenta a uma pagina ja lida as filas de DEPOSITO que ela nao apanhou (ver `depositos`).

    Entram como linhas para a prova poder fechar — a factura declara-as na base isenta. Nao sao
    mercadoria: levam `deposito` e o `propoe` deixa-as de fora das propostas de preco, como ja deixava
    as que vinham com codigo proprio."""
    linhas = pagina["linhas"]
    ja = [l.get("y_codigo", l.get("y")) for l in linhas]
    for y, q, p, v in depositos(caixas, passo):
        if any(t is not None and abs(y - t) < passo * 0.5 for t in ja):
            continue
        linhas.append({"codigo": "DEPOSITO", "descricao": "DEPOSITO DE EMBALAGENS",
                       "quantidade": q, "preco": p, "valor": v, "iva": 0.0, "desconto": 0,
                       "y": y, "y_codigo": y, "deposito": True, "outros_numeros": [],
                       "conf_min": None, "precos_alternativos": [], "preco_unidade": None})
        # a conta orfa desta fila, se a houve, passa a estar contada na linha
        pagina["sem_codigo"] = [c for c in (pagina.get("sem_codigo") or [])
                                if abs(c.get("y", -1e9) - y) >= passo * 0.5]
    linhas.sort(key=lambda l: l.get("y_codigo", l.get("y", 0)))
    return pagina


# ---------------------------------------------------------------- leitor generico (formatos novos)

CODIGO_GENERICO = re.compile(r"^[A-Z0-9][A-Z0-9./-]{2,24}$")


def _conta_generica(ns):
    """Como _melhor_conta, com duas folgas que os formatos conhecidos nao precisam: o VALOR pode vir
    com 3 casas ("33,330", Carceluz) e o preco tambem. So corre quando a pagina nao deu nenhuma
    linha pelas regras normais — no Recheio a Qt.Total tambem tem 3 casas, e ai isto enganava-se."""
    melhor = None
    for i in range(len(ns)):
        for j in range(i + 1, len(ns)):
            q, p = ns[i][1], ns[j][1]
            if q <= 0 or p <= 0 or "," not in ns[j][2]:
                continue
            for l in range(j + 1, len(ns)):
                v = ns[l][1]
                if v <= 0 or _casas(ns[l][2]) not in (2, 3):
                    continue
                tol = 0.0051 + q * 0.5 * 10 ** (-max(2, _casas(ns[j][2])))
                descontos = [0.0] + [ns[m][1] for m in range(j + 1, l) if 0 < ns[m][1] < 100]
                for d in descontos:
                    erro = abs(q * p * (1 - d / 100.0) - v)
                    if erro <= tol:
                        pontos = (j - i) + (l - j) + erro
                        if melhor is None or pontos < melhor[0]:
                            melhor = (pontos, i, j, l, d)
                        break
    if not melhor:
        return None
    _, i, j, l, d = melhor
    k_iva = _taxa_da_linha(ns, i, j, l)
    return {"i": i, "j": j, "l": l, "d": d, "iva": ns[k_iva][1] if k_iva is not None else None}


ETIQUETA_POR_BAIXO = re.compile(
    r"^\s*(LOTE|ORIGEM|FORNECEDOR|CAPTURADO|ARTE\s+DE\s+PESCA|NOME\s+CIENT|METODO|PRODUTO|VALIDADE|"
    r"CARRO|ZONA|DATA)\b", re.I)


def _continuacao(fs, linhas, x_desc, largura):
    """A DESCRICAO QUE CONTINUA NA LINHA DE BAIXO. Numa factura estreita o fornecedor parte a descricao
    em duas ("GOMAS MELLOWS TACO TWISTY FINI" / "12x80G"), e sem a segunda parte perde-se logo o que
    distingue o produto e o tamanho da caixa (GENIALIS, 17/09).

    So junta uma fila que: esta logo abaixo (menos de uma linha e meia), comeca na coluna da descricao,
    nao tem nenhum numero com virgula (isso seria outra conta) e nao e a fila de outra linha lida."""
    if not linhas:
        return linhas
    ys = sorted(l["y"] for l in linhas)
    passo = ((ys[-1] - ys[0]) / (len(ys) - 1)) if len(ys) > 1 else 40.0
    ocupadas = {round(l["y"], 1) for l in linhas}
    for l in linhas:
        abaixo = [f for f in fs if 0 < f["y"] - l["y"] <= 1.4 * passo and round(f["y"], 1) not in ocupadas]
        if not abaixo:
            continue
        f = min(abaixo, key=lambda f: f["y"])
        todas = sorted(f["caixas"], key=lambda k: k[0])
        # se a fila de baixo comeca na coluna da REFERENCIA, e outro produto (mesmo que o leitor nao lhe
        # tenha conseguido fechar a conta): os Jelly Kisses ficaram com a descricao das melancias colada
        if any(k[0] < x_desc - 0.02 * largura and re.search(r"\d", k[3]) for k in todas):
            continue
        cx = [k for k in todas if k[0] >= x_desc - 0.02 * largura]
        texto = " ".join(k[3] for k in cx).strip()
        if not texto or len(texto) > 60 or re.search(r"\d,\d", texto) or _tokens(cx) and len(_tokens(cx)) > 2:
            continue
        # as ETIQUETAS que o Recheio imprime por baixo do peixe e da carne ("Lote:", "Origem:",
        # "Fornecedor:", "Nome Cientifico:") nao fazem parte do nome do produto
        if ETIQUETA_POR_BAIXO.match(texto) or ":" in texto or "..." in texto:
            continue
        # uma continuacao nao tem preco nem valor; costuma ser o resto do nome ("12x80G", "S/GLUTEN")
        l["descricao"] = _limpa((l["descricao"] + " " + texto).strip())
        l["continuou"] = True
    return linhas


def le_pagina_generica(caminho, caixas=None):
    """LEITOR PARA FORMATOS QUE NUNCA VIMOS. Nao conhece o fornecedor: descobre a tabela.

      1. AS CONTAS DIZEM QUAIS SAO AS LINHAS DE PRODUTO: em cada fila, quantidade x preco x
         (1 - desconto) = valor. Uma fila que faz a conta e um artigo, seja qual for o formato.
      2. O ALINHAMENTO DIZ QUAL E A REFERENCIA: nas filas que fazem a conta, a primeira caixa de
         texto a esquerda da quantidade comeca quase sempre na mesma posicao — essa coluna e a
         referencia do fornecedor, e o texto a seguir e a descricao. Quando o OCR colou referencia
         e descricao numa caixa so ("TECLDP-130-110-LAMPLEDE27..."), corta-se na posicao da coluna
         da descricao medida nas outras filas, acertada ao hifen ou espaco mais proximo.
      3. As provas sao as de sempre (QR por taxa). A pagina sai DUVIDOSA sempre que a referencia
         nao esta alinhada em pelo menos 80% das filas.

    Medido na Carceluz (PHC, referencias alfanumericas, valores com 3 casas): o OCR lia tudo;
    faltavam so regras. Este leitor e essas regras escritas sem nome de fornecedor."""
    caixas = ocr(caminho) if caixas is None else caixas
    largura = max((c[5] for c in caixas), default=1000) + 1
    itens = []
    for f in filas(caixas):
        cx = sorted(f["caixas"], key=lambda c: c[0])
        ns = _tokens(cx)
        c = _conta_generica(ns)
        if not c:
            continue
        xq = ns[c["i"]][0]
        # texto a esquerda da quantidade: sem numeros soltos
        esq = [k for k in cx if k[5] <= xq + 2 and not NUM.match(k[3].split()[0] if k[3].split() else "")]
        if not esq:
            continue
        itens.append({"f": f, "ns": ns, "c": c, "esq": esq})
    if not itens:
        return {"ficheiro": os.path.basename(caminho), "linhas": [], "sem_conta": [], "sem_codigo": [],
                "modo": "generico: nenhuma fila faz a conta", "duvidosa": True,
                "transporte_inicio": None, "transporte_fim": None}
    xs = sorted(it["esq"][0][0] for it in itens)
    x_ref = xs[len(xs) // 2]
    alinhadas = [it for it in itens if abs(it["esq"][0][0] - x_ref) <= 0.025 * largura]
    sem_conta = _codigos_sem_conta(filas(caixas), itens, x_ref, largura)
    # onde comeca a descricao: a 2.a caixa nas filas em que o OCR as separou
    segundas = sorted(it["esq"][1][0] for it in alinhadas if len(it["esq"]) > 1)
    x_desc = segundas[len(segundas) // 2] if segundas else None
    linhas, sem_codigo = [], []
    for it in itens:
        ns, c, esq = it["ns"], it["c"], it["esq"]
        primeira = esq[0]
        texto = primeira[3].strip()
        resto = [k[3] for k in esq[1:]]
        codigo = None
        if abs(primeira[0] - x_ref) <= 0.025 * largura:
            if resto or " " in texto and CODIGO_GENERICO.match(texto.split()[0]):
                partes = texto.split(None, 1) if not resto else [texto]
                codigo = partes[0]
                resto = partes[1:] + resto
            elif x_desc and primeira[5] > x_desc:
                # colado: corta pela posicao da coluna da descricao, acertado a um hifen/espaco
                k = int(round((x_desc - primeira[0]) / max(1.0, primeira[5] - primeira[0]) * len(texto)))
                # so corta num hifen/espaco SEGUIDO DE LETRA: a descricao comeca por uma palavra.
                # "TECLDP-130-110-LAMPLED..." cortado no hifen mais perto dava "TECLDP-130" e
                # "110-LAMPLED" — e a leitura dupla contava a linha duas vezes.
                cortes = [m.end() for m in re.finditer(r"[-\s]", texto)
                          if abs(m.end() - k) <= 6 and m.end() < len(texto) and texto[m.end()].isalpha()]
                k = min(cortes, key=lambda e: abs(e - k)) if cortes else k
                codigo, resto = texto[:k].strip(), [texto[k:]] + resto
            else:
                partes = texto.split(None, 1)
                codigo, resto = partes[0], partes[1:] + resto
        if codigo and not (CODIGO_GENERICO.match(codigo.upper()) and re.search(r"\d", codigo)):
            resto = [codigo] + resto
            codigo = None
        q, p, v = ns[c["i"]][1], ns[c["j"]][1], ns[c["l"]][1]
        if not codigo:
            sem_codigo.append({"quantidade": q, "preco": p, "valor": v, "desconto": c["d"], "y": it["f"]["y"]})
            continue
        # numeros que sobram na fila: o LOTE tambem vem impresso na embalagem e liga a foto a esta linha
        usados = {c["i"], c["j"], c["l"]}
        livres = sorted({ns[k][2] for k in range(len(ns)) if k not in usados and "," not in ns[k][2]
                         and len(re.sub(r"\D", "", ns[k][2])) >= 4})
        linhas.append({"codigo": codigo.rstrip("-"), "descricao": _limpa(" ".join(resto)), "quantidade": q,
                       "preco": p, "desconto": c["d"], "valor": round(v, 2), "iva": c["iva"], "prova_iva": None,
                       "conf_min": min(ns[c["i"]][3], ns[c["j"]][3], ns[c["l"]][3]), "precos_alternativos": [],
                       "outros_numeros": livres, "y": it["f"]["y"], "y_codigo": it["f"]["y"]})
    for l in linhas:
        if l["iva"] is None and "DEPOSITO" in l["descricao"].upper().replace(" ", ""):
            l["iva"] = 0.0
    _continuacao(filas(caixas), linhas, x_desc if x_desc is not None else x_ref, largura)
    precos_por_unidade(linhas)
    fraccao = len(alinhadas) / len(itens)
    lidos = {l["codigo"] for l in linhas}
    sem_conta = [k for k in sem_conta if k["codigo"] not in lidos]     # um codigo que ja e linha nao falta
    return {"ficheiro": os.path.basename(caminho), "linhas": linhas, "sem_conta": sem_conta, "sem_codigo": sem_codigo,
            "modo": "generico (%d filas pela conta; referencia alinhada em %.0f%%)" % (len(itens), 100 * fraccao),
            "duvidosa": bool(sem_codigo or sem_conta) or fraccao < 0.8,
            "transporte_inicio": None, "transporte_fim": None}


def _codigos_sem_conta(fs, itens, x_ref, largura):
    """As filas da tabela com um CODIGO na coluna das referencias mas SEM CONTA que feche. O leitor generico
    saltava-as sem deixar rasto: a 30/09, na Meigal, "1000000238 ALMONDEGAS BOVINO ... 5 UN x 27,50 = 27,50"
    (o preco era o da embalagem de 5) desapareceu — nem "codigo sem linha" ficou, e o codigo de barras do
    saco nao tinha a que se ligar. Nao se inventa numero nenhum: fica so o codigo e a descricao, e a prova
    passa a saber que falta uma linha.

    So conta uma fila: dentro da zona da tabela (entre a primeira e a ultima linha que fechou, com a folga de
    uma linha para cima e para baixo), com a primeira caixa na coluna da referencia medida nas linhas que
    fecharam, e um codigo com algarismos seguido de descricao com letras."""
    # pela ALTURA da fila e nao pelo objecto: as filas sao calculadas outra vez para aqui chegarem
    feitas = {round(it["f"]["y"], 1) for it in itens}
    ys = sorted(it["f"]["y"] for it in itens)
    if len(ys) < 2:
        return []
    passo = sorted(b - a for a, b in zip(ys, ys[1:]))[len(ys) // 2 - 1] or 40.0
    # EM CIMA, O CABECALHO DA TABELA (como no leitor normal): na Meigal de 30/09 as duas primeiras linhas nao
    # fecharam na foto original, e com "uma linha acima da primeira que fechou" as almondegas ficavam de fora
    topo = _y_cabecalho(fs)
    lo = topo if topo is not None and topo < ys[0] else ys[0] - 1.2 * passo
    hi = ys[-1] + 1.2 * passo
    fora = []
    for f in fs:
        if round(f["y"], 1) in feitas or not (lo <= f["y"] <= hi):
            continue
        # como nas linhas que fecham (le_pagina_generica): as caixas que comecam por um numero solto ("10", o
        # n.o do item) nao sao a referencia
        cx = [k for k in sorted(f["caixas"], key=lambda c: c[0]) if not NUM.match((k[3].split() or [""])[0])]
        if not cx or abs(cx[0][0] - x_ref) > 0.025 * largura:
            continue
        partes = cx[0][3].strip().split(None, 1)
        codigo = partes[0].rstrip("-") if partes else ""
        if len(codigo) < 4 or not (CODIGO_GENERICO.match(codigo.upper()) and re.search(r"\d", codigo)):
            continue
        desc = _limpa(" ".join(partes[1:] + [k[3] for k in cx[1:] if not NUM.match((k[3].split() or [""])[0])]))
        if not re.search(r"[A-Za-z]{3}", desc):
            continue
        # do_generico: a altura dos NUMEROS desta linha nao se sabe (e por isso que nao fechou) — o
        # cloud.alinhamento nao a usa para julgar em que fila esta o valor
        fora.append({"codigo": codigo, "descricao": desc, "y": f["y"], "do_generico": True})
    return fora


PROMO = re.compile(r"POUPOU|PRECO ORIGINAL|PRE.O ORIGINAL")
PRECO_ORIGINAL = re.compile(r"ORIGINAL\s*:?\s*(\d{1,4},\d{2})")


def _promocoes(caixas, linhas):
    """Marca as linhas compradas em PROMOCAO, com o preco normal que a nota indica.

    O Recheio imprime, por baixo da linha, "Poupou com a promocao a caixa - preco original 1,49
    eur/unid.". O custo da linha (1,37) e PROMOCIONAL. Uma regra "o custo desceu, baixa o preco
    de venda" baixaria o preco da loja por causa de uma promocao de uma semana — e depois a margem
    ia ao chao quando a mercadoria seguinte chegasse ao preco normal. Por isso a linha leva o preco
    original, e e esse que conta para decidir precos.

    A nota refere-se a linha DE CIMA. A primeira leitura colou "Poupou com a" a descricao do
    artigo de baixo (o Ice Tea de 20cl), porque a nota e a linha seguinte caiam na mesma fila."""
    for x, y, h, texto, conf, x2 in caixas:
        t = texto.upper().replace("0", "O")
        if not PROMO.search(t):
            continue
        acima = [l for l in linhas if l["y_codigo"] < y]
        if not acima:
            continue
        alvo = max(acima, key=lambda l: l["y_codigo"])
        alvo["promo"] = True
        m = PRECO_ORIGINAL.search(texto.upper())
        if m:
            alvo["preco_original"] = _f(m.group(1))
    # a nota nao faz parte da descricao de ninguem
    for l in linhas:
        l["descricao"] = re.split(r"\s+Poupou\b", l["descricao"], flags=re.I)[0].strip()


def _texto_por_baixo(codigos, linhas):
    """Marca as linhas que tem ESPACO por baixo — onde o papel imprimiu alguma coisa.

    Medido a 2026-09-14 na factura 73442: a nota "preco original 1,49" por baixo da Coca-Cola
    1,5L NAO foi lida pelo OCR — nenhuma caixa de texto, nada. Sem guarda, o custo promocional
    (1,37) passava por custo normal e a regra "o custo desceu" baixava o preco da loja.
    O que o OCR nao consegue esconder e o BURACO: entre dois artigos seguidos ha o dobro da altura
    normal. Uma linha com buraco por baixo e sem nota lida fica marcada, e uma descida de custo
    nela nunca se aplica sozinha. (Nos blocos de rastreabilidade do peixe tambem dispara: nao faz
    mal, so trava descidas automaticas.)"""
    import statistics
    ys = [k["y"] for k in codigos]
    if len(ys) < 3:
        return
    passos = [b - a for a, b in zip(ys, ys[1:])]
    normal = statistics.median(passos)
    com_buraco = {round(a, 1) for a, d in zip(ys, passos) if d > 1.6 * normal}
    for l in linhas:
        if round(l["y_codigo"], 1) in com_buraco:
            l["texto_por_baixo"] = True


# "CX6", "CAIXA 12", "Cx24", "CX:6" — tambem colado ao que vem antes ("1.5LTCX6"), que e como o OCR devolve.
# 21/09: a Frukendy vinha "1.5LTCX:6" e os dois pontos escondiam a caixa
CAIXA_NA_DESCRICAO = re.compile(r"(?<!\d)C(?:X|AIXA)\s*[-.:]?\s*(\d{1,3})(?!\d)")
# "(006UN)", "6 UNID", "PACK 4", "PK4", "EMB6": o numero de unidades dito por extenso, em qualquer formato
# (22/09, "CHEETOSPANDILHA031TIR(006UN)" a 4,92 = 6 x 0,82). NAO entram "PC"/"P" nem numeros soltos: na mesma
# factura, "CHEETOS FUTEBOLAS130G 6PC03222" custa 1,62 e NAO e uma caixa de 6 — quem decide e a conta.
UNIDADES_NA_DESCRICAO = re.compile(r"(?<![\d.,])(\d{1,3})\s*(?:UN|UND|UNID|UNIDS|UNIDADES)(?![A-Z])"
                                   r"|(?<![A-Z])(?:PACK|PK|EMB|EMBALAGEM)\s*[-.:]?\s*(\d{1,3})(?!\d)")
# "12x90G", "12x80G", "10x500g" — a caixa dita pelo numero de embalagens e o peso de cada uma
EMBALAGENS_NA_DESCRICAO = re.compile(r"(?<!\d)(\d{1,3})\s*[X*]\s*\d{1,4}(?:[.,]\d+)?\s*(?:G|GR|KG|ML|CL|LT|L|UN)(?![A-Z])")


def unidades_da_caixa(desc):
    """Quantas unidades traz a caixa, quando a DESCRICAO o diz: "AGUA PENACOVA 1.5LT CX6" -> 6,
    "AGUA PEDRAS T/P - Cx24" -> 24, "GOMAS MELLOWS TACO TWISTY FINI 12x80G" -> 12.

    Quem usa isto nao decide nada sozinho: para um artigo que ja existe, o preco por unidade so e
    aceite se couber no custo medio da loja (propoe._propoe_artigo) — na Gelpeixe ha linhas "10x800g"
    cujo preco e por KG, e ai a divisao dava errado e e recusada."""
    t = " " + (desc or "").upper() + " "
    m = CAIXA_NA_DESCRICAO.search(t) or EMBALAGENS_NA_DESCRICAO.search(t) or UNIDADES_NA_DESCRICAO.search(t)
    n = int(next((g for g in m.groups() if g), 0)) if m else 0
    return n if 2 <= n <= 144 else None


def precos_por_unidade(linhas):
    """Acrescenta a cada linha o PRECO LIQUIDO e o PRECO POR UNIDADE, quando a factura os permite saber:
      0. LIQUIDO: com desconto na linha, o custo e o valor a dividir pela quantidade, e nao o preco de
         tabela (GENIALIS 17/09: 7,68 menos 10% = 6,91 — o que se paga e 6,91);
      1. POR UNIDADE impresso numa coluna propria (Gelpeixe "Preco UN") — vem de _melhor_conta;
      2. a descricao diz a caixa ("CX6", "12x80G") e o preco e da caixa: divide-se (MINIMATOS, agua
         Penacova 1,86 a caixa de 6 = 0,31 a garrafa; GENIALIS, 6,91 a caixa de 12 = 0,58 o saco);
      2b. MESMA CAIXA EM TODA A FACTURA: quando 3 ou mais linhas dizem a mesma caixa (12x90G, 12x80G) e
         numa delas o OCR perdeu o "x" ("1280G"), vale o mesmo numero — e a mesma factura do mesmo
         fornecedor, nao se esta a adivinhar produto nenhum.
    Ninguem escolhe aqui qual e o custo: a linha leva os precos todos e a proposta escolhe pelo custo
    que a loja ja tem (propoe._propoe_artigo)."""
    from collections import Counter
    for l in linhas:
        # O CUSTO E O QUE SE PAGA: valor / quantidade. Com desconto na linha, ou quando o valor e MENOR do que
        # quantidade x preco sem desconto nenhum lido (02/10, Distrobidos: "0,00" na coluna e "+28,50" numa linha por
        # baixo — 2 CX x 14,28 = 28,56 mas o valor e 20,42; cada caixa custa 10,21, nao 14,28).
        q, v, p = l.get("quantidade"), l.get("valor"), l.get("preco") or 0
        implicito = q and v is not None and p and v < q * p - 0.011
        if q and v is not None and ((l.get("desconto") or 0) > 0 or implicito):
            liquido = round(v / q, 4)
            if abs(liquido - p) > 0.005:
                l["preco_liquido"] = liquido
        n = unidades_da_caixa(l.get("descricao"))
        if n:
            l["unidades_caixa"] = n
    contas = Counter(l["unidades_caixa"] for l in linhas if l.get("unidades_caixa"))
    comum = contas.most_common(1)[0][0] if contas and contas.most_common(1)[0][1] >= 3 else None
    for l in linhas:
        if comum and not l.get("unidades_caixa"):
            # o "x" perdido pelo OCR: "1280G" com 12 a frente, na factura em que 12 e a caixa de todos
            if re.search(r"(?<!\d)%d\d{2,4}\s*(?:G|GR|ML|CL|LT|L)(?![A-Z])" % comum, (l.get("descricao") or "").upper()):
                l["unidades_caixa"] = comum
                l["caixa_da_factura"] = True
        n = l.get("unidades_caixa")
        base = l.get("preco_liquido") or l.get("preco")
        if l.get("preco_unidade") is None and n and base:
            l["preco_unidade"] = round(base / n, 4)
            l["unidade_calculada"] = True
    return linhas


MODOS_FIAVEIS = ("ordem", "ordem e proximidade concordam")


def _junta(codigos, contas, passo):
    """Liga codigos a contas. As duas listas vem pela ordem da pagina, de cima para baixo.

    POR ORDEM quando ha tantas contas como codigos e o desvio entre elas varia devagar — medido
    nas fotos do Recheio: os numeros saem impressos acima das descricoes, e esse desvio muda ao
    longo da folha curvada, mas de uma linha para a seguinte muda pouco. Um salto brusco no desvio
    e o sinal de que uma conta ficou com o artigo do vizinho, e ai nao se confia na ordem.

    Senao, por PROXIMIDADE com o desvio calibrado — e a pagina fica marcada como duvidosa. Esta
    via erra quando o desvio chega a meia linha (os numeros ficam a igual distancia de dois
    artigos), e foi o que trocou quatro linhas na primeira pagina do Recheio."""
    import statistics
    if codigos and len(codigos) == len(contas):
        difs = [c["y"] - k["y"] for k, c in zip(codigos, contas)]
        if all(abs(difs[i] - difs[i - 1]) <= 0.5 * passo for i in range(1, len(difs))):
            return ([dict(c, codigo=k["codigo"], descricao=k["descricao"], y_codigo=k["y"])
                     for k, c in zip(codigos, contas)], [], [], "ordem")
    if not codigos or not contas:
        return [], list(codigos), list(contas), "proximidade"
    difs = [min((c["y"] - k["y"] for k in codigos), key=abs) for c in contas]
    desvio = statistics.median(difs)
    pares = sorted((abs(c["y"] - desvio - k["y"]), ic, ik)
                   for ic, c in enumerate(contas) for ik, k in enumerate(codigos))
    usadas_c, usados_k, linhas = set(), set(), []
    for dist, ic, ik in pares:
        if dist > 0.6 * passo:
            break
        if ic in usadas_c or ik in usados_k:
            continue
        usadas_c.add(ic)
        usados_k.add(ik)
        linhas.append(dict(contas[ic], codigo=codigos[ik]["codigo"],
                           descricao=codigos[ik]["descricao"], y_codigo=codigos[ik]["y"],
                           _ik=ik, _ic=ic))
    # BURACOS COM UM SO CANDIDATO. Entre dois pares ja ligados, se sobra exactamente um codigo e
    # exactamente uma conta, sao um do outro — a ordem da pagina garante-o. Na primeira pagina do
    # Recheio sobravam a Pizza e uma conta de 6 x 2,08 = 12,48, e o TRANSPORTE dizia que faltavam
    # precisamente 12,48.
    ligados = sorted((l["_ik"], l["_ic"]) for l in linhas)
    fronteiras = [(-1, -1)] + ligados + [(len(codigos), len(contas))]
    for (k0, c0), (k1, c1) in zip(fronteiras, fronteiras[1:]):
        ks = [i for i in range(k0 + 1, k1) if i not in usados_k]
        cs = [j for j in range(c0 + 1, c1) if j not in usadas_c]
        if len(ks) == 1 and len(cs) == 1:
            usados_k.add(ks[0])
            usadas_c.add(cs[0])
            linhas.append(dict(contas[cs[0]], codigo=codigos[ks[0]]["codigo"],
                               descricao=codigos[ks[0]]["descricao"],
                               y_codigo=codigos[ks[0]]["y"], _ik=ks[0], _ic=cs[0]))
    linhas.sort(key=lambda l: l["y_codigo"])
    # sem cruzamentos: a i-esima linha em altura tem de ter a i-esima conta em altura
    sem_cruzar = [l["_ic"] for l in linhas] == sorted(l["_ic"] for l in linhas)
    for l in linhas:
        l.pop("_ik", None)
        l.pop("_ic", None)
    sem_conta = [k for i, k in enumerate(codigos) if i not in usados_k]
    sem_codigo = [c for i, c in enumerate(contas) if i not in usadas_c]
    # DUAS REGUAS. Se, no fim, tudo ficou ligado e sem cruzamentos, a proximidade chegou ao mesmo
    # resultado que a ordem teria dado — dois metodos diferentes a concordar, e isso vale mais do
    # que qualquer um deles sozinho (a ordem so falhou o teste de suavidade por a folha estar
    # curvada, nao por haver uma troca).
    if not sem_conta and not sem_codigo and sem_cruzar:
        return linhas, [], [], "ordem e proximidade concordam"
    return linhas, sem_conta, sem_codigo, "proximidade"


# LETRA PEQUENA DEMAIS NA FOTO (pedido do Pedro, 01/10). O talao do Recheio de 01/10 fotografado inteiro tinha
# ~9 pixeis por letra: de 47 linhas o leitor so leu os numeros de 17, e um custo saiu errado (0,80 em vez de
# 0,63). A mesma folha fotografada de perto (~17 px por letra) deu 46 de 47, todas certas. Mede-se a largura
# das letras nas caixas que o OCR ja leu (vem da cache, nao custa tempo). Sozinha nao prova nada — paginas de
# referencia com 6-8 px leram-se bem —, por isso so serve para EXPLICAR uma factura que nao ficou provada.
LETRA_MINIMA = 11.0


def letra_px(caminho):
    """Largura tipica de uma letra na foto, em pixeis (mediana das caixas com 5 ou mais caracteres)."""
    try:
        cx = ocr(caminho)
    except Exception:                                      # noqa: BLE001 — sem medida, sem aviso
        return None
    ws = sorted((c[5] - c[0]) / len(c[3]) for c in cx if len(c[3]) >= 5)
    return round(ws[len(ws) // 2], 1) if ws else None


def le_factura(caminhos):
    import qr_factura as Q
    paginas = [le_pagina(c) for c in caminhos]
    qr = None
    for c in caminhos:
        qs = Q.le_foto(c)
        if qs:
            qr = qs[0]
            break
    # sem QR, os totais impressos no papel servem de referencia (totais_factura.py, 25/09)
    impresso = None
    if not qr:
        try:
            import totais_factura as TF
            impresso = TF.declarado_impresso([ocr(c) for c in caminhos])
        except Exception:                                  # noqa: BLE001 — fica sem referencia
            impresso = None
    return {"paginas": paginas, "qr": qr, "impresso": impresso}


def relatorio(fac):
    print()
    acumulado = 0.0
    por_taxa = {}
    for p in fac["paginas"]:
        soma = sum(l["valor"] for l in p["linhas"])
        acumulado += soma
        estado = "%d linhas" % len(p["linhas"])
        if p["duvidosa"]:
            estado += " — DUVIDOSA: %d codigos sem conta, %d contas sem codigo" \
                      % (len(p["sem_conta"]), len(p["sem_codigo"]))
        print("== %s — %s" % (p["ficheiro"], estado))
        for l in p["linhas"]:
            print("   %-10s %-38s %8.3f x %8.3f = %8.2f  IVA %-4s %s"
                  % (l["codigo"], l["descricao"][:38], l["quantidade"], l["preco"], l["valor"],
                     ("%g" % l["iva"]) if l["iva"] is not None else "?",
                     "c/IVA ok" if l["prova_iva"] else ""))
            if l["iva"] is not None:
                por_taxa[l["iva"]] = por_taxa.get(l["iva"], 0.0) + l["valor"]
        for k in p["sem_conta"]:
            print("   %-10s %-38s   (sem conta lida)" % (k["codigo"], k["descricao"][:38]))
        for c in p["sem_codigo"]:
            print("   %-10s %-38s %8.3f x %8.3f = %8.2f   (conta sem artigo)"
                  % ("?", "", c["quantidade"], c["preco"], c["valor"]))
        if p["transporte_fim"] is not None:
            # cada pagina confere-se SOZINHA: o que ela acrescenta ao acumulado
            esperado = p["transporte_fim"] - (p["transporte_inicio"] or 0.0)
            bate = abs(soma - esperado) <= 0.02
            print("   TRANSPORTE %.2f -> %.2f: a pagina vale %.2f | linhas lidas %.2f -> %s"
                  % (p["transporte_inicio"] or 0.0, p["transporte_fim"], esperado, soma,
                     "BATE" if bate else "faltam %.2f" % (esperado - soma)))
    print()
    q = fac["qr"]
    if not q:
        print("sem QR fiscal: as linhas nao tem com que ser conferidas no total")
        return
    mapa = {6.0: "reduzida", 13.0: "intermedia", 23.0: "normal"}
    print("contra o QR (factura %s, total %.2f EUR):" % (q["numero"], q["total"]))
    for taxa, nome in mapa.items():
        esperado = q["por_taxa"].get(nome, {}).get("base", 0.0)
        lido = por_taxa.get(taxa, 0.0)
        if esperado or lido:
            print("   IVA %2g%%  QR %9.2f | linhas lidas %9.2f | %s"
                  % (taxa, esperado, lido,
                     "BATE" if abs(esperado - lido) <= 0.02 else
                     "faltam %.2f EUR (paginas por fotografar?)" % (esperado - lido)))
    if q["base_isenta"]:
        print("   isento  QR %9.2f | linhas lidas %9.2f" % (q["base_isenta"], por_taxa.get(0.0, 0.0)))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    relatorio(le_factura(sys.argv[1:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
