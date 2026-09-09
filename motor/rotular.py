"""Da nome ao que a extracao nao soube nomear, e monta o mapa da base.

Livro sem sumario no PDF vira "Trecho 1..N" — medido, 184 capitulos (16%) em 57
documentos. Para quem procura, "Power Meter - Trecho 4" nao diz nada. Aqui o
proprio corpus resolve: TF-IDF de cada capitulo contra todos os outros mostra o
que so aquele capitulo fala, e um titulo interno do texto, quando existe, e
melhor ainda.

Nada e inventado: o rotulo sai de palavras que estao no capitulo.

    python rotular.py --seco      # mostra os rotulos que atribuiria
    python rotular.py             # grava `assunto:` e refaz os INDEX
    python rotular.py --mapa      # so regenera MAPA.md
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import catalogar  # noqa: E402
import qualidade  # noqa: E402
from buscar import _frontmatter, ler_capitulo, tokenizar  # noqa: E402
from semantico import _corpo  # noqa: E402

from raiz import RAIZ_PADRAO  # noqa: E402

_GENERICO = re.compile(
    r"^(trecho|abertura|parte|cap[ií]tulo|chapter|se[cç][aã]o|section|"
    r"unidade|modulo|m[oó]dulo|lesson|li[cç][aã]o)\b[\s\d\.:/()-]*$",
    re.IGNORECASE,
)
_TITULO_MD = re.compile(r"^#{2,4}\s+(.{3,90})$", re.MULTILINE)


def titulo_generico(titulo: str) -> bool:
    t = (titulo or "").strip()
    return bool(_GENERICO.match(t)) or len(t) < 4


def carregar(raiz: Path):
    itens = []
    for p in sorted((raiz / "markdown").rglob("*.md")):
        if p.name == "INDEX.md":
            continue
        bruto = ler_capitulo(p)
        if bruto is None:
            continue
        campos = _frontmatter(bruto)
        if campos.get("util") == "nao":
            continue
        itens.append({"caminho": p, "campos": campos, "corpo": _corpo(bruto)})
    return itens


def _idf(itens) -> dict:
    df = Counter()
    for it in itens:
        df.update(set(_termos(it["corpo"])))
    n = len(itens)
    return {t: math.log(n / c) + 1 for t, c in df.items() if c >= 2}


def _termos(texto: str) -> list:
    uni = [t for t in tokenizar(texto) if len(t) > 3]
    bi = [f"{a} {b}" for a, b in zip(uni, uni[1:])]
    return uni + bi


def _conceitos(corpo: str, idf: dict, quantos: int = 8) -> list:
    tf = Counter(_termos(corpo))
    placar = {}
    for termo, c in tf.items():
        if c < 2 or termo not in idf:
            continue
        placar[termo] = (1 + math.log(c)) * idf[termo]
    ordenado = [t for t, _v in sorted(placar.items(), key=lambda kv: -kv[1])]
    # bigrama primeiro: diz mais que palavra solta ("zona de potencia" > "zona")
    bigramas = [t for t in ordenado if " " in t]
    unigramas = [t for t in ordenado if " " not in t]
    saida, usados = [], set()
    for termo in bigramas + unigramas:
        partes = set(termo.split())
        if partes & usados:            # nao repetir a mesma palavra em dois rotulos
            continue
        saida.append(termo)
        usados |= partes
        if len(saida) >= quantos:
            break
    return saida


_STOPWORDS_TITULO = set(
    """de da do das dos e ou em no na para por com sem que a o as os um uma ao
    the of and to in for with a an on is are how what why when""".split()
)


def _so_nome_proprio(titulo: str) -> bool:
    """"Donald Miller", "Csaba Szepesvari University of Alberta" — folha de rosto.

    Vira rotulo inutil: diz quem escreveu, nao do que trata. Detecta pela falta
    de palavra funcional e pelo excesso de iniciais maiusculas.
    """
    palavras = [p for p in re.findall(r"[^\W\d_]+", titulo) if len(p) > 1]
    if not palavras or len(palavras) > 6:
        return False
    if any(p.lower() in _STOPWORDS_TITULO for p in palavras[1:]):
        return False
    return all(p[0].isupper() for p in palavras)


def _caixa(titulo: str) -> str:
    """TITULO INTEIRO EM MAIUSCULA cansa de ler numa tabela."""
    letras = [c for c in titulo if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) / len(letras) > 0.7:
        return titulo.capitalize()
    return titulo


def _titulo_interno(corpo: str, idf: dict) -> str | None:
    """Melhor cabecalho dentro do capitulo — quando o livro tem, e o rotulo ideal."""
    candidatos = []
    for bruto in _TITULO_MD.findall(corpo[:20000]):
        titulo = re.sub(r"\s+", " ", bruto).strip(" .:-")
        # numero de pagina grudado no comeco: "87 La estrategia SPIN"
        titulo = re.sub(r"^\d{1,4}[\s.:\-–]*", "", titulo).strip(" .:-")
        palavras = titulo.split()
        if not (2 <= len(palavras) <= 10) or qualidade.titulo_e_lixo(titulo):
            continue
        if _so_nome_proprio(titulo):
            continue
        if sum(c.isdigit() for c in titulo) > len(titulo) / 4:
            continue
        peso = sum(idf.get(t, 0) for t in tokenizar(titulo))
        candidatos.append((peso, titulo))
    if not candidatos:
        return None
    peso, titulo = max(candidatos)
    return _caixa(titulo) if peso >= 4 else None


def rotular(raiz: Path, seco: bool = False) -> int:
    itens = carregar(raiz)
    idf = _idf(itens)

    # IDF local, dentro do documento: contra o corpus inteiro, todo capitulo do
    # Power Meter sai rotulado "power meter" — o termo distingue o livro, nao o
    # capitulo. O que interessa aqui e o que separa um capitulo dos irmaos.
    por_doc = defaultdict(list)
    for it in itens:
        por_doc[it["caminho"].parent].append(it)
    idf_local = {
        pasta: _idf(caps) for pasta, caps in por_doc.items() if len(caps) >= 4
    }

    mudou = 0
    for it in itens:
        campos, corpo = it["campos"], it["corpo"]
        local = idf_local.get(it["caminho"].parent)
        conceitos = _conceitos(corpo, local) if local else _conceitos(corpo, idf)
        assunto = campos.get("assunto", "")
        if titulo_generico(campos.get("capitulo", "")):
            novo = _titulo_interno(corpo, idf) or ", ".join(conceitos[:4])
        else:
            novo = campos.get("capitulo", "")
        novo = novo[:110]
        termos = ", ".join(conceitos[:6])
        if assunto == novo and campos.get("termos") == termos:
            continue
        mudou += 1
        if seco:
            if titulo_generico(campos.get("capitulo", "")):
                print(f"  {it['caminho'].parent.name[:34]:34} "
                      f"{campos.get('capitulo', '?')[:14]:14} -> {novo[:64]}")
            continue
        _gravar(it["caminho"], {"assunto": novo, "termos": termos})
    print(f"{len(itens)} capitulos, {mudou} atualizados"
          + (" (seco: nada escrito)" if seco else ""))
    return mudou


def _gravar(md: Path, novos: dict) -> None:
    texto = md.read_text(encoding="utf-8")
    fim = texto.find("\n---", 3)
    if not texto.startswith("---") or fim == -1:
        return
    campos = {}
    for linha in texto[3:fim].strip().splitlines():
        if ":" in linha:
            k, v = linha.split(":", 1)
            campos[k.strip()] = v.strip()
    campos.update({k: catalogar._yaml(v) for k, v in novos.items()})
    cabeca = "---\n" + "\n".join(f"{k}: {v}" for k, v in campos.items()) + "\n---"
    md.write_text(cabeca + texto[fim + 4:], encoding="utf-8")


# ------------------------------------------------------------- indices e mapa


def reescrever_indices(raiz: Path) -> None:
    """Refaz o INDEX.md de cada documento, agora com a coluna de assunto."""
    itens = carregar(raiz)
    por_doc = defaultdict(list)
    for it in itens:
        por_doc[it["caminho"].parent].append(it)

    for pasta, caps in por_doc.items():
        caps.sort(key=lambda it: it["caminho"].name)
        meta = caps[0]["campos"]
        linhas = [
            f"# {meta.get('titulo', pasta.name)}",
            "",
            f"**{meta.get('autor') or 'autor nao informado'}** · idioma "
            f"`{meta.get('idioma', 'xx')}` · {meta.get('total_paginas', '?')} paginas · "
            f"{len(caps)} capitulos na busca",
            "",
            "| # | Capitulo | Assunto | Paginas | Palavras |",
            "|---|---|---|---|---|",
        ]
        for it in caps:
            c = it["campos"]
            titulo = (c.get("capitulo") or "?").replace("|", "/")[:60]
            assunto = (c.get("assunto") or "").replace("|", "/")[:70]
            if assunto and assunto[:40] == titulo[:40]:
                assunto = "—"
            linhas.append(
                f"| [{it['caminho'].stem.split('-')[0]}]({it['caminho'].name}) "
                f"| {titulo} | {assunto} | {c.get('paginas', '?')} "
                f"| {c.get('palavras', '?')} |"
            )
        (pasta / "INDEX.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")


def mapa(raiz: Path) -> Path:
    """Uma pagina so com o cartao de cada documento — para orientar antes de buscar."""
    itens = carregar(raiz)
    idf = _idf(itens)
    por_doc = defaultdict(list)
    for it in itens:
        por_doc[it["caminho"].parent].append(it)

    por_cat = defaultdict(list)
    for pasta, caps in por_doc.items():
        meta = caps[0]["campos"]
        corpo = "\n".join(c["corpo"] for c in caps)
        por_cat[meta.get("categoria", pasta.parent.name)].append(
            {
                "pasta": pasta,
                "titulo": meta.get("titulo", pasta.name),
                "autor": meta.get("autor", ""),
                "idioma": meta.get("idioma", "xx"),
                "paginas": meta.get("total_paginas", "?"),
                "capitulos": len(caps),
                "conceitos": _conceitos(corpo, idf, 10),
            }
        )

    linhas = [
        "# Mapa da base",
        "",
        "Cartao de cada documento: idioma, tamanho e **os conceitos que so ele "
        "carrega** (TF-IDF contra o resto da base, nao resumo escrito por modelo).",
        "",
        "Use para escolher onde procurar. Para achar o capitulo, use a busca:",
        "",
        "```bash",
        'python buscar.py "pergunta em portugues" \\',
        '    --tambem "same question in english" --n 6 --trechos',
        "```",
        "",
    ]
    for cat in sorted(por_cat):
        linhas.append(f"## {catalogar.ROTULOS.get(cat, cat)}")
        linhas.append("")
        for d in sorted(por_cat[cat], key=lambda x: x["titulo"].lower()):
            autor = f" — {d['autor']}" if d["autor"] else ""
            linhas.append(
                f"**{d['titulo']}**{autor}  \n"
                f"`{d['idioma']}` · {d['paginas']} pag · {d['capitulos']} cap · "
                f"[sumario]({d['pasta'].relative_to(raiz).as_posix()}/INDEX.md)  \n"
                f"{', '.join(d['conceitos'])}"
            )
            linhas.append("")
    caminho = raiz / "MAPA.md"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def main() -> int:
    ap = argparse.ArgumentParser(description="Rotula capitulos e monta o mapa")
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--mapa", action="store_true", help="so regenera MAPA.md")
    args = ap.parse_args()

    if args.mapa:
        print("mapa:", mapa(args.raiz))
        return 0
    rotular(args.raiz, seco=args.seco)
    if not args.seco:
        reescrever_indices(args.raiz)
        print("mapa:", mapa(args.raiz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
