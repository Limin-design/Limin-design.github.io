"""O QUE E DESTA LOJA, e nao do programa: config\\loja.json.

Ate 29/09 estas coisas estavam escritas no codigo (auditoria 29/09, secao 5, e 22/09 M12): o NIF da loja,
o artigo de tara, o "R"+codigo do Recheio e o codigo de deposito 888879. Na loja nº 2 cada uma delas estava
errada sem ninguem dar por isso. Sem o ficheiro, ficam os valores neutros: nenhuma regra de codigo, nenhum
codigo de deposito, e o NIF por verificar.
"""
import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
FICHEIRO = os.path.join(AQUI, "config", "loja.json")
_cache = None


def config():
    global _cache
    if _cache is None:
        try:
            with open(FICHEIRO, encoding="utf-8") as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def nif():
    return str(config().get("nif") or "")


def nome():
    return str(config().get("nome") or "")


def tara_ean():
    return str(config().get("tara_ean") or "0000000000010")


def sql_ligacao():
    """A ligacao a copia SQL das caixas (so leitura)."""
    return str(config().get("sql_ligacao") or
               "DRIVER={SQL Server};SERVER=.;DATABASE=NewPosserver;Trusted_Connection=yes;")


def loja_de_referencia():
    """True so em Fanhoes: e onde estao as facturas, as ligacoes e os casos com que a verificacao completa
    mede o programa. Noutra loja esses passos nao medem nada (os artigos nao existem la) e saltam-se."""
    return bool(config().get("loja_de_referencia"))


def artigo_pelo_codigo(nif_fornecedor, codigo, arts):
    """O artigo da loja cujo CODIGO e o do fornecedor com um prefixo (regra DESTA loja), ou None.
    So com o NIF do fornecedor: sem ele a regra nao se aplica (auditoria 22/09 M12 — sem QR, linhas de
    outros fornecedores caiam em artigos "R")."""
    if not nif_fornecedor:
        return None
    base = str(codigo).split(".")[0].strip()
    for r in config().get("codigo_do_fornecedor_no_artigo") or []:
        if str(r.get("nif")) == str(nif_fornecedor):
            cand = str(r.get("prefixo") or "") + base
            if cand in arts:
                return cand
    return None


def e_codigo_de_deposito(codigo):
    c = str(codigo or "")
    return any(c.startswith(str(x)) for x in (config().get("codigos_de_deposito") or []))
