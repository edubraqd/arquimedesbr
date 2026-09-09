"""Extracao de texto -> markdown por pagina.

Sem LLM. PyMuPDF le fonte e posicao para inferir titulos; OCR (Tesseract) so
entra quando a pagina nao tem texto util e o binario existe na maquina.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import statistics
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree

import fitz  # PyMuPDF

# ---------------------------------------------------------------- OCR opcional


# O instalador do Windows nao entra no PATH de sessao ja aberta, entao procurar
# so com `which` dava "OCR indisponivel" com o Tesseract instalado.
_CAMINHOS_TESSERACT = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def binario_tesseract() -> str | None:
    achado = shutil.which("tesseract")
    if achado:
        return achado
    for caminho in _CAMINHOS_TESSERACT:
        if Path(caminho).exists():
            return caminho
    return None


def ocr_disponivel() -> bool:
    if binario_tesseract() is None:
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


# Escrever em "C:\Program Files\Tesseract-OCR\tessdata" exige admin, entao os
# idiomas extras (por, spa) ficam aqui e entram por --tessdata-dir.
TESSDATA = Path(__file__).parent / "tessdata"

# Teto de pixels por pagina no OCR. Existe porque Security Analysis (735 pag.
# escaneadas) tem pagina que a 300 dpi vira 1,8 bilhao de pixels: o PIL barra
# como "decompression bomb" (limite ~179 MPix) e a pagina inteira se perde.
# Acima de ~40 MPix o Tesseract tambem nao reconhece nada a mais -- o ganho de
# resolucao morre bem antes disso.
MAX_PIXELS_OCR = 40_000_000


def _dpi_seguro(page, dpi: int) -> int:
    """Reduz o dpi so quando a pagina renderizada passaria de MAX_PIXELS_OCR."""
    r = getattr(page, "rect", None)
    if r is None or r.width <= 0 or r.height <= 0:
        return dpi
    pixels = (r.width * dpi / 72.0) * (r.height * dpi / 72.0)
    if pixels <= MAX_PIXELS_OCR:
        return dpi
    # sem piso de dpi de proposito: pagina que so cabe abaixo de 72 dpi vai
    # reconhecer mal, e isso e melhor que estourar o limite do PIL e perder a
    # pagina inteira -- ou, como aconteceu em 09/09, a fila inteira atras dela.
    return max(1, int(dpi * (MAX_PIXELS_OCR / pixels) ** 0.5))


def idiomas_ocr(desejados=("por", "eng", "spa")) -> str:
    """So pede a Tesseract idioma que ele realmente tem.

    A instalacao padrao do Windows traz apenas `eng` e `osd`; pedir `por+eng`
    nesse caso faz a chamada inteira falhar em vez de degradar para ingles.
    """
    import subprocess

    ambiente = dict(os.environ)
    if TESSDATA.exists():
        ambiente["TESSDATA_PREFIX"] = str(TESSDATA)
    try:
        saida = subprocess.run(
            [binario_tesseract(), "--list-langs"],
            capture_output=True, text=True, timeout=30, env=ambiente,
        ).stdout
    except Exception:
        return "eng"
    tem = {ln.strip() for ln in saida.splitlines() if ln.strip()}
    escolhidos = [d for d in desejados if d in tem]
    return "+".join(escolhidos) or "eng"


def _ocr_pagina(page, idiomas: str | None = None, dpi: int = 300) -> str:
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = binario_tesseract()
    # via variavel de ambiente, e nao --tessdata-dir: pytesseract quebra a config
    # por espaco, entao o caminho entre aspas chegava literal ao Tesseract
    if TESSDATA.exists():
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA)
    pix = page.get_pixmap(dpi=_dpi_seguro(page, dpi))
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, lang=idiomas or idiomas_ocr())


def _ocr_em_lote(doc, indices: list, lang: str, progresso=None,
                 dpi: int = 300, threads: int = 0) -> dict:
    """OCR de varias paginas em paralelo. Devolve {indice: texto}.

    O Tesseract roda como subprocesso, entao a espera acontece fora do GIL e
    threads ganham de verdade: medido, 2,2 s por pagina sequencial contra ~0,3 s
    efetivos com 8 threads. Quem nao e thread-safe e o `fitz.Document`, entao o
    desenho da imagem fica sequencial e so o reconhecimento e paralelo.
    """
    from concurrent.futures import ThreadPoolExecutor

    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = binario_tesseract()
    if TESSDATA.exists():
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA)
    threads = threads or min(8, (os.cpu_count() or 4))

    def reconhecer(par):
        indice, bruto = par
        try:
            img = Image.open(io.BytesIO(bruto))
            return indice, _normalizar(pytesseract.image_to_string(img, lang=lang))
        except Exception as e:
            # uma pagina ilegivel nao pode custar as outras 734
            print(f"    aviso: OCR falhou na pagina {indice + 1}: "
                  f"{e.__class__.__name__}")
            return indice, ""

    saida = {}
    with ThreadPoolExecutor(max_workers=threads) as pool:
        for inicio in range(0, len(indices), threads * 3):
            lote = indices[inicio: inicio + threads * 3]
            imagens = [(i, doc[i].get_pixmap(dpi=_dpi_seguro(doc[i], dpi)).tobytes("png"))
                       for i in lote]
            for indice, texto in pool.map(reconhecer, imagens):
                saida[indice] = texto
            if progresso:
                progresso(min(inicio + len(lote), len(indices)), len(indices), "ocr")
    return saida


# ------------------------------------------------------------------ estruturas


@dataclass
class Pagina:
    numero: int
    md: str
    palavras: int
    extrator: str = "pymupdf"


@dataclass
class Documento:
    titulo: str
    autor: str
    paginas: list = field(default_factory=list)
    toc: list = field(default_factory=list)  # [[nivel, titulo, pagina], ...]
    aberturas: dict = field(default_factory=dict)  # {pagina 1-based: titulo}
    extrator: str = "pymupdf"

    @property
    def palavras(self) -> int:
        return sum(p.palavras for p in self.paginas)


# -------------------------------------------------------------------- limpeza

_HIFEN = re.compile(r"(\w)-\s*\n\s*(\w)")
_ESPACO = re.compile(r"[ \t ]+")
_SO_NUMERO = re.compile(r"^[\s\-–—|]*\d+[\s\-–—|]*$")
_LIGADURAS = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "­": "",
}


def _normalizar(texto: str) -> str:
    for k, v in _LIGADURAS.items():
        texto = texto.replace(k, v)
    texto = _HIFEN.sub(r"\1\2", texto)
    return _ESPACO.sub(" ", texto).strip()


def _assinatura(linha: str) -> str:
    """Chave para achar cabecalho/rodape repetido: numero vira '#'."""
    return re.sub(r"\d+", "#", linha.lower()).strip()


# --------------------------------------------------------------- leitura PDF


def _blocos_da_pagina(page) -> list:
    """Blocos com texto normalizado, maior fonte e fracao em negrito."""
    dados = page.get_text("dict")
    blocos = []
    for b in dados.get("blocks", []):
        if b.get("type") != 0:
            continue
        linhas, tamanhos, negrito_chars, total_chars = [], [], 0, 0
        for ln in b.get("lines", []):
            partes = []
            for sp in ln.get("spans", []):
                txt = sp.get("text", "")
                if not txt.strip():
                    # Span so de espaco carrega o espaco da linha em PDF de
                    # LaTeX (fonte Type1 sem glifo de espaco proprio). Descarta-lo
                    # colava o texto todo: "Figure1:Thethreeresearchquestions".
                    # Medido em 07/09/2026 no arXiv 2608.23953 — 16 paginas
                    # viraram 1.256 palavras contra 6.839 do get_text() cru.
                    # Fica fora das estatisticas de fonte e negrito de proposito.
                    if partes and not partes[-1].endswith(" "):
                        partes.append(" ")
                    continue
                partes.append(txt)
                tamanhos.append(round(sp.get("size", 0), 1))
                total_chars += len(txt)
                if sp.get("flags", 0) & 16:  # bold
                    negrito_chars += len(txt)
            if partes:
                linhas.append("".join(partes))
        if not linhas:
            continue
        texto = _normalizar("\n".join(linhas))
        if not texto:
            continue
        blocos.append(
            {
                "texto": texto,
                "linhas": len(linhas),
                "tam": max(tamanhos) if tamanhos else 0.0,
                "negrito": (negrito_chars / total_chars) if total_chars else 0.0,
            }
        )
    return blocos


def _candidato_a_titulo(blocos: list, corpo: float):
    """Maior bloco curto no topo da pagina — candidato a titulo de capitulo."""
    melhor = None
    for b in blocos[:3]:
        texto = b["texto"].strip()
        if b["linhas"] > 3 or not (3 <= len(texto) <= 90):
            continue
        if b["tam"] < corpo * 1.25:
            continue
        if melhor is None or b["tam"] > melhor[0]:
            melhor = (round(b["tam"] * 2) / 2, _limpar_titulo(texto))
    return melhor


def _limpar_titulo(texto: str) -> str:
    """Tira numero de pagina e quebra de linha grudados no titulo detectado.

    O bloco costuma vir como "2
Capitulo uno" porque o numero da pagina fica
    na mesma caixa de texto do titulo.
    """
    texto = re.sub(r"\s+", " ", texto).strip()
    texto = re.sub(r"^\d{1,4}[\s.:\-–]*", "", texto).strip()
    return texto


def aberturas_de_capitulo(paginas_blocos: list, corpo: float) -> dict:
    """Acha onde comecam capitulos em PDF que nao traz sumario.

    Ideia: num livro, o titulo de capitulo tem um tamanho de fonte proprio, que
    aparece **poucas vezes** — uma por capitulo. Subtitulo aparece demais, e
    titulo de secao de rosto aparece de menos. Entao conta-se a frequencia de
    cada tamanho entre os candidatos e escolhe-se o maior que apareca numa faixa
    plausivel de capitulos.

    Devolve {indice da pagina: titulo}.
    """
    candidatos = {}
    for i, blocos in enumerate(paginas_blocos):
        achado = _candidato_a_titulo(blocos, corpo)
        if achado:
            candidatos[i] = achado

    frequencia = Counter(tam for tam, _t in candidatos.values())
    n_paginas = max(len(paginas_blocos), 1)
    plausiveis = [
        tam for tam, n in frequencia.items()
        if 3 <= n <= 80 and n_paginas / n >= 4      # ao menos 4 paginas por capitulo
    ]
    if not plausiveis:
        return {}
    escolhido = max(plausiveis)
    achados = {i: t for i, (tam, t) in candidatos.items() if tam == escolhido}
    return achados if _cobre_o_livro(achados, n_paginas) else {}


def _cobre_o_livro(achados: dict, n_paginas: int) -> bool:
    """So aceita a deteccao se ela cobrir o livro de ponta a ponta.

    Medido: no Refactoring UI a fonte grande so aparece 3 vezes, e as tres na
    segunda metade — usar isso daria um primeiro capitulo de 157 paginas, pior
    que o corte por tamanho. Melhor recusar e cair no fallback.
    """
    if len(achados) < 4:
        return False
    posicoes = sorted(achados)
    if posicoes[0] > n_paginas * 0.25:          # comeca tarde demais
        return False
    limites = posicoes + [n_paginas]
    maior_vao = max(b - a for a, b in zip(limites, limites[1:]))
    return maior_vao <= n_paginas * 0.35        # nenhum bloco engole o livro


def _fonte_do_corpo(paginas_blocos: list) -> float:
    pesos = []
    for blocos in paginas_blocos:
        for b in blocos:
            pesos.extend([b["tam"]] * max(1, len(b["texto"]) // 40))
    return statistics.median(pesos) if pesos else 10.0


def _bordas_repetidas(paginas_blocos: list, limite: float = 0.4) -> set:
    """Cabecalho/rodape que se repete em mais de `limite` das paginas."""
    contagem = {}
    total = 0
    for blocos in paginas_blocos:
        if not blocos:
            continue
        total += 1
        for c in {blocos[0]["texto"], blocos[-1]["texto"]}:
            if len(c) < 120:
                chave = _assinatura(c)
                contagem[chave] = contagem.get(chave, 0) + 1
    if total < 5:
        return set()
    return {k for k, v in contagem.items() if v / total >= limite}


def _bloco_para_md(b: dict, corpo: float, bordas: set) -> str:
    texto = b["texto"]
    if _SO_NUMERO.match(texto) or _assinatura(texto) in bordas:
        return ""
    curto = b["linhas"] <= 2 and len(texto) <= 120
    razao = b["tam"] / corpo if corpo else 1.0
    if curto and (razao >= 1.45 or (razao >= 1.15 and b["negrito"] > 0.6)):
        nivel = 2 if razao >= 1.6 else 3
        return "#" * nivel + " " + texto.replace("\n", " ")
    if curto and razao >= 1.12:
        return "### " + texto.replace("\n", " ")
    return texto.replace("\n", " ")


def extrair_pdf(caminho: Path, usar_ocr: bool = True,
                minimo_palavras: int = 25, progresso=None) -> Documento:
    doc = fitz.open(caminho)
    try:
        return _extrair_pdf_aberto(doc, usar_ocr, minimo_palavras, progresso)
    finally:
        doc.close()


def _extrair_pdf_aberto(doc, usar_ocr: bool, minimo_palavras: int,
                        progresso) -> Documento:
    meta = doc.metadata or {}
    titulo = (meta.get("title") or "").strip()
    autor = (meta.get("author") or "").strip()

    brutos = []
    for i, page in enumerate(doc):
        brutos.append(_blocos_da_pagina(page))
        if progresso and i and i % 100 == 0:
            progresso(i, doc.page_count, "lendo")

    corpo = _fonte_do_corpo(brutos)
    bordas = _bordas_repetidas(brutos)

    ocr_ok = usar_ocr and ocr_disponivel()
    lang = idiomas_ocr() if ocr_ok else None   # uma consulta so, nao uma por pagina

    primeira = []
    for blocos in brutos:
        pedacos = [m for m in (_bloco_para_md(b, corpo, bordas) for b in blocos) if m]
        primeira.append("\n\n".join(pedacos))

    faltando = [
        i for i, md in enumerate(primeira) if len(md.split()) < minimo_palavras
    ]
    ocr_texto = (
        _ocr_em_lote(doc, faltando, lang, progresso) if ocr_ok and faltando else {}
    )

    paginas = []
    usou_ocr = 0
    for i, md in enumerate(primeira):
        n = len(md.split())
        extrator = "pymupdf"
        alternativa = ocr_texto.get(i)
        if alternativa and len(alternativa.split()) > n:
            md, n, extrator = alternativa, len(alternativa.split()), "ocr"
            usou_ocr += 1
        paginas.append(Pagina(numero=i + 1, md=md, palavras=n, extrator=extrator))

    toc = doc.get_toc(simple=True) or []
    # so vale detectar por layout quando o PDF nao traz sumario proprio
    aberturas = {} if toc else {
        i + 1: titulo
        for i, titulo in aberturas_de_capitulo(brutos, corpo).items()
    }
    return Documento(
        titulo=titulo,
        autor=autor,
        paginas=paginas,
        toc=toc,
        aberturas=aberturas,
        extrator="ocr" if usou_ocr > len(paginas) / 2 else "pymupdf",
    )


# ------------------------------------------------------------ outros formatos


def extrair_docx(caminho: Path) -> Documento:
    import docx

    d = docx.Document(str(caminho))
    pedacos = []
    for p in d.paragraphs:
        texto = _normalizar(p.text)
        if not texto:
            continue
        estilo = (p.style.name or "").lower()
        if estilo.startswith("heading"):
            nivel = min(6, max(2, int(re.sub(r"\D", "", estilo) or 2) + 1))
            pedacos.append("#" * nivel + " " + texto)
        else:
            pedacos.append(texto)
    md = "\n\n".join(pedacos)
    props = d.core_properties
    return Documento(
        titulo=(props.title or "").strip(),
        autor=(props.author or "").strip(),
        paginas=[Pagina(1, md, len(md.split()), "docx")],
        extrator="docx",
    )


def extrair_texto(caminho: Path) -> Documento:
    bruto = caminho.read_text(encoding="utf-8", errors="replace")
    return Documento(
        titulo="",
        autor="",
        paginas=[Pagina(1, bruto, len(bruto.split()), "texto")],
        extrator="texto",
    )


# ----------------------------------------------------------------------- epub


def _sem_ns(tag: str) -> str:
    """`{http://www.idpf.org/2007/opf}spine` -> `spine`."""
    return tag.rsplit("}", 1)[-1].lower()


class _HtmlParaTexto(HTMLParser):
    """XHTML de capitulo -> texto com os titulos virando `##`.

    Nao usa BeautifulSoup de proposito: o motor inteiro roda em stdlib + pymupdf,
    e epub e so zip com XHTML dentro.
    """

    IGNORAR = {"script", "style", "head", "svg"}
    QUEBRA = {"p", "div", "br", "li", "tr", "blockquote", "section", "figcaption"}
    TITULO = {"h1": 2, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pedacos: list[str] = []
        self._mudo = 0
        self._titulo: int | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self._mudo += 1
        elif tag in self.TITULO:
            self.pedacos.append("\n\n" + "#" * self.TITULO[tag] + " ")
            self._titulo = self.TITULO[tag]
        elif tag in self.QUEBRA:
            self.pedacos.append("\n\n")

    def handle_endtag(self, tag):
        if tag in self.IGNORAR:
            self._mudo = max(0, self._mudo - 1)
        elif tag in self.TITULO:
            self._titulo = None
            self.pedacos.append("\n\n")
        elif tag in self.QUEBRA:
            self.pedacos.append("\n\n")

    def handle_data(self, dado):
        if self._mudo:
            return
        # dentro de titulo a quebra de linha do XHTML viraria "## " orfao
        self.pedacos.append(" ".join(dado.split()) if self._titulo else dado)

    def texto(self) -> str:
        bruto = "".join(self.pedacos)
        return re.sub(r"\n{3,}", "\n\n", _normalizar(bruto)).strip()


_EXT_EBOOK = re.compile(r"\.(epub|mobi|azw3?|pdf)\s*$", re.I)
_SITE_NO_FIM = re.compile(r"[\(\[][^()\[\]]*\.(com|net|org|info|ru)[^()\[\]]*[\)\]]\s*$", re.I)


def _limpar_titulo_epub(bruto: str) -> str:
    """Tira o lixo que epub reempacotado carrega no titulo.

    O Challenger Sale chegou como
    `The Challenger Sale: ...   \\( PDFDrive.com \\).epub` -- quem gerou o arquivo
    pos o nome do arquivo como titulo. Sem isso o lixo vai para o frontmatter,
    para o INDEX.md e para toda citacao.
    """
    t = bruto.replace("\\(", "(").replace("\\)", ")")
    t = _EXT_EBOOK.sub("", t.strip())
    t = _SITE_NO_FIM.sub("", t).strip()
    t = _EXT_EBOOK.sub("", t).strip()
    return re.sub(r"\s{2,}", " ", t).strip(" -–—_")


def _opf_do_epub(z) -> str:
    """Caminho do OPF, lido do container.xml em vez de adivinhado."""
    try:
        raiz = ElementTree.fromstring(z.read("META-INF/container.xml"))
    except (KeyError, ElementTree.ParseError):
        raiz = None
    if raiz is not None:
        for el in raiz.iter():
            if _sem_ns(el.tag) == "rootfile" and el.get("full-path"):
                return el.get("full-path")
    # epub torto: procura qualquer .opf no zip
    for nome in z.namelist():
        if nome.lower().endswith(".opf"):
            return nome
    raise ValueError("epub sem OPF: nao da para saber a ordem de leitura")


def extrair_epub(caminho: Path) -> Documento:
    """EPUB -> uma `Pagina` por documento do spine.

    Uma pagina por documento (e nao um bloco unico, como o `.docx` faz) porque
    o spine ja e a ordem de leitura do livro: assim `fatiar.py` corta em
    fronteira de capitulo de verdade e a citacao aponta para um lugar real. O
    numero da "pagina" e a posicao no spine, nao pagina de papel -- o epub nao
    tem uma.
    """
    with zipfile.ZipFile(caminho) as z:
        opf_caminho = _opf_do_epub(z)
        opf = ElementTree.fromstring(z.read(opf_caminho))
        pasta = PurePosixPath(opf_caminho).parent

        titulo = autor = ""
        manifesto: dict[str, str] = {}
        ordem: list[str] = []
        for el in opf.iter():
            nome = _sem_ns(el.tag)
            if nome == "title" and not titulo:
                titulo = (el.text or "").strip()
            elif nome == "creator" and not autor:
                autor = (el.text or "").strip()
            elif nome == "item" and el.get("id") and el.get("href"):
                manifesto[el.get("id")] = el.get("href")
            elif nome == "itemref" and el.get("idref"):
                ordem.append(el.get("idref"))

        nomes_no_zip = set(z.namelist())
        paginas: list[Pagina] = []
        for idref in ordem:
            href = manifesto.get(idref)
            if not href:
                continue
            alvo = str(pasta / unquote(href.split("#")[0])).lstrip("./")
            if alvo not in nomes_no_zip:
                continue
            p = _HtmlParaTexto()
            try:
                p.feed(z.read(alvo).decode("utf-8", errors="replace"))
            except Exception:
                continue
            md = p.texto()
            # `if not md` nao basta: documento de capa ou pagina em branco sai
            # como "##" (o marcador do titulo vazio), que e verdadeiro e viraria
            # uma pagina sem uma palavra dentro
            if not md.replace("#", "").strip():
                continue
            paginas.append(Pagina(len(paginas) + 1, md, len(md.split()), "epub"))

    if not paginas:
        raise ValueError("epub sem texto legivel no spine")
    return Documento(titulo=_limpar_titulo_epub(titulo), autor=autor,
                     paginas=paginas, extrator="epub")


EXTENSOES = {".pdf", ".docx", ".epub", ".txt", ".md", ".markdown"}


def extrair(caminho: Path, usar_ocr: bool = True, progresso=None) -> Documento:
    ext = caminho.suffix.lower()
    if ext == ".pdf":
        return extrair_pdf(caminho, usar_ocr=usar_ocr, progresso=progresso)
    if ext == ".docx":
        return extrair_docx(caminho)
    if ext == ".epub":
        return extrair_epub(caminho)
    if ext in {".txt", ".md", ".markdown"}:
        return extrair_texto(caminho)
    raise ValueError("extensao nao suportada: " + ext)
