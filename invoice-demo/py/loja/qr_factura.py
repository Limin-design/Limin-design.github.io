"""Le o QR code de uma factura portuguesa a partir de uma fotografia. Tudo local.

Porque o QR e a peca central: as facturas desta loja chegam em PAPEL e sem codigo de barras nas
linhas. Uma fotografia de papel tem de passar por OCR, e o OCR erra — um 8 lido como 3 num preco
unitario muda o preco de venda proposto sem ninguem dar por isso. O QR code (obrigatorio nas
facturas de software certificado) e a unica parte do papel que se le SEM erro, e traz o que
precisamos para apanhar os erros do OCR: o fornecedor, a data, o numero, e a BASE TRIBUTAVEL POR
TAXA DE IVA. As linhas lidas por OCR tem de somar isso. Se nao somarem, nao se propoe preco nenhum.

O QUE O QR NAO TRAZ: as linhas da factura. Nao ha maneira de tirar o custo de cada artigo so do
QR — isso continua a precisar de ler a factura. O QR e a PROVA, nao a fonte das linhas.

Formato (codigos separados por '*', cada um CODIGO:valor), campos que usamos:
  A NIF do emitente   B NIF do adquirente   D tipo de documento   F data AAAAMMDD
  G numero do documento   H ATCUD
  I1 espaco fiscal   I2 base isenta   I3/I4 base e IVA taxa reduzida
  I5/I6 base e IVA taxa intermedia   I7/I8 base e IVA taxa normal
  N total de impostos   O total com impostos
Os espacos fiscais dos Acores (J) e da Madeira (K) leem-se da mesma forma.

NAO VERIFICADO contra uma factura real desta loja: o formato foi escrito a partir da estrutura
publicada e testado com um QR construido a mao. A primeira fotografia verdadeira e o teste que
falta — e o `confere()` e o que diz se a leitura faz sentido.

Uso:
  python\\python.exe qr_factura.py foto.jpg [foto2.jpg ...]
  python\\python.exe qr_factura.py --teste
"""
import os
import sys

# NIF da loja: o adquirente que tem de vir no campo B. Visto nas duas primeiras facturas reais
# (Recheio e Pao de Mafra). Uma factura para outro NIF e o sinal mais barato de que se
# fotografou o documento errado — ou que o IVA dela nao e dedutivel por esta empresa.
NIF_LOJA = "240155300"

TAXAS = {  # (campo base, campo IVA) por escalao, espaco fiscal do continente
    "reduzida": ("I3", "I4"),
    "intermedia": ("I5", "I6"),
    "normal": ("I7", "I8"),
}


def _num(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def interpreta(texto):
    """Texto do QR -> dicionario com os campos que interessam. None se nao for um QR de factura."""
    if not texto or "*" not in texto or not texto.startswith("A:"):
        return None
    campos = {}
    for parte in texto.split("*"):
        if ":" in parte:
            k, v = parte.split(":", 1)
            campos[k.strip()] = v.strip()
    if "A" not in campos or "O" not in campos:
        return None
    f = campos.get("F", "")
    fora = {
        "nif_fornecedor": campos.get("A"),
        "nif_cliente": campos.get("B"),
        "tipo": campos.get("D"),
        "data": ("%s-%s-%s" % (f[:4], f[4:6], f[6:8])) if len(f) == 8 else f,
        "numero": campos.get("G"),
        "atcud": campos.get("H"),
        "espaco_fiscal": campos.get("I1"),
        "base_isenta": _num(campos.get("I2")) or 0.0,
        # L = "nao sujeito / nao tributado". E onde o Recheio poe o TABACO (o PVP vem do selo fiscal):
        # sem isto a factura do tabaco de 19/09 nao tinha nada por onde ser provada.
        "nao_sujeito": _num(campos.get("L")) or 0.0,
        "por_taxa": {},
        "total_impostos": _num(campos.get("N")) or 0.0,
        "total": _num(campos.get("O")) or 0.0,
        "_campos": campos,
    }
    for nome, (kb, ki) in TAXAS.items():
        b, i = _num(campos.get(kb)), _num(campos.get(ki))
        if b or i:
            fora["por_taxa"][nome] = {"base": b or 0.0, "iva": i or 0.0}
    return fora


def confere(q, tolerancia=0.02):
    """A factura bate certo consigo propria? Soma das bases + impostos = total.

    Nao prova que a leitura esta certa — prova que NAO esta obviamente errada. Um QR mal lido ou
    de um formato que nao conhecemos falha aqui, e ai nao se usa para nada."""
    bases = q["base_isenta"] + q.get("nao_sujeito", 0.0) + sum(t["base"] for t in q["por_taxa"].values())
    iva = sum(t["iva"] for t in q["por_taxa"].values())
    problemas = []
    if abs(iva - q["total_impostos"]) > tolerancia:
        problemas.append("IVA por taxa (%.2f) nao bate com o total de impostos (%.2f) — pode "
                         "haver Imposto do Selo ou retencao" % (iva, q["total_impostos"]))
    if abs(bases + q["total_impostos"] - q["total"]) > tolerancia:
        problemas.append("bases (%.2f) + impostos (%.2f) = %.2f, e o total diz %.2f"
                         % (bases, q["total_impostos"], bases + q["total_impostos"], q["total"]))
    return problemas


def _tentativas(img):
    """Versoes da mesma foto, da mais barata para a mais trabalhada.

    Medido a 2026-09-14 na factura do Pao de Mafra: o QR mais nitido das tres fotos NAO lia com a
    imagem crua — nem a cores, nem em cinzento. Nao era a perspectiva: era contraste. A folha
    tinha sombras suaves e o preto dos modulos ficava cinzento. Com contraste automatico, ou so
    com a foto a metade do tamanho, lia a primeira. As duas ficam, porque falham de maneiras
    diferentes, e so se passa a seguinte quando a anterior nao encontrou QR fiscal."""
    from PIL import ImageOps
    yield img
    cinza = ImageOps.grayscale(img)
    yield ImageOps.autocontrast(cinza, cutoff=2)
    yield cinza.resize((cinza.width // 2, cinza.height // 2))


def le_foto(caminho):
    """Os QR FISCAIS encontrados na foto. Os de publicidade (o Recheio tem um no cabecalho) ficam
    de fora porque nao comecam por 'A:' — o `interpreta` recusa-os."""
    import zxingcpp
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(caminho))   # fotos de telemovel vem deitadas
    for versao in _tentativas(img):
        fora = [q for q in (interpreta(r.text) for r in zxingcpp.read_barcodes(versao)) if q]
        if fora:
            return fora
    return []


def teste():
    """Um QR construido a mao com contas que batem, e um com contas erradas."""
    bom = ("A:500000000*B:999999990*C:PT*D:FT*E:N*F:20260910*G:FT A/123*H:ABCD1234-123*"
           "I1:PT*I2:0.00*I3:100.00*I4:6.00*I7:50.00*I8:11.50*N:17.50*O:167.50*Q:abcd*R:1234")
    mau = bom.replace("O:167.50", "O:176.50")          # um 7 e um 6 trocados, como no OCR
    q = interpreta(bom)
    falhas = []
    if not q or q["nif_fornecedor"] != "500000000" or q["data"] != "2026-09-10":
        falhas.append("cabecalho mal lido")
    if q["por_taxa"].get("reduzida", {}).get("base") != 100.0:
        falhas.append("base da taxa reduzida mal lida")
    if confere(q):
        falhas.append("QR certo acusado de errado: %s" % confere(q))
    if not confere(interpreta(mau)):
        falhas.append("CONTROLO: QR com total errado passou como certo")
    if interpreta("isto nao e um QR de factura") is not None:
        falhas.append("texto qualquer lido como factura")
    print("QR OK (5 verificacoes)" if not falhas else "FALHAS: %s" % "; ".join(falhas))
    return 1 if falhas else 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--teste" in sys.argv:
        return teste()
    for f in sys.argv[1:]:
        qs = le_foto(f)
        nome_f = os.path.basename(f)
        if not qs:
            # O QR fiscal so vem numa pagina: nas de continuacao (o Recheio imprime "TRANSPORTE")
            # nao ha nenhum, e isso esta certo. A mensagem antiga mandava tirar outra fotografia.
            print("%s: sem QR fiscal — normal numa pagina de continuacao; se for a primeira "
                  "pagina, tirar a foto mais perto e sem sombra" % nome_f)
            continue
        for q in qs:
            print("%s: fornecedor %s | %s | %s | total %.2f EUR"
                  % (nome_f, q["nif_fornecedor"], q["numero"], q["data"], q["total"]))
            if q["base_isenta"]:
                print("    isento          base %9.2f" % q["base_isenta"])
            for nome, t in q["por_taxa"].items():
                print("    taxa %-10s base %9.2f  IVA %8.2f" % (nome, t["base"], t["iva"]))
            if q["nif_cliente"] != NIF_LOJA:
                print("    ATENCAO: factura emitida ao NIF %s, nao ao da loja (%s)"
                      % (q["nif_cliente"], NIF_LOJA))
            for p in confere(q):
                print("    ATENCAO: %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
