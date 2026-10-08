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

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

# Virgula decimal, como nas facturas PT — e ponto de MILHARES nos valores grandes: o TRANSPORTE
# "1.021,27" era rejeitado e as paginas 5 e 6 da factura 72816 ficavam sem prova. O ponto so
# conta como milhares quando separa grupos de 3 algarismos e ha virgula: os codigos do Recheio
# ("117627.1") nunca passam por aqui.
NUM = re.compile(r"^-?(?:\d{1,7}|\d{1,3}(?:\.\d{3})+)(?:,\d{1,4})?$")
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
    import statistics
    cru = _ocr_cru(caminho)
    largas = [c[6] for c in cru if c[1] - c[0] > 150]
    incl = statistics.median(largas) if largas else 0.0
    # (x_min, y, altura, texto, conf, x_max) — o x_max serve para repartir numeros colados
    return [(c[0], c[2] - incl * (c[0] + c[1]) / 2.0, c[3], c[4], c[5], c[1]) for c in cru]


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
    return [p]


NOTA_COLADA = re.compile(r"^(\d{1,7},\d{2})([a-z]\))$")
ZERO_LETRA_FIM = re.compile(r"^(\d{1,2},\d)[CO]$")
UNIDADE_COLADA = re.compile(r"^(\d{1,6},\d{2,3})(UN|KG|LT|CX|PK|MT|M2|GR)$")


PONTO_DECIMAL = re.compile(r"^\d{1,4}\.\d{2}$")
# Taxa impressa com percentagem ("23%", Poupanca) e motivo de isencao no lugar da taxa ("M99",
# o deposito Volta). Entram como numeros so para o IVA: nao tem virgula, logo nunca sao preco
# nem valor da linha.
TAXA_PCT = re.compile(r"^(\d{1,2})%$")
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


def _triplos(ns):
    """Todas as contas que batem na fila: [(pontos, i, j, l, d)] — quantidade i, preco j, valor l,
    desconto d. Quem escolhe entre elas e _melhor_conta (ou a coluna do valor da pagina)."""
    fora = []
    for i in range(len(ns)):
        for j in range(i + 1, len(ns)):
            q, p = ns[i][1], ns[j][1]
            # o PRECO e dinheiro: tem virgula. "Vol" e "Qt./Vol." sao inteiros e nunca sao preco
            if q <= 0 or p <= 0 or "," not in ns[j][2]:
                continue
            for l in range(j + 1, len(ns)):
                v = ns[l][1]
                # o VALOR da linha e dinheiro: exactamente 2 casas. E isto que afasta a outra
                # multiplicacao do Recheio, Vol x Qt./Vol = Qt.Total, porque a Qt.Total tem 3
                # casas ("5,000"). A primeira versao apanhava-a e dizia "7 x 1 = 7,00".
                if v <= 0 or _casas(ns[l][2]) != 2:
                    continue
                # Folga = arredondamento do valor (meio centimo) + o do preco impresso vezes a
                # quantidade. Depende das CASAS com que o preco vem: com uma folga fixa de 1
                # centimo passava "1,000 x 1,000 = 0,99" no espinafre, e "2,000 x 2,000 = 3,99"
                # na margarina — duas quantidades tomadas por preco.
                tol = 0.0051 + q * 0.5 * 10 ** (-_casas(ns[j][2]))
                descontos = [0.0] + [ns[m][1] for m in range(j + 1, l) if 0 < ns[m][1] < 100]
                for d in descontos:
                    erro = abs(q * p * (1 - d / 100.0) - v)
                    if erro <= tol:
                        # quanto mais encostados e mais exacta a conta, melhor
                        fora.append(((j - i) + (l - j) + erro, i, j, l, d))
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


def _melhor_conta(ns, coluna_valor=None):
    """Procura quantidade x preco (x (1 - desconto)) = valor. None se nenhuma combinacao bater.

    Entre varias combinacoes validas escolhe a de quantidade mais proxima do preco: no Recheio
    '5 1 5,000 1,19 5,95' tanto o Vol (5) como a Qt.Total (5,000) batem, mas no molho bechamel
    '1 6 6,000 1,19 7,14' so a Qt.Total bate — e a coluna certa e sempre a encostada ao preco.

    COLUNA_VALOR ("ultima"): a pagina ja disse onde esta a coluna do total (ver coluna_do_valor) e
    so contam as contas que acabam la. Sem isto, na Gelpeixe "8,00 1,00 2,88 23 2,65 2,65 21,20"
    dava 1 x 2,65 = 2,65 (as colunas Preco liq. e Preco UN sao iguais) em vez de 8 x 2,65 = 21,20."""
    todos = _triplos(ns)
    escolha = [t for t in todos if t[3] == len(ns) - 1] if coluna_valor == "ultima" else todos
    if not escolha:
        escolha = todos
    if not escolha:
        return None
    validas = [(t[3], ns[t[2]][1], _casas(ns[t[2]][2])) for t in todos]
    _, i, j, l, d = min(escolha)
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
    # Taxa de IVA: um numero com casas decimais, a direita do preco, que seja uma taxa legal.
    # PREFERE uma taxa diferente de zero: no Pao de Mafra a coluna do desconto (0,00) vem antes
    # da do IVA (6,00), e a primeira versao apanhava o desconto e dizia IVA 0%. Zero so fica
    # quando e o unico candidato. A prova final da taxa e o QR, que tem a base por taxa.
    candidatos = [k for k in range(j + 1, len(ns))
                  if k != l and ns[k][1] in TAXAS_IVA
                  and ("," in ns[k][2] or TAXA_PCT.match(ns[k][2]) or ISENCAO.match(ns[k][2]))]
    if not candidatos:
        # TAXA SEM CASAS DECIMAIS ("6", "23" na Gelpeixe), e impressa ANTES do preco liquido, por isso
        # tambem se procura a esquerda do preco. Sem isto a Gelpeixe ficava com todas as linhas sem
        # IVA e nenhuma base do QR se podia provar. So conta se houver UMA taxa legal na linha: dois
        # numeros diferentes que sejam taxas seria adivinhar qual.
        inteiros = [k for k in range(i + 1, len(ns))
                    if k not in (j, l) and "," not in ns[k][2] and ns[k][1] in TAXAS_IVA and ns[k][1] > 0]
        if len({ns[k][1] for k in inteiros}) == 1:
            candidatos = inteiros
    nao_zero = [k for k in candidatos if ns[k][1] > 0]
    k_iva = nao_zero[0] if nao_zero else (candidatos[0] if candidatos else None)
    iva = ns[k_iva][1] if k_iva is not None else None
    usados = {i, j, l} | ({k_iva} if k_iva is not None else set())
    # prova extra do Recheio: preco x (1 + IVA) = preco c/IVA, na coluna a seguir
    com_iva_ok = None
    if iva is not None:
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
            "prova_iva": com_iva_ok, "conf_min": min(ns[i][3], ns[j][3], ns[l][3]),
            "precos_alternativos": alternativas, "preco_unidade": unidade, "outros_numeros": livres,
            # a altura da CONTA e a media das caixas que a formam, nao a da fila
            "y": (ns[i][4] + ns[j][4] + ns[l][4]) / 3.0, "_usados": usados}


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
            if NUM.match(t.split()[0] if t.split() else "") or VOL_UNID.match(t.strip()):
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


def le_pagina(caminho):
    """Uma pagina: cada codigo de artigo fica com a conta da sua linha.

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
    cadeias = [[area[k] for k in cadeia] for cadeia in _cadeias(area, passo, largura)]
    coluna = coluna_do_valor(cadeias)                     # onde esta o total nesta pagina
    for ns in cadeias:
        c = _melhor_conta(ns, coluna)
        if c:
            c.pop("_usados")
            c["y"] = ns[0][4]       # a ponta esquerda da linha, a que fica junto a descricao
            contas.append(c)
    contas.sort(key=lambda c: c["y"])
    linhas, sem_conta, sem_codigo, modo = _junta(codigos, contas, passo)
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
    if not linhas:
        # nenhuma linha pelas regras dos formatos conhecidos: tenta o leitor generico
        g = le_pagina_generica(caminho, caixas)
        if g["linhas"]:
            return g
    tr = transportes(fs)
    inicio = fim = None
    if tr and codigos:
        acima = [v for y, v in tr if y < codigos[0]["y"]]
        abaixo = [v for y, v in tr if y > codigos[-1]["y"]]
        inicio = acima[-1] if acima else 0.0
        fim = abaixo[0] if abaixo else None
    return {"ficheiro": os.path.basename(caminho), "linhas": linhas,
            "sem_conta": sem_conta, "sem_codigo": sem_codigo, "modo": modo,
            "duvidosa": bool(sem_conta or sem_codigo or modo not in MODOS_FIAVEIS),
            "transporte_inicio": inicio, "transporte_fim": fim}


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
                tol = 0.0051 + q * 0.5 * 10 ** (-_casas(ns[j][2]))
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
    taxas = [k for k in range(l + 1, len(ns)) if ns[k][1] in TAXAS_IVA
             and ("," in ns[k][2] or TAXA_PCT.match(ns[k][2]) or ISENCAO.match(ns[k][2]))]
    return {"i": i, "j": j, "l": l, "d": d, "iva": ns[taxas[0]][1] if taxas else None}


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
    return {"ficheiro": os.path.basename(caminho), "linhas": linhas, "sem_conta": [], "sem_codigo": sem_codigo,
            "modo": "generico (%d filas pela conta; referencia alinhada em %.0f%%)" % (len(itens), 100 * fraccao),
            "duvidosa": bool(sem_codigo) or fraccao < 0.8,
            "transporte_inicio": None, "transporte_fim": None}


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
# "12x90G", "12x80G", "10x500g" — a caixa dita pelo numero de embalagens e o peso de cada uma
EMBALAGENS_NA_DESCRICAO = re.compile(r"(?<!\d)(\d{1,3})\s*[X*]\s*\d{1,4}(?:[.,]\d+)?\s*(?:G|GR|KG|ML|CL|LT|L|UN)(?![A-Z])")


def unidades_da_caixa(desc):
    """Quantas unidades traz a caixa, quando a DESCRICAO o diz: "AGUA PENACOVA 1.5LT CX6" -> 6,
    "AGUA PEDRAS T/P - Cx24" -> 24, "GOMAS MELLOWS TACO TWISTY FINI 12x80G" -> 12.

    Quem usa isto nao decide nada sozinho: para um artigo que ja existe, o preco por unidade so e
    aceite se couber no custo medio da loja (propoe._propoe_artigo) — na Gelpeixe ha linhas "10x800g"
    cujo preco e por KG, e ai a divisao dava errado e e recusada."""
    t = " " + (desc or "").upper() + " "
    m = CAIXA_NA_DESCRICAO.search(t) or EMBALAGENS_NA_DESCRICAO.search(t)
    n = int(m.group(1)) if m else 0
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
        if l.get("quantidade") and l.get("valor") is not None and (l.get("desconto") or 0) > 0:
            liquido = round(l["valor"] / l["quantidade"], 4)
            if abs(liquido - (l.get("preco") or 0)) > 0.005:
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


def le_factura(caminhos):
    import qr_factura as Q
    paginas = [le_pagina(c) for c in caminhos]
    qr = None
    for c in caminhos:
        qs = Q.le_foto(c)
        if qs:
            qr = qs[0]
            break
    return {"paginas": paginas, "qr": qr}


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
