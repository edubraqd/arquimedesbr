"""Busca BM25 na base, sem dependencia externa e sem chamada de rede.

O indice fica em `.indice-busca.json` e so e reconstruido quando algum arquivo
mudou. Serve para o agente localizar o capitulo certo antes de ler qualquer
coisa, em vez de abrir livro inteiro.

    python buscar.py "objection handling"
    python buscar.py "precificacao por valor" --n 15 --categoria posicionamento-negocio
    python buscar.py "borrow checker" --trechos
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import dominio as dom

from raiz import RAIZ_PADRAO  # noqa: E402
NOME_INDICE = ".indice-busca.json"

_PARADAS = set(
    """a o os as um uma uns umas de do da dos das em no na nos nas por para com sem
    que se e ou mas como quando onde qual quais ao aos aa as ser sao foi era isso
    este esta esse essa aquele aquela seu sua seus suas mais menos muito ja nao sim
    the a an of to in for on with as at by from is are was were be been it this that
    these those and or but if then than so such not no yes you your we our they their
    can will would should could may might have has had do does did""".split()
)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_]{1,}")


def tokenizar(texto: str) -> list:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = texto.encode("ascii", "ignore").decode("ascii")
    return [t for t in _TOKEN.findall(texto) if t not in _PARADAS]


def _frontmatter(texto: str) -> dict:
    if not texto.startswith("---"):
        return {}
    fim = texto.find("\n---", 3)
    if fim == -1:
        return {}
    campos = {}
    for linha in texto[3:fim].strip().splitlines():
        if ":" not in linha:
            continue
        k, v = linha.split(":", 1)
        campos[k.strip()] = v.strip().strip('"')
    return campos


def construir_indice(raiz: Path) -> dict:
    raiz_md = raiz / "markdown"
    docs = []
    for caminho in sorted(raiz_md.rglob("*.md")):
        if caminho.name == "INDEX.md":
            continue
        texto = caminho.read_text(encoding="utf-8", errors="replace")
        meta = _frontmatter(texto)
        if meta.get("util") == "nao":
            continue        # copyright, sumario, indice remissivo, pagina de venda
        tokens = tokenizar(texto)
        if not tokens:
            continue
        docs.append(
            {
                "caminho": str(caminho.relative_to(raiz)).replace("\\", "/"),
                "titulo": meta.get("titulo", caminho.parent.name),
                "capitulo": meta.get("capitulo", caminho.stem),
                "categoria": meta.get("categoria", caminho.parent.parent.name),
                "idioma": meta.get("idioma", "xx"),
                "paginas": meta.get("paginas", ""),
                "n": len(tokens),
                "tf": dict(Counter(tokens)),
                "mtime": caminho.stat().st_mtime,
            }
        )
    df = Counter()
    for d in docs:
        df.update(d["tf"].keys())
    return {"docs": docs, "df": dict(df), "total": len(docs),
            "media": (sum(d["n"] for d in docs) / len(docs)) if docs else 0}


def _mudou(raiz: Path, indice: dict) -> bool:
    atuais = {
        str(p.relative_to(raiz)).replace("\\", "/"): p.stat().st_mtime
        for p in (raiz / "markdown").rglob("*.md")
        if p.name != "INDEX.md"
    }
    antigos = {d["caminho"]: d["mtime"] for d in indice.get("docs", [])}
    return atuais != antigos


def carregar_indice(raiz: Path, forcar: bool = False) -> dict:
    caminho = raiz / NOME_INDICE
    if not forcar and caminho.exists():
        try:
            indice = json.loads(caminho.read_text(encoding="utf-8"))
            if not _mudou(raiz, indice):
                return indice
        except json.JSONDecodeError:
            pass
    indice = construir_indice(raiz)
    caminho.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
    return indice


def bm25(indice: dict, consulta: str, k1: float = 1.5, b: float = 0.75) -> list:
    termos = tokenizar(consulta)
    if not termos:
        return []
    N, media = indice["total"], indice["media"] or 1
    df = indice["df"]
    saida = []
    for d in indice["docs"]:
        pontos = 0.0
        acertos = []
        for termo in termos:
            f = d["tf"].get(termo, 0)
            if not f:
                continue
            idf = math.log(1 + (N - df.get(termo, 0) + 0.5) / (df.get(termo, 0) + 0.5))
            pontos += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * d["n"] / media))
            acertos.append(termo)
        if pontos:
            saida.append((pontos, len(set(acertos)), d))
    # Ordenar por numero de termos distintos antes do score deixava o documento
    # gigante ganhar sempre: a Encyclopedia of Big Data (478 mil palavras) casa
    # qualquer combinacao de termos e vencia quem de fato trata do assunto.
    # O BM25 ja premia cobertura, porque soma uma parcela por termo.
    saida.sort(key=lambda x: -x[0])
    return saida


def fundir(indice: dict, consultas: list, k: int = 60) -> list:
    """BM25 em varias consultas, fundido por rank reciproco.

    Serve para o caso que domina esta base: 33 dos 58 documentos estao em ingles
    e as perguntas saem em portugues. Medido — "objecao de preco" em portugues
    nao acha nada util; "price objection too expensive" acha Gap Selling cap. 13
    e Pricing Creativity cap. 8. Rodar as duas e fundir cobre os dois lados sem
    depender de modelo nenhum.
    """
    placar, ficha = {}, {}
    for consulta in consultas:
        for posicao, (_pontos, _n, d) in enumerate(bm25(indice, consulta)[:200]):
            c = d["caminho"]
            # MELHOR rank, nao a soma: as consultas nao sao evidencias
            # independentes do mesmo item, sao alternativas por idioma. Somando,
            # quem aparecia mediano nas duas listas (documento gigante e
            # generico) passava na frente de quem era primeiro colocado numa so.
            placar[c] = max(placar.get(c, 0.0), 1 / (k + posicao + 1))
            ficha.setdefault(c, d)
    return [(p, ficha[c]) for c, p in sorted(placar.items(), key=lambda kv: -kv[1])]


def trecho(raiz: Path, doc: dict, termos: list, largura: int = 240) -> str:
    texto = (raiz / doc["caminho"]).read_text(encoding="utf-8", errors="replace")
    if texto.startswith("---"):  # trecho vem do corpo, nao do frontmatter
        fim = texto.find("\n---", 3)
        if fim != -1:
            texto = texto[fim + 4:]
    plano = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    for termo in termos:
        i = plano.find(termo)
        if i != -1:
            ini = max(0, i - largura // 2)
            return "..." + re.sub(r"\s+", " ", texto[ini:ini + largura]).strip() + "..."
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Busca na base de conhecimento")
    ap.add_argument("consulta", nargs="+")
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--categoria")
    dom.adicionar_argumento(ap)
    ap.add_argument("--trechos", action="store_true")
    ap.add_argument("--tambem", action="append", default=[], metavar="CONSULTA",
                    help="mesma busca noutro idioma; funde por rank reciproco")
    ap.add_argument("--reindexar", action="store_true")
    args = ap.parse_args()

    # O console do Windows abre em cp1252 e o corpus tem caractere que ele
    # nao codifica. Medido em 07/09: `objecao de preco --trechos` morria com
    # UnicodeEncodeError em '■' depois de ja ter impresso meia lista.
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    consulta = " ".join(args.consulta)
    indice = carregar_indice(args.raiz, forcar=args.reindexar)
    if not indice["total"]:
        print("base vazia - rode motor/processar.py antes")
        return 1

    if args.tambem:
        resultados = [(p, 0, d) for p, d in fundir(indice, [consulta] + args.tambem)]
        rotulo = " + ".join(f'"{c}"' for c in [consulta] + args.tambem)
    else:
        resultados = bm25(indice, consulta)
        rotulo = f'"{consulta}"'
    if args.categoria:
        resultados = [r for r in resultados if r[2]["categoria"] == args.categoria]
    permitidas = dom.categorias(args.raiz, args.dominio)
    if permitidas is not None:
        resultados = [r for r in resultados if r[2]["categoria"] in permitidas]
    if not resultados:
        print(f"nada para {rotulo}")
        return 1

    termos = tokenizar(" ".join([consulta] + args.tambem))
    print(f"{len(resultados)} capitulos com {rotulo} (top {min(args.n, len(resultados))}):")
    print()
    for pontos, n_termos, d in resultados[: args.n]:
        print(f"{pontos:7.3f}  {d['titulo']} — {d['capitulo']}")
        print(f"        {d['categoria']} [{d.get('idioma','xx')}] "
              f"· pag {d['paginas'] or '?'} · {d['caminho']}")
        if args.trechos:
            t = trecho(args.raiz, d, termos)
            if t:
                print(f"        {t}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
