"""Da factura a uma LISTA DE ALTERACOES de preco, para aprovar. Nao escreve nada na loja.

Duas pecas separadas de proposito: esta DECIDE e escreve a lista; outra (aplica.py) so aplica
uma lista que o Pedro aprovou. O programa que decide nunca e o que escreve — assim um erro de
decisao fica a vista numa folha antes de chegar a caixa.

REGRAS, todas deterministicas, e cada uma com a razao:

  So linhas LIGADAS por codigo ("R" + codigo do Recheio), com o IVA da factura IGUAL ao da loja e
  o custo entre 0,6x e 1,7x o custo medio. Fora disso a ligacao nao e de confianca (embalagem
  diferente, artigo errado) e nao se propoe nada.

  CUSTO SUBIU -> propoe o PVP que repoe a margem habitual da familia, arredondado para cima aos
  5 centimos. Nunca propoe um PVP abaixo do actual por causa de uma subida.

  CUSTO DESCEU -> por omissao NAO MEXE no PVP: o Pedro ganha margem e decide se quer passar a
  descida ao cliente. E nunca, em caso algum, se a linha e PROMOCAO ("Poupou com a promocao...")
  ou tem um espaco por baixo onde podia estar uma nota que o OCR nao leu — medido na factura de
  14/09: a nota da Coca-Cola 1,5L nao foi lida, e sem esta guarda o custo promocional passava por
  descida real.

  Variacoes pequenas (menos de 2% e menos de 2 centimos) nao contam: arredondamentos do
  fornecedor nao sao mudancas de preco.

  O CUSTO NOVO e sempre o da factura (ou o preco original, se for promocao). E o facto; o PVP e
  a decisao.

Uso:  python\\python.exe propoe.py 73442
"""
import json
import math
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import cruza as CZ
import linhas_factura as LF
import motor_precos as MP

LIMIAR_PCT, LIMIAR_EUR = 0.02, 0.02


def para_cima_5(v):
    return math.ceil(round(v * 100, 6) / 5.0) * 5 / 100.0


def le_factura(fotos):
    """LEITURA DUPLA quando o modelo de planificacao esta instalado (endireita.py): cada pagina e
    lida na foto original e na planificada, e as duas tem de concordar. Sem torch ou sem os pesos
    do UVDoc, fica a leitura simples de sempre — o programa nunca deixa de funcionar por causa
    do modelo."""
    try:
        import endireita as E
        E.modelo()
    except Exception:                                   # noqa: BLE001
        fac = LF.le_factura(fotos)
        fac["paginas"] = sem_sobreposicao(fac["paginas"])
        return iva_da_referencia(fac)
    import qr_factura as Q
    qr = None
    for f in fotos:
        qs = Q.le_foto(f)
        if qs:
            qr = qs[0]
            break
    # o que ja se aprendeu deste fornecedor de uma factura dele que ficou provada (formatos.py)
    formato = None
    try:
        import formatos as FM
        # COM O TIPO DE DOCUMENTO (FR/FT/FS): e assim que a memoria esta guardada (formatos.chave). Sem ele
        # procurava-se "<nif>|?" e nunca se encontrava nada — a memoria de formatos nunca foi usada ate 29/09
        # (auditoria M5)
        formato = FM.conhecido((qr or {}).get("nif_fornecedor"), (qr or {}).get("tipo"))
    except ImportError:
        pass
    fac = {"paginas": sem_sobreposicao([E.le_pagina_dupla(f, formato) for f in fotos]), "qr": qr, "formato": formato,
           "impresso": totais_impressos(fotos, qr)}
    # a taxa que a factura nao imprime em cada linha, ANTES de qualquer prova (ver iva_da_referencia)
    iva_da_referencia(fac)
    return _so_se_ajudar(_tenta_com_iva(fac, fotos, formato, E))


def _numeros_de_duas_linhas(p):
    """OS MESMOS NUMEROS EM DUAS LINHAS QUE SAO A MESMA FILA (01/10). Na borda de uma foto, ou com outro papel
    por baixo, o leitor junta um codigo aos numeros da fila do lado: no talao do Recheio a linha cortada no topo
    (115805.1, custo 0,49) ficou com os numeros da seguinte (0,85), e o "5530" de uma factura por baixo ficou
    com os do tomate 115740.0. Duas linhas com quantidade, preco e valor iguais a menos de meia fila de
    distancia sao UMA fila de numeros reclamada por dois codigos. Se um deles foi visto nas duas leituras
    (original e planificada) e o outro so numa, fica o confirmado; senao nao se sabe qual e e saem os dois
    para "sem conta" (ligaveis, a pedir o custo). Duas linhas iguais em filas diferentes (os dois noodles,
    8 x 0,63) estao a uma fila inteira de distancia e ficam."""
    ls = [l for l in p["linhas"] if l.get("y") is not None]
    ys = sorted(l["y"] for l in ls)
    passos = sorted(b - a for a, b in zip(ys, ys[1:]) if b - a > 5)
    if len(passos) < 3:
        return
    # a distancia de UMA fila: o primeiro quartil dos intervalos, nao a mediana. Numa foto mal lida faltam muitas
    # linhas, os intervalos medem duas e tres filas, e com a mediana os dois noodles (8 x 0,63, filas seguidas)
    # pareciam a mesma fila e saiam os dois
    meia = 0.6 * passos[len(passos) // 4]
    fora = set()
    for i, x in enumerate(ls):
        for z in ls[i + 1:]:
            if (x["quantidade"], x["preco"], x["valor"]) != (z["quantidade"], z["preco"], z["valor"]) or \
               str(x["codigo"]) == str(z["codigo"]) or abs(x["y"] - z["y"]) >= meia:
                continue
            vx, vz = len(x.get("vista_em") or []), len(z.get("vista_em") or [])
            if vx != vz:
                fora.add(id(z) if vx > vz else id(x))
            else:
                fora.update((id(x), id(z)))
    if fora:
        p.setdefault("sem_conta", [])
        p["sem_conta"] += [{"codigo": str(l["codigo"]), "descricao": l["descricao"],
                            "porque": "numeros iguais aos da linha vizinha"} for l in p["linhas"] if id(l) in fora]
        p["linhas"] = [l for l in p["linhas"] if id(l) not in fora]


def sem_sobreposicao(paginas):
    """FOTOS QUE SE SOBREPOEM (Pedro, 01/10): um talao comprido fotografa-se as metades, e a segunda foto
    apanha sempre umas linhas do fim da primeira. No talao do Recheio de 01/10 eram 21, contadas duas vezes,
    e a factura nunca se provava (sobravam 105 EUR a 23%).

    So se tira o que tem a forma de uma sobreposicao: linhas IGUAIS (codigo, quantidade, preco e valor) que
    sao o FUNDO de uma foto e o TOPO da seguinte, e pelo menos duas. Uma linha repetida a meio de uma pagina
    nao e sobreposicao (pode ser a mesma compra duas vezes) e fica. Quem confirma e a prova de sempre: se o
    corte estivesse errado, as somas deixavam de bater com o QR."""
    for p in paginas:
        _numeros_de_duas_linhas(p)
    chave = lambda l: (str(l["codigo"]), l["quantidade"], l["preco"], l["valor"])
    for a, b in zip(paginas, paginas[1:]):
        if not a["linhas"] or not b["linhas"]:
            continue
        comuns = {chave(l) for l in a["linhas"]} & {chave(l) for l in b["linhas"]}
        if len(comuns) < 2 or any(l.get("y") is None for l in a["linhas"] + b["linhas"]):
            continue
        # a ULTIMA linha da foto de cima e a PRIMEIRA da de baixo sao das repetidas, e na de baixo as repetidas
        # vem todas antes das outras. Na de cima pode haver no meio uma linha que a de baixo nao leu (211291.1).
        ultima_a = max(a["linhas"], key=lambda l: l["y"])
        topo_b = max(l["y"] for l in b["linhas"] if chave(l) in comuns)
        if chave(ultima_a) not in comuns or chave(min(b["linhas"], key=lambda l: l["y"])) not in comuns or \
           any(l["y"] < topo_b for l in b["linhas"] if chave(l) not in comuns):
            continue                                       # os iguais estao misturados: nao e sobreposicao
        b["linhas"] = [l for l in b["linhas"] if chave(l) not in comuns]
        b["sobreposicao"] = len(comuns)
    # um codigo que ficou "sem conta" numa foto mas foi lido com os numeros noutra ja esta na factura
    lidos = {str(l["codigo"]) for p in paginas for l in p["linhas"]}
    for p in paginas:
        if p.get("sem_conta"):
            p["sem_conta"] = [k for k in p["sem_conta"] if str(k.get("codigo") or "") not in lidos]
    return paginas


def totais_impressos(fotos, qr):
    """Os totais IMPRESSOS no papel, para servirem de juiz quando nao ha QR (Pedro, 25/09).

    So se le quando nao ha QR: o QR e melhor referencia (vem lido por maquina) e ler o papel a mais
    nao acrescenta nada. Usa o OCR que ja esta em cache, por isso nao custa tempo nenhum."""
    if qr:
        return None
    try:
        import linhas_factura as LFX
        import totais_factura as TF
        return TF.declarado_impresso([LFX.ocr(f) for f in fotos])
    except Exception:                                      # noqa: BLE001 — sem totais fica como estava
        return None


def _so_se_ajudar(fac):
    """As linhas montadas PELA GRELHA so ficam se aproximarem a factura do que o QR declara.

    A grelha (linhas_factura.pela_grelha) recupera filas que o encadeamento perdeu, juntando
    numeros ja lidos pela coluna a que pertencem. Na factura dificil ganhou tres linhas e encurtou
    a distancia ao declarado em 10 EUR. Mas noutra (Poupanca, 18/09) ganhou duas e AFASTOU as somas:
    a factura falhava por 1,90 e passou a falhar por 0,70 mais 2,84.

    Mais linhas nao e o mesmo que linhas certas — ja custou caro hoje. Por isso a grelha propoe e o
    QR dispoe: mede-se a distancia as bases declaradas com e sem as linhas dela, e ficam so se
    encurtarem. Sem juiz nenhum nao se arrisca: ficam de fora. Desde 25/09 o juiz pode ser tambem o
    resumo do IVA impresso no papel, para as facturas sem QR."""
    tem = [l for p in fac["paginas"] for l in p["linhas"] if l.get("da_grelha")]
    if not tem:
        return fac
    try:
        import prova as PR
    except ImportError:
        return fac

    def distancia(paginas):
        r = PR.avalia(paginas, fac.get("qr"), fac.get("impresso"))
        if not r.get("declarado"):
            return None
        return sum(abs(r["declarado"].get(t, 0.0) - r["nosso"].get(t, 0.0))
                   for t in set(r["declarado"]) | set(r["nosso"]))

    com = distancia(fac["paginas"])
    sem_paginas = [dict(p, linhas=[l for l in p["linhas"] if not l.get("da_grelha")])
                   for p in fac["paginas"]]
    sem = distancia(sem_paginas)
    if com is None or sem is None or com > sem:
        fac["paginas"] = sem_paginas
        fac["grelha_recusada"] = len(tem)
    return fac


def _tenta_com_iva(fac, fotos, formato, E):
    """SEGUNDA LEITURA a tratar a coluna do valor como se levasse IVA — e fica-se com ela SO se
    provar contra o QR.

    O leitor decide pagina a pagina se a coluna do valor traz IVA, e precisa de tres linhas que so
    fechem assim para se decidir. Num talao mal fotografado, onde poucas linhas fecham, nunca la
    chega e assume o caso comum (sem IVA) — e ai nao fecha nenhuma, porque o talao e c/IVA.

    A tentacao e escolher "a maneira que da mais linhas". Nao se faz: a 24/09 essa regra ganhou
    quatro linhas numa factura da Poupanca e estragou-lhe as contas em 25 EUR. Aqui quem decide e a
    prova — se a releitura fechar as somas com a referencia, e porque estava certa; se nao fechar,
    fica tudo como estava e nao se perdeu nada.

    A REFERENCIA PODE SER O PAPEL (25/09). Ate aqui isto so corria com QR, e era exactamente a
    factura errada a ficar de fora: o talao de 591,49 EUR (20260923_113358) e c/IVA, o QR dessa foto
    nao se le, e sem QR nao se tentava a releitura — a pagina ficava com zero linhas. Com o resumo do
    IVA impresso ha juiz, e um juiz que se confirma a si proprio."""
    if (formato or {}).get("valor_com_iva"):
        return fac
    if not fac.get("qr") and not (fac.get("impresso") or {}).get("por_taxa"):
        return fac
    try:
        import prova as PR
    except ImportError:
        return fac
    if PR.avalia(fac["paginas"], fac.get("qr"), fac.get("impresso"))["provada"]:
        return fac
    forcado = dict(formato or {}, valor_com_iva=True)
    try:
        outra = {"paginas": sem_sobreposicao([E.le_pagina_dupla(f, forcado) for f in fotos]),
                 "qr": fac.get("qr"), "formato": fac.get("formato"), "impresso": fac.get("impresso")}
        iva_da_referencia(outra)      # a releitura tambem precisa da taxa antes de ser julgada
    except Exception:                                    # noqa: BLE001
        return fac
    r = PR.avalia(outra["paginas"], fac.get("qr"), fac.get("impresso"))
    if r["provada"]:
        for p in outra["paginas"]:
            p["modo"] += " + valor c/IVA (provado pel%s)" % ("o QR" if fac.get("qr") else "os totais impressos")
        return outra
    return fac


TAXAS_QR = {"reduzida": 6.0, "intermedia": 13.0, "normal": 23.0}


def _iva_do_qr(linhas, qr, impresso=None):
    """A FACTURA QUE NAO IMPRIME A TAXA EM CADA LINHA: se a referencia so declara UMA taxa com base, e
    essa a taxa de todas as linhas — nao ha nada a escolher. So se aplica quando NENHUMA linha trouxe
    taxa (uma factura com duas taxas e sem coluna nao se adivinha). GENIALIS 17/09: 23% em tudo, e sem
    isto as linhas ficavam sem IVA e nao se podia propor preco nenhum.

    A referencia e o QR quando o ha, senao o resumo do IVA impresso (25/09) — a regra e a mesma."""
    if not linhas or any(l.get("iva") is not None for l in linhas):
        return linhas
    if qr:
        taxas = [TAXAS_QR[k] for k, v in (qr.get("por_taxa") or {}).items()
                 if k in TAXAS_QR and (v or {}).get("base")]
        if (qr.get("base_isenta") or 0) > 0:
            taxas.append(0.0)
    else:
        taxas = sorted((impresso or {}).get("por_taxa") or {})
    if len(taxas) == 1:
        for l in linhas:
            l["iva"] = taxas[0]
            l["iva_do_qr"] = True
    return linhas


def iva_da_referencia(fac):
    """Preenche a taxa das linhas de uma factura ja lida, pela referencia dela.

    TEM DE CORRER ANTES DE QUALQUER PROVA. Ate 25/09 so corria no fim, em `propoe`, depois de a prova
    ja ter decidido se valia a pena chamar a cloud — e a factura da Batista (52027), que nao imprime a
    taxa em linha nenhuma, ficava com as 11 linhas no balde do 0%: a prova via 132,72 a 0% contra
    128,74 a 23% e mandava-a para a cloud, quando a leitura local estava certa e so faltava dizer-lhe a
    taxa. Preenchida a taxa, sobra uma diferenca de 3,98 — essa e real, e outra coisa."""
    linhas = [l for p in fac.get("paginas") or [] for l in p.get("linhas") or []]
    _iva_do_qr(linhas, fac.get("qr"), fac.get("impresso"))
    return fac


def _sugestoes_da_linha(l):
    """As sugestoes procuradas com OS DOIS custos da linha: o da factura e o da unidade.

    Um custo so nao chega para os dois casos, e sao ambos reais:
      GENIALIS, 18/09 — a factura vende a caixa a 7,68 e o artigo da loja custa 0,50. Procurar com
        7,68 deitava fora todas as sugestoes; por isso passou-se a procurar com o custo da unidade.
      Lusiaves, 23/09 — a coluna "Unid." da factura ("4UN") foi colada a descricao, o programa leu
        "embalagem de 4" e procurou a MARINADA PIMENTAO FRANGO (que a loja tem, a 4,35) com 3,15/4 =
        0,79. Vieram salsichas e gelatinas. Com 3,15 a certa vem em primeiro lugar.
    Procura-se com os dois e juntam-se, sem repetir artigos: nenhum dos casos volta a perder-se."""
    import ligar as LG
    custos = [l["preco"]]
    for c in (l.get("preco_unidade"), l.get("preco_liquido")):
        if c and all(abs(c - x) > 0.005 for x in custos):
            custos.append(c)
    fora, vistos = [], set()
    for c in custos:
        for s in LG.sugestoes(l["descricao"], l["iva"], c, LG.loja()) or []:
            if s.get("artigo") not in vistos:
                vistos.add(s.get("artigo"))
                fora.append(s)
    return fora


def _recurso_cloud(fotos, fac, nome):
    """Na versao publica nao ha leitura por um modelo de cloud: a factura fica com a leitura local.

    No programa da loja, uma factura que a leitura local nao conseguia provar podia ser lida tambem por um
    modelo de cloud, e so era aceite se fechasse as somas por taxa com o QR. Essa parte nao faz parte desta
    copia: uma factura nao provada segue marcada por confirmar, para uma pessoa ver."""
    return {"usada": False, "porque": "versao publica: sem leitura na cloud"}


def propoe(fotos, nome, nif_dito=None):
    """nif_dito: o fornecedor dito A MAO na app, para uma factura sem QR (servidor.diz_fornecedor). So vale
    quando o QR nao traz NIF — o QR, lido por maquina, manda sempre."""
    c = MP.ligar()
    arts = CZ.artigos_por_id(c)
    vend = MP.vendas(c)
    lista = [dict(id=k, desc=v["desc"], fam=v["fam"], custo=v["custo"], pvp=v["pvp"],
                  iva=v["iva"] or 0.0, fam_desc="", ean="") for k, v in arts.items()]
    fams, loja = MP.referencias(lista)
    fac = le_factura(fotos)
    for p, f in zip(fac["paginas"], fotos):                 # para o aviso de letra pequena (servidor.provas)
        p["letra_px"] = LF.letra_px(f)
    fac["cloud"] = _recurso_cloud(fotos, fac, nome)
    nif = (fac.get("qr") or {}).get("nif_fornecedor") or nif_dito
    linhas = [l for p in fac["paginas"] for l in p["linhas"]]
    # ja foi preenchida em le_factura, antes das provas; aqui so apanha as linhas que vieram da cloud
    iva_da_referencia(fac)
    sem_ligar = sum(len(p["sem_codigo"]) + len(p["sem_conta"]) for p in fac["paginas"])
    import ligar as LG
    mem = LG.memoria()
    # CODIGO COM UM ALGARISMO A MENOS (E0009, 01/10): repara-se se so um codigo conhecido deste fornecedor
    # encaixa e a descricao confirma; senao a linha vai marcada e a ligacao dela nao entra na memoria
    conhecidos = LG.codigos_conhecidos(nif, arts, mem) if nif else {}
    for l in linhas + [k for p in fac["paginas"] for k in p.get("sem_conta") or []]:
        novo, como = LG.repara_codigo(nif, l.get("codigo") or "", l.get("descricao"), conhecidos)
        if como == "reparado":
            l["codigo_lido"], l["codigo"] = l["codigo"], novo
        elif como == "incompleto":
            l["codigo_incompleto"] = True
    fora = []
    for idx, l in enumerate(linhas):
        # deposito de embalagens (Volta): nao e mercadoria. 888879 no Recheio; na Poupanca o
        # codigo muda (61792), por isso vale tambem a descricao
        import loja_config as LC
        if LC.e_codigo_de_deposito(l["codigo"]) or "DEPOSITO" in l["descricao"].upper().replace(" ", ""):
            continue
        # LIGACAO, so pelas vias certas: memoria confirmada (NIF + codigo) e depois a regra do codigo da
        # loja (config\loja.json). SEM QR NAO HA NIF E NAO SE LIGA NADA (auditoria 22/09 M12): antes o
        # "R"+codigo valia para qualquer fornecedor e duas linhas de outro caiam em artigos "R". Diz-se de
        # quem e a factura na app (fornecedor a olho) e refaz-se a proposta.
        ids, origem = LG.liga(nif, l["codigo"], arts, mem) if nif else ([], None)
        base_r = {"idx": idx, "cod_fornecedor": l["codigo"], "desc_factura": l["descricao"],
                  "custo_factura": l["preco"], "quantidade": l["quantidade"], "iva_factura": l["iva"],
                  "promo": bool(l.get("promo")), "preco_original": l.get("preco_original"),
                  "texto_por_baixo": bool(l.get("texto_por_baixo")), "origem_ligacao": origem,
                  # vao em TODAS as linhas: uma "sem ligacao" pode ser ligada mais tarde pelo codigo de
                  # barras, e a decisao de preco nessa altura tem de ver as mesmas guardas
                  "discordancia": l.get("discordancia"), "precos_alternativos": l.get("precos_alternativos") or [],
                  # preco POR UNIDADE quando a factura vende a caixa (ver linhas_factura.precos_por_unidade)
                  "custo_unidade": l.get("preco_unidade"), "unidades_caixa": l.get("unidades_caixa"),
                  # lote e outras referencias da linha: o lote tambem vem impresso na embalagem
                  "outros_numeros": l.get("outros_numeros") or []}
        if l.get("codigo_lido"):
            base_r["codigo_lido"] = l["codigo_lido"]
        if l.get("codigo_incompleto"):
            base_r["codigo_incompleto"] = True
        if not ids:
            r = dict(base_r, artigo=None, desc_loja=None, vendidos_90d=0, accao="sem ligacao",
                     motivo="codigo do fornecedor ainda nao ligado a um artigo da loja",
                     sugestoes=_sugestoes_da_linha(l))
            fora.append(r)
            continue
        for aid in ids:
            fora.extend(_propoe_artigo(dict(base_r), l, aid, arts, vend, fams, loja))
    # AS LINHAS QUE NAO FECHARAM A CONTA (codigo e descricao lidos, numeros que nao batem) tambem entram, sem
    # custo. 30/09: "ALMONDEGAS BOVINO ... 5 UN x 27,50 = 27,50" (o preco era o da embalagem de 5) ficou fora da
    # proposta, e fotografar o codigo de barras nao tinha linha nenhuma a que ligar. O leitor continua a nao
    # adivinhar numeros: a linha entra so para se poder LIGAR, e o custo diz-o a pessoa (servidor.decisao_preco).
    idx = len(linhas)
    for p in fac["paginas"]:
        for k in p.get("sem_conta") or []:
            cod, desc = str(k.get("codigo") or "").strip(), str(k.get("descricao") or "").strip()
            if not cod or "DEPOSITO" in desc.upper().replace(" ", ""):
                continue
            ids, origem = LG.liga(nif, cod, arts, mem) if nif else ([], None)
            base_r = {"idx": idx, "cod_fornecedor": cod, "desc_factura": desc, "custo_factura": None,
                      "quantidade": None, "iva_factura": None, "sem_conta": True, "origem_ligacao": origem,
                      "promo": False, "preco_original": None, "texto_por_baixo": False, "discordancia": None,
                      "precos_alternativos": [], "custo_unidade": None, "unidades_caixa": None, "outros_numeros": []}
            if k.get("codigo_lido"):
                base_r["codigo_lido"] = k["codigo_lido"]
            if k.get("codigo_incompleto"):
                base_r["codigo_incompleto"] = True
            idx += 1
            motivo = ("os numeros desta linha nao fecham a conta (quantidade x preco = valor): confere o custo na "
                      "factura e escreve-o")
            if not ids:
                fora.append(dict(base_r, artigo=None, desc_loja=None, vendidos_90d=0, accao="sem ligacao",
                                 motivo="linha que nao fechou a conta; " + motivo))
            for aid in ids:
                a = arts.get(aid)
                fora.append(dict(base_r, artigo=aid, desc_loja=a["desc"] if a else None,
                                 vendidos_90d=vend.get(aid, 0), accao="nao mexer", pede_custo=True, motivo=motivo))
    # DUAS LINHAS DESTA FACTURA PARA O MESMO ARTIGO, com custos diferentes: nenhuma grava sozinha. O "Aplicar
    # precos" guarda uma decisao por artigo e o aplica.ps1 so le a primeira linha — a outra perdia-se sem
    # aviso, ou (pelo codigo de barras) a segunda gravava por cima da primeira (auditoria C1, 22/09).
    por_artigo = {}
    for r in fora:
        if r.get("artigo") and r.get("accao") in ACCOES_COM_PRECO:
            por_artigo.setdefault(r["artigo"], []).append(r)
    for aid, rs in por_artigo.items():
        custos = sorted({round(x["custo_novo"], 2) for x in rs})
        if len(custos) > 1:
            for x in rs:
                x.update(accao="nao mexer", pede_confirmacao=True,
                         motivo="esta factura tem %d linhas para o artigo %s com custos diferentes (%s): "
                                "escolhe qual fica" % (len(rs), aid, " / ".join("%.2f" % v for v in custos)))
    return fac, fora, sem_ligar


ACCOES_COM_PRECO = ("SUBIR PVP", "subiu, PVP chega", "desceu", "igual", "primeiro custo")
SALTO_AVISO = 0.30          # como o $SALTO_MAX do aplica.ps1: acima disto a mudanca e mostrada a vermelho


def _propoe_artigo(r, l, aid, arts, vend, fams, loja):
    """A decisao (_decide) com o AVISO de mudanca grande a vista. Antes o aviso so existia no texto do
    aplica.ps1, que a app mostra dentro de um "detalhe" fechado: o custo das BOLACHAS CORAL desceu 33%
    (22/09) sem ninguem o ver (auditoria, C1)."""
    fora = _decide(r, l, aid, arts, vend, fams, loja)
    for x in fora:
        if x.get("accao") not in ACCOES_COM_PRECO or not (x.get("custo_medio") or 0) > 0:
            continue
        partes = []
        dc = x["custo_novo"] / x["custo_medio"] - 1
        if abs(dc) > SALTO_AVISO:
            partes.append("custo %+.0f%% (%.2f -> %.2f)" % (100 * dc, x["custo_medio"], x["custo_novo"]))
        pvp_novo = x.get("pvp_proposto") if x["accao"] == "SUBIR PVP" else x.get("pvp_actual")
        if pvp_novo and (x.get("pvp_actual") or 0) > 0 and abs(pvp_novo / x["pvp_actual"] - 1) > SALTO_AVISO:
            partes.append("PVP %+.0f%% (%.2f -> %.2f)" % (100 * (pvp_novo / x["pvp_actual"] - 1), x["pvp_actual"], pvp_novo))
        if partes:
            x["aviso"] = "mudanca grande: " + "; ".join(partes) + " — confere na factura"
    return fora


def _decide(r, l, aid, arts, vend, fams, loja):
    """A decisao de preco para UMA linha ja ligada a UM artigo. Um codigo de fornecedor pode servir
    varios artigos (o CIF Lava Tudo e o Marinho e o Limao): cada um tem a sua decisao."""
    a = arts.get(aid)
    r.update(artigo=aid, desc_loja=a["desc"] if a else None, vendidos_90d=vend.get(aid, 0))
    if not a:
        # ligado na memoria mas ainda nao na copia das caixas: artigo criado e por enviar
        r.update(accao="artigo novo por enviar",
                 motivo="ligado ao artigo %s, que ainda nao chegou as caixas (falta actualizar)" % aid)
        return [r]
    # o custo e o que se PAGA: com desconto na linha vale o liquido (GENIALIS: 7,68 -10% = 6,91)
    custo_novo = l.get("preco_original") or l.get("preco_liquido") or l["preco"]
    # PRECO DA CAIXA OU PRECO DA UNIDADE? A factura traz os dois (coluna "Preco UN" da Gelpeixe, ou
    # "CX6" na descricao da MINIMATOS); a loja e que sabe como vende o artigo, e o custo medio dela
    # decide sem se adivinhar nada: fica o preco que cabe na ordem de grandeza do custo actual.
    # Medido nos custos confirmados: choco 6,48 (caixa de 800g) e nao 8,10 (o kg); pescada 8,95 (o
    # kg) e nao 53,70 (a caixa de 6 kg); agua Penacova 0,31 (garrafa) e nao 1,86 (caixa de 6).
    # ---- A LINHA E UMA CAIXA? Quatro sinais, e podem discordar. A ordem e esta (22/09):
    #   1. a pessoa, agora (o botao "dividir por N") — trata-se mais abaixo, e manda sempre;
    #   2. a MEMORIA: o que uma pessoa ja disse deste codigo deste fornecedor (1 = "nao dividir");
    #   3. a COLUNA de preco unitario que a factura traz (ou a divisao que a leitura ja fez);
    #   4. a CONTA: o custo da linha e um multiplo inteiro, ao centimo, do custo que a loja ja paga
    #      ("CHEETOSPANDILHA031TIR(006UN)" 4,92 = 6 x 0,82);
    #   5. a DESCRICAO ("CX6", "006UN", "12x80G") — o sinal mais fraco: na mesma factura, "CHEETOS
    #      FUTEBOLAS130G 6PC" a 1,62 nao e caixa nenhuma, e "PENSO RAPIDO 30UN" sao 30 pensos numa caixa so.
    # A conta ganha a coluna e a descricao quando elas nao cabem no custo da loja e ela bate certo. Se a
    # MEMORIA e a CONTA discordarem, nao se grava sozinho: pergunta-se (pede_confirmacao).
    # E PERGUNTA-SE SEMPRE A PRIMEIRA VEZ (decisao do Pedro, 22/09): dividir ou nao dividir muda o custo do
    # artigo, por isso nenhuma conta decide isso sozinha — o programa propoe, a pessoa confirma. Da segunda
    # vez ja nao pergunta: a resposta fica guardada para aquele codigo daquele fornecedor.
    cabe = lambda x: a["custo"] > 0 and CZ.RAZAO_MIN <= x / a["custo"] <= CZ.RAZAO_MAX
    n_conta = None
    if a["custo"] > 0 and custo_novo > 0:
        k = int(round(custo_novo / a["custo"]))
        if 2 <= k <= 144 and abs(custo_novo / k - a["custo"]) <= 0.02 * a["custo"]:
            n_conta = k
    # A CONTA SO VALE PARA O MESMO PRODUTO (01/10, registo de erros E0015): o PACK BUONDI DOLCE GUSTO 48CAPS a 10,99,
    # ligado por engano ao R119429 AZEITONA (custo 0,65), deu "caixa de 17" porque 10,99 = 17 x 0,65 — uma
    # coincidencia — e o custo do cafe foi gravado na azeitona. Sem NENHUMA palavra em comum entre a factura e o
    # artigo, um multiplo do custo nao prova caixa nenhuma: nao se propoe dividir.
    if n_conta:
        import ligar as LG
        if not LG.palavras_em_comum(l["descricao"], a["desc"]):
            n_conta = None
            r["caixa_sem_palavras"] = True
    n_mem, n_txt = l.get("unidades_memoria"), l.get("unidades_texto") or l.get("unidades_caixa")
    col = l.get("preco_unidade")
    unidade, duvida, origem = col, False, "coluna da factura" if col else ""
    if n_mem:                                            # o que uma pessoa ja disse vale mais
        unidade = round(custo_novo / n_mem, 4) if n_mem > 1 else None
        origem = "ja confirmado neste codigo do fornecedor"
        r["unidades_caixa"] = n_mem if n_mem > 1 else None
    elif n_conta and (not unidade or not cabe(unidade)):  # a conta so perde para a pessoa e para a memoria
        unidade = round(custo_novo / n_conta, 4)
        origem = "a conta: %s = %d x %.2f" % (("%.2f" % custo_novo), n_conta, custo_novo / n_conta)
        r["unidades_caixa"], r["caixa_pela_conta"] = n_conta, True
    elif not unidade and n_txt:
        unidade = round(custo_novo / n_txt, 4)
        origem = "a descricao da factura"
        r["unidades_caixa"] = n_txt
    if origem:
        r["caixa_porque"] = origem
    if unidade:
        r["custo_unidade"] = unidade
    if n_mem and n_conta and n_mem != n_conta and not l.get("escolha"):
        r["pede_confirmacao"] = True
        r["conflito_caixa"] = "ja tinhas dito %s, mas a conta desta factura da %s" % (
            "para nao dividir" if n_mem == 1 else "caixa de %d" % n_mem, "caixa de %d" % n_conta)
    # A PESSOA DISSE (botao "dividir pela caixa" no telemovel, 21/09): "unidade" = a factura e a caixa de
    # N e a loja vende a unidade; "caixa" = o preco da factura e o de UMA embalagem que se vende assim
    # (pensos com "24" no nome). Sem isto, num artigo sem custo nada decidia e ficava "nao mexer".
    escolha = l.get("escolha")
    n_pedido = r.get("unidades_caixa") or l.get("unidades_caixa") or n_conta or n_txt
    if escolha == "unidade" and not unidade and n_pedido:
        unidade = round(custo_novo / n_pedido, 4)
        r["unidades_caixa"] = n_pedido
    if escolha == "unidade" and unidade:
        r["custo_da_caixa"] = custo_novo
        r["preco_caixa"] = l.get("preco_original") or l["preco"]
        custo_novo = unidade
        r["por_unidade"] = True
    elif escolha == "caixa":
        if unidade:
            r["preco_caixa"] = l.get("preco_original") or l["preco"]
    elif unidade and a["custo"] > 0 and abs(unidade - custo_novo) > 0.02:
        cabe_linha = CZ.RAZAO_MIN <= custo_novo / a["custo"] <= CZ.RAZAO_MAX
        cabe_unidade = CZ.RAZAO_MIN <= unidade / a["custo"] <= CZ.RAZAO_MAX
        perto_linha = abs(custo_novo - a["custo"]) / a["custo"]
        perto_unidade = abs(unidade - a["custo"]) / a["custo"]
        if cabe_unidade and (not cabe_linha or perto_unidade * 2 <= perto_linha):
            # o preco da unidade cabe, e o da caixa nao — ou esta MUITO mais perto do custo que a loja
            # ja tem (choco: 6,48 contra 6,48 de custo medio, e a caixa a 8,10). Mostra-se ja dividido,
            # mas e uma PROPOSTA: falta a pessoa confirmar (a menos que ja o tenha dito neste codigo).
            r["custo_da_caixa"] = custo_novo
            custo_novo = unidade
            r["por_unidade"] = True
            if not n_mem:
                r["pergunta_caixa"] = True
        else:
            duvida = cabe_unidade and cabe_linha and perto_linha * 2 > perto_unidade
        r["preco_caixa"] = l.get("preco_original") or l["preco"]
    r.update(custo_medio=a["custo"], custo_novo=custo_novo, pvp_actual=a["pvp"],
             iva=a["iva"], familia=a["fam"], escolha=escolha)
    if r.get("conflito_caixa") and not l.get("confirmado"):
        # a memoria e a conta discordam: quem decide e a pessoa (e a escolha dela fica guardada)
        r.update(accao="nao mexer", motivo="as unidades da caixa nao batem certo: %s — diz tu qual e"
                                           % r["conflito_caixa"])
        return [r]
    if r.get("pergunta_caixa"):
        # PRIMEIRA VEZ NESTE CODIGO DESTE FORNECEDOR: o programa propoe dividir, a pessoa e que diz que sim
        r.update(accao="nao mexer", pede_escolha=True,
                 motivo="esta linha parece uma caixa de %d (%s): o custo de cada unidade fica %.2f. Confirma "
                        "com \"dividir o custo por %d\" — ou desmarca, se o preco da factura e de uma "
                        "embalagem que vendes assim. Fica guardado para este codigo deste fornecedor."
                        % (r.get("unidades_caixa") or 0, r.get("caixa_porque") or "", custo_novo,
                           r.get("unidades_caixa") or 0))
        return [r]
    if duvida:
        r["pede_escolha"] = True
        r.update(accao="nao mexer", precos_possiveis=[custo_novo, unidade],
                 motivo="a factura da o preco da caixa (%.2f) e o da unidade (%.2f) e os dois servem "
                        "para este artigo — confirma qual e o custo" % (custo_novo, unidade))
        return [r]
    import ligar as LG
    if LG.TABACO.search(l["descricao"]) or LG.TABACO.search(a["desc"]):
        # o tabaco tem o PVP impresso no selo fiscal (DL 346/85 na factura): nunca se propoe preco
        r.update(accao="nao mexer", motivo="tabaco: o PVP e o do selo fiscal; so conta o custo (%.2f)" % custo_novo)
        return [r]
    # ARTIGO GENERICO (muitos codigos de barras, "por preco"): o custo desta linha e o de UM dos produtos
    # que ele junta, nao o do artigo. So com confirmacao da pessoa (auditoria C1: BOLACHAS CORAL, 22/09).
    n_cod = LG.e_generico(aid, LG.loja())
    if n_cod and not l.get("confirmado"):
        r.update(accao="nao mexer", pede_confirmacao=True, generico=n_cod,
                 motivo="artigo generico (%d codigos de barras): o custo desta linha (%.2f) e o de um dos produtos "
                        "que ele junta, nao o do artigo — so se grava se confirmares" % (n_cod, custo_novo))
        return [r]
    if l.get("discordancia"):
        # as duas leituras (foto original e planificada) deram numeros diferentes a este codigo
        r.update(accao="nao mexer", precos_possiveis=[l["preco"]] + (l.get("precos_alternativos") or []),
                 motivo="as duas leituras da foto nao concordam (%s) — confirma na factura"
                        % l["discordancia"])
        return [r]
    if l.get("precos_alternativos"):
        # a mesma linha da o mesmo total com dois precos (preco ao kg e a caixa, na Gelpeixe)
        r.update(accao="nao mexer", precos_possiveis=[l["preco"]] + l["precos_alternativos"],
                 motivo="a linha da dois precos possiveis: %s — confirma qual e o custo"
                        % " ou ".join("%.2f" % x for x in [l["preco"]] + l["precos_alternativos"]))
        return [r]
    if l["iva"] is not None and a["iva"] is not None and abs(l["iva"] - a["iva"]) > 0.01:
        # iva_diferente/iva_loja: a app mostra o botao "usar o IVA da factura" nesta linha (01/10)
        r.update(accao="nao mexer", motivo="IVA %g%% na factura e %g%% na loja" % (l["iva"], a["iva"]),
                 iva_diferente=True, iva_loja=a["iva"])
        return [r]
    if a["custo"] <= 0:
        # O ARTIGO AINDA NAO TEM CUSTO (criado a mao so com PVP): nao ha custo medio com que comparar, e a
        # guarda 0,6x-1,7x nao pode decidir nada. Decide a pessoa: unidade ou caixa. Depois disso fica o
        # custo; o PVP fica se cobrir o custo com IVA, senao propoe-se com a margem da familia.
        # SEM NADA A DIZER CAIXA (05/10, Pedro: "faz com que nao de erro"): Lava Tudo 2L a 0,70 e Dove 720ml a 3,59,
        # artigos criados na caixa sem custo, eram recusados a pedir "unidade ou caixa?" sem nenhum sinal de caixa. Se
        # a linha nao fala de caixa (descricao, coluna por unidade, memoria), o preco conta como o de 1 unidade — dito
        # a vista no motivo. Com um sinal de caixa continua a perguntar. A guarda de baixo fica: se o PVP nao cobrir o
        # custo com IVA (um preco de caixa passado por unidade), propoe-se subir e a pessoa ve-o.
        sinal_caixa = unidade or n_txt or n_mem or r.get("unidades_caixa")
        if not escolha and not sinal_caixa:
            escolha = "caixa"
            r["escolha"] = escolha
            r["custo_como_unidade"] = True
        if not escolha:
            r.update(accao="nao mexer", pede_escolha=True,
                     motivo="o artigo ainda nao tem custo: diz se os %.2f da factura sao o custo de uma "
                            "unidade que vendes ou de uma caixa" % custo_novo)
            return [r]
        ref = (fams.get(a["fam"]) or loja)["mediana"]
        com_iva = custo_novo * (1 + a["iva"] / 100.0)
        if a["pvp"] >= com_iva:
            margem = a["pvp"] / com_iva - 1
            r["margem_actual_custo_novo"], r["margem_habitual"] = margem, ref
            r.update(accao="primeiro custo",
                     motivo="o artigo nao tinha custo: fica %.2f%s%s; o PVP %.2f cobre-o com margem de %.0f%%"
                            % (custo_novo, " (a caixa a dividir por %d)" % l["unidades_caixa"]
                               if r.get("por_unidade") and l.get("unidades_caixa") else "",
                               " (o preco da factura, como de 1 unidade: a linha nao fala de caixa)"
                               if r.get("custo_como_unidade") else "",
                               a["pvp"], 100 * margem))
            if margem < ref - 0.05:
                # cobrir o custo nao chega: 1,80 sobre 1,45 com IVA da 1% (Ice Tea Manga, 21/09)
                r["motivo"] += " — abaixo da familia (%.0f%%): rever o PVP (com a margem da familia seria %.2f)" % (
                    100 * ref, para_cima_5(com_iva * (1 + ref)))
        else:
            r.update(accao="SUBIR PVP", pvp_proposto=para_cima_5(com_iva * (1 + ref)),
                     motivo="o artigo nao tinha custo: fica %.2f, e o PVP %.2f nao chega ao custo com IVA "
                            "(%.2f) — proposto com a margem da familia (%.0f%%)" % (custo_novo, a["pvp"], com_iva, 100 * ref))
        return [r]
    if not (CZ.RAZAO_MIN <= custo_novo / a["custo"] <= CZ.RAZAO_MAX):
        r.update(accao="nao mexer",
                 motivo="custo %.2f contra medio %.2f: embalagem ou unidade diferente?"
                        % (custo_novo, a["custo"]))
        return [r]
    ref = (fams.get(a["fam"]) or loja)["mediana"]
    base = a["pvp"] / (1 + a["iva"] / 100.0) if a["pvp"] > 0 else 0
    r["margem_actual_custo_novo"] = (base / custo_novo - 1) if custo_novo else None
    r["margem_habitual"] = ref
    dif = custo_novo - a["custo"]
    if abs(dif) < LIMIAR_EUR or abs(dif) / a["custo"] < LIMIAR_PCT:
        r.update(accao="igual", motivo="custo praticamente igual ao medio (%+.2f)" % dif)
    elif dif > 0:
        # MANTER A MARGEM QUE O ARTIGO JA TINHA — nao a da familia. A primeira versao usava a
        # mediana da familia e propunha o presunto de 3,75 para 4,45 (+19%) quando o custo
        # subiu 9%: misturava repercutir a subida com corrigir um preco que ja estava baixo
        # (15% contra 25% da familia). Sao duas decisoes; esta so faz a primeira.
        margem_antes = base / a["custo"] - 1 if a["custo"] > 0 and base > 0 else ref
        alvo = para_cima_5(custo_novo * (1 + margem_antes) * (1 + a["iva"] / 100.0))
        r["margem_antes"] = margem_antes
        if alvo <= a["pvp"]:
            r.update(accao="subiu, PVP chega",
                     motivo="custo subiu %+.2f, mas o PVP actual mantem a margem" % dif)
        else:
            r.update(accao="SUBIR PVP", pvp_proposto=alvo,
                     motivo="custo subiu %+.2f (%.0f%%); mantem a margem de %.0f%%"
                            % (dif, 100 * dif / a["custo"], 100 * margem_antes))
        if margem_antes < ref - 0.05:
            r["motivo"] += " — e ja estava abaixo da familia (%.0f%%): rever a parte" % (100 * ref)
    else:
        # DOIS FORNECEDORES PARA O MESMO ARTIGO: fica pelo mais caro (Pedro, 25/09).
        #
        # A ficha da loja tem UM custo so. Se dois fornecedores vendem o mesmo produto a precos
        # diferentes, cada factura apagava o custo da outra e o PVP passava a seguir a ultima que
        # entrasse — e com stock dos dois misturado na prateleira, a margem calculada pelo mais barato
        # nao cobre as pecas que se pagaram mais caras. Por isso, num artigo com mais do que um
        # fornecedor, o custo NUNCA DESCE SOZINHO; subir continua a ser automatico.
        #
        # Nao e uma recusa: se a descida e real nos dois fornecedores, confirma-se e passa. Sem essa
        # saida o custo ficava preso no valor alto para sempre.
        nifs = LG.fornecedores_do_artigo(aid)
        if len(nifs) > 1 and not l.get("confirmado"):
            r.update(accao="nao mexer", pede_confirmacao=True, custo_mais_caro=True,
                     fornecedores_do_artigo=nifs,
                     motivo="este artigo vem de %d fornecedores (%s) e a ficha so guarda um custo: "
                            "fica pelo mais caro, %.2f, em vez dos %.2f desta factura. Se o preco desceu "
                            "nos dois, confirma para baixar."
                            % (len(nifs), ", ".join(nifs), a["custo"], custo_novo))
            return [r]
        if r["promo"] or r["texto_por_baixo"]:
            r.update(accao="nao mexer",
                     motivo="custo desceu mas pode ser PROMOCAO (nota lida ou espaco por baixo)")
        else:
            r.update(accao="desceu", motivo="custo desceu %.2f (%.0f%%): ganhas margem; "
                                            "baixar o PVP e decisao tua" % (dif, 100 * dif / a["custo"]))
    return [r]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    alvo = sys.argv[1] if len(sys.argv) > 1 else "73442"
    fotos = sorted(os.path.join(AQUI, "facturas", f) for f in os.listdir(os.path.join(AQUI, "facturas"))
                   if alvo in f and f.endswith(".jpg"))
    fac, props, sem_ligar = propoe(fotos, alvo)
    q = fac.get("qr") or {}
    print("factura %s | %s | total %.2f EUR | %d linhas de mercadoria"
          % (q.get("numero", alvo), q.get("data", "?"), q.get("total", 0), len(props)))
    print("linhas lidas mas nao ligadas a codigo na foto: %d (nao entram)\n" % sem_ligar)
    from collections import Counter
    for k, v in Counter(p["accao"] for p in props).most_common():
        print("   %-20s %d" % (k, v))
    print()
    for p in props:
        if p["accao"] in ("SUBIR PVP", "desceu", "subiu, PVP chega", "nao mexer"):
            m = p.get("margem_actual_custo_novo")
            print("%-18s %-8s %-30s custo %5.2f -> %5.2f | PVP %5.2f%s | margem %s | %s"
                  % (p["accao"], p["artigo"] or "", (p["desc_loja"] or "")[:30],
                     p.get("custo_medio") or 0, p.get("custo_novo") or 0, p.get("pvp_actual") or 0,
                     (" -> %.2f" % p["pvp_proposto"]) if p.get("pvp_proposto") else "        ",
                     ("%3.0f%%" % (m * 100)) if m is not None else "  ?", p["motivo"]))
    dest = os.path.join(AQUI, "proposta_%s.json" % alvo)
    with open(dest, "w", encoding="utf-8") as f:
        # fornecedor_nif (do QR): o aplica.ps1 regista este fornecedor em cada artigo que gravar
        json.dump({"factura": q.get("numero", alvo), "data": q.get("data"), "fornecedor_nif": q.get("nif_fornecedor"),
                   "linhas": props}, f, ensure_ascii=False, indent=1)
    print("\nlista para aprovar: %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
