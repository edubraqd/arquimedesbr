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
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

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
    pix = page.get_pixmap(dpi=dpi)
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
        img = Image.open(io.BytesIO(bruto))
        return indice, _normalizar(pytesseract.image_to_string(img, lang=lang))

    saida = {}
    with ThreadPoolExecutor(max_workers=threads) as pool:
        for inicio in range(0, len(indices), threads * 3):
            lote = indices[inicio: inicio + threads * 3]
            imagens = [(i, doc[i].get_pixmap(dpi=dpi).tobytes("png")) for i in lote]
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
    doc.close()
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


EXTENSOES = {".pdf", ".docx", ".txt", ".md", ".markdown"}


def extrair(caminho: Path, usar_ocr: bool = True, progresso=None) -> Documento:
    ext = caminho.suffix.lower()
    if ext == ".pdf":
        return extrair_pdf(caminho, usar_ocr=usar_ocr, progresso=progresso)
    if ext == ".docx":
        return extrair_docx(caminho)
    if ext in {".txt", ".md", ".markdown"}:
        return extrair_texto(caminho)
    raise ValueError("extensao nao suportada: " + ext)
