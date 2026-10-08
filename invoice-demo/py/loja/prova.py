"""ESTA FACTURA ESTA PROVADA? — a pergunta que decide se se pede ajuda a um modelo de cloud.

A regra nao e "a leitura falhou". E "nao conseguimos DEMONSTRAR que a leitura esta completa e
certa". A diferenca nao e teorica: a 23/09 o talao do Recheio de 66,51 EUR deu 8 linhas todas
correctas e faltavam-lhe duas — pela regra do erro passava, e o Pedro ficava com dois produtos sem
preco actualizado sem ninguem dar por isso. Pela regra da prova, vai a cloud.

TRES CONDICOES, todas ao mesmo tempo:

  1. AS SOMAS POR TAXA batem com o que a propria factura declara (o QR fiscal traz a base por
     escalao; e a unica coisa do documento que nao depende da nossa leitura). E esta que apanha ao
     mesmo tempo a linha que falta e a linha com o valor trocado.
  2. NENHUM CODIGO FICOU SEM LINHA (sem_conta = 0).
  3. NENHUMA CONTA FICOU SEM CODIGO (sem_codigo = 0).

A 1 sozinha nao chega: duas linhas trocadas entre si somam na mesma. A 2 e a 3 sozinhas tambem
nao: uma linha pode estar completa e com o valor mal lido. Juntas, para passarem as tres com um
erro, teriam de existir dois erros que se anulam ao centimo em todas as taxas — nao e impossivel,
e e o suficientemente improvavel para se confiar.

SEM QR, OS TOTAIS IMPRESSOS (Pedro, 25/09: "quando n ha qr temos de ir a olho e pelos totais"). O QR
continua a mandar quando existe — vem lido por maquina, nao por OCR. Quando nao existe, vale a
tabelinha "Resumo do IVA" do fundo do papel, lida por totais_factura.py, que da as mesmas bases por
taxa. Cada fila dela confirma-se a si propria (base x taxa = imposto), o que e o que distingue um
numero lido de um numero adivinhado.

Uma tabela a que o OCR perdeu uma fila declara MENOS do que as linhas lidas: a prova ve a diferenca e
a factura fica sem prova, que e o comportamento certo. Que isso nunca se inverta — o papel a provar
uma factura que o QR nao provaria — mede-se em ferramentas/mede_totais.py, nas 28 facturas que tem QR
e portanto tem resposta conhecida.

SEM QR E SEM TOTAIS LEGIVEIS NAO HA PROVA. Uma factura assim nunca fica provada, por melhor que a
leitura pareca. Isso e de proposito: e melhor pedir ajuda de mais do que gravar um preco errado.
Quanto e que isso custa em chamadas mede-se com ferramentas/mede_prova.py.

O mesmo predicado serve para aceitar a resposta da cloud. A pagina inteira vem de UMA fonte — ou a
nossa leitura ou a dela. Misturar linhas das duas e a maneira mais facil de duplicar um valor e na
mesma fechar a soma.
"""
import propoe as P
import qr_factura as Q

TOLERANCIA = 0.02          # a base: dois centimos por taxa
POR_LINHA = 0.005          # e MEIO CENTIMO POR CADA LINHA dessa taxa


def tolerancia(n_linhas):
    """Quanto e que as somas podem afastar-se sem que isso queira dizer erro de leitura.

    Nao pode ser um numero fixo. O valor de cada linha e arredondado ao centimo (pelo fornecedor e
    por nos), e esses meios centimos acumulam: numa factura de 60 linhas, so o arredondamento chega
    a 30 centimos sem que ninguem tenha lido nada de errado.

    A 23/09 isto custou-nos a factura mais dificil que temos, o rolo de 591,49 EUR: o modelo leu
    378,99 a 23% (o declarado, ao centimo) e 118,21 a 6% contra 118,24 — tres centimos em 59
    linhas. Com a tolerancia fixa de 2 centimos era recusada uma leitura correcta.

    Continua apertada onde interessa: a linha mais pequena que se ve nestas facturas vale mais de
    1 EUR, e uma taxa trocada ou um algarismo errado dao erros de euros. Tudo isso e apanhado."""
    return TOLERANCIA + POR_LINHA * max(0, n_linhas)


def somas_por_taxa(linhas):
    """O que a NOSSA leitura diz que a factura tem, por taxa. Valores sem IVA.

    UMA LINHA SEM TAXA CONTA PARA O ZERO, nunca se deita fora. O tabaco do Recheio vem "nao
    sujeito" e nao traz taxa nenhuma impressa (o PVP esta no selo fiscal): ignora-la fazia a prova
    dizer que faltavam 50,10 EUR numa factura que estava inteira e certa. E se a linha na verdade
    era de 23% e so nao lhe lemos a taxa, entao o balde do zero fica a mais e o dos 23% a menos —
    a prova falha, que e o que se quer."""
    fora = {}
    for l in linhas:
        if l.get("valor") is None:
            continue
        taxa = 0.0 if l.get("iva") is None else float(l["iva"])
        fora[taxa] = round(fora.get(taxa, 0.0) + l["valor"], 2)
    return fora


def declarado_por_taxa(qr):
    """O que a FACTURA declara, por taxa: as bases do QR fiscal."""
    if not qr:
        return None
    fora = {}
    for nome, v in (qr.get("por_taxa") or {}).items():
        if nome in P.TAXAS_QR and (v or {}).get("base"):
            fora[P.TAXAS_QR[nome]] = round(v["base"], 2)
    isenta = round((qr.get("base_isenta") or 0.0) + (qr.get("nao_sujeito") or 0.0), 2)
    if isenta:
        fora[0.0] = isenta
    return fora


def avalia(paginas, qr, impresso=None):
    """{provada, porque, faltam, ...} para uma factura ja lida (paginas = fac["paginas"]).

    `impresso` e o que totais_factura.declarado_impresso leu no papel; so se usa quando nao ha QR."""
    linhas = [l for p in paginas for l in p["linhas"]]
    sem_conta = sum(len(p.get("sem_conta") or []) for p in paginas)
    sem_codigo = sum(len(p.get("sem_codigo") or []) for p in paginas)
    r = {"linhas": len(linhas), "sem_conta": sem_conta, "sem_codigo": sem_codigo,
         "provada": False, "porque": "", "nosso": somas_por_taxa(linhas), "declarado": None,
         "faltam": {}, "referencia": None}
    if qr:
        problemas = Q.confere(qr)
        if problemas:
            r["porque"] = "o QR nao bate consigo proprio (%s)" % "; ".join(problemas)
            return r
        r["declarado"] = declarado_por_taxa(qr)
        r["referencia"] = "QR fiscal"
    elif (impresso or {}).get("por_taxa"):
        r["declarado"] = dict(impresso["por_taxa"])
        r["referencia"] = ("totais impressos (%s)" % impresso.get("de")
                           + (", total %.2f" % impresso["total"] if impresso.get("total") else ""))
    else:
        r["porque"] = ("sem QR e sem totais impressos legiveis: nao ha com que comparar" if not qr
                       else "sem QR: nao ha com que comparar")
        return r
    quantas = {}
    for l in linhas:
        t = 0.0 if l.get("iva") is None else float(l["iva"])
        quantas[t] = quantas.get(t, 0) + 1
    faltam = {}
    for taxa in set(r["declarado"]) | set(r["nosso"]):
        d = r["declarado"].get(taxa, 0.0)
        n = r["nosso"].get(taxa, 0.0)
        if abs(d - n) > tolerancia(quantas.get(taxa, 0)):
            faltam[taxa] = round(d - n, 2)
    r["faltam"] = faltam
    if faltam:
        r["porque"] = "as somas por taxa nao batem: " + ", ".join(
            "%g%% faltam %.2f" % (t, v) for t, v in sorted(faltam.items()))
        return r
    if sem_conta or sem_codigo:
        r["porque"] = "as somas batem mas ficaram %d codigos sem linha e %d contas sem codigo" % (
            sem_conta, sem_codigo)
        return r
    # SEM QR, O RESUMO IMPRESSO TEM DE FECHAR COM O TOTAL IMPRESSO (auditoria 29/09, M7). "Uma tabela
    # incompleta declara menos e a prova falha" so e verdade se o leitor tiver lido alguma linha da taxa que
    # a tabela perdeu. Se o OCR perder a fila dos 23% no resumo E o leitor nao ler nenhuma linha a 23% (24 dos
    # 43 documentos tem uma taxa com so 1 ou 2 linhas), a taxa desaparece dos dois lados e a factura ficava
    # "provada" sem essas linhas. O total impresso e o que diz que a tabela foi lida inteira.
    if not qr and not (impresso or {}).get("total"):
        r["porque"] = ("as somas batem com o resumo do IVA impresso, mas nao encontrei o TOTAL impresso que "
                       "confirme que o resumo foi lido inteiro")
        return r
    r["provada"] = True
    r["porque"] = "as somas por taxa batem com %s e nao sobrou nada" % r["referencia"]
    return r


def precisa_de_ajuda(paginas, qr, impresso=None):
    """True quando vale a pena pedir a leitura a um modelo de cloud."""
    return not avalia(paginas, qr, impresso)["provada"]
