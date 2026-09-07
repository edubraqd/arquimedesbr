"""Mede o gabarito de 53 perguntas contra o indice inteiro, com e sem recorte.

Diferente do `avaliar_modelo.py`, que compara modelos de embedding num pool
amostrado, aqui o modelo e fixo e o que varia e **o quanto do corpus entra na
disputa**. A pergunta que este arquivo responde: `--dominio` e `--categoria`
pagam o que prometem quando medidos em 53 perguntas, e nao em 3?

Carrega indice e modelos uma vez so. Rodar cada consulta num processo novo
custava ~50 s, quase tudo em carregar 1,1 GB de reranker; em memoria a mesma
consulta sai em ~6 s.

    python avaliar_dominio.py --seco       # so os modos rapidos, sem reranker
    python avaliar_dominio.py              # tudo

Os recortes usam o dominio e a categoria **do alvo**, entao medem o teto: o
ganho de quem escolhe o recorte certo. Escolher dominio errado nao esta medido
aqui — e a pergunta seguinte, nao esta.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import dominio as dom  # noqa: E402
import semantico as S  # noqa: E402
import buscar as bm  # noqa: E402
from gabarito import GABARITO, TRADUCAO  # noqa: E402

from raiz import RAIZ_PADRAO as RAIZ  # noqa: E402


def pasta(caminho: str) -> str:
    """markdown/<categoria>/<documento>/<cap>.md -> '<categoria>/<documento>'."""
    partes = re.split(r"[\\/]", caminho)
    return "/".join(partes[1:3]) if len(partes) >= 3 else caminho


def categoria(caminho: str) -> str:
    return re.split(r"[\\/]", caminho)[1]


def acerta(caminho: str, alvos: list[str]) -> bool:
    return any(a in caminho.replace("\\", "/") for a in alvos)


def ranquear_documentos(pares) -> list[str]:
    """(pontos, meta) por capitulo -> lista de documentos, melhor primeiro."""
    vistos, saida = set(), []
    for _pontos, p in pares:
        d = pasta(p["caminho"])
        if d not in vistos:
            vistos.add(d)
            saida.append(d)
    return saida


def metricas(rankings: list[tuple[list[str], list[str]]]) -> dict:
    """hit@1, hit@3 e MRR sobre (documentos_ranqueados, alvos)."""
    h1 = h3 = 0
    rr = 0.0
    for docs, alvos in rankings:
        posicao = next((i for i, d in enumerate(docs) if acerta(d, alvos)), None)
        if posicao is None:
            continue
        if posicao == 0:
            h1 += 1
        if posicao < 3:
            h3 += 1
        rr += 1 / (posicao + 1)
    n = len(rankings)
    return {"hit1": h1, "hit3": h3, "mrr": rr / n if n else 0.0, "n": n}


def alvo_no_disco(raiz: Path, alvos: list[str]) -> list[str]:
    """Categorias em que os documentos-alvo realmente estao."""
    cats = set()
    for d in (raiz / "markdown").iterdir():
        if not d.is_dir():
            continue
        for doc in d.iterdir():
            if doc.is_dir() and any(a in doc.name for a in alvos):
                cats.add(d.name)
    return sorted(cats)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raiz", type=Path, default=RAIZ)
    ap.add_argument("--seco", action="store_true", help="pula os modos com reranker")
    ap.add_argument("--topo", type=int, default=50)
    args = ap.parse_args()

    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    raiz = args.raiz
    meta, vetores = S.carregar(raiz)
    if meta is None:
        print("indice semantico nao existe - rode: python semantico.py indexar")
        return 1
    vetores = vetores.astype(np.float32)
    passagens = meta["passagens"]
    print(f"indice: {len(passagens)} passagens, {len({pasta(p['caminho']) for p in passagens})} documentos")

    # Cada pergunta ganha o dominio e a categoria do seu alvo. Onde o alvo mora em
    # duas categorias, o recorte por categoria nao se aplica (seria arbitrario).
    contexto = []
    for pergunta, alvos in GABARITO:
        cats = alvo_no_disco(raiz, alvos)
        doms = sorted({d for c in cats if (d := dom.de_categoria(raiz, c))})
        contexto.append({
            "pergunta": pergunta,
            "alvos": alvos,
            "categorias": cats,
            "dominio": doms[0] if len(doms) == 1 else None,
            "categoria": cats[0] if len(cats) == 1 else None,
        })

    sem_dom = [c for c in contexto if not c["dominio"]]
    sem_cat = [c for c in contexto if not c["categoria"]]
    print(f"perguntas: {len(contexto)} | sem dominio unico: {len(sem_dom)} | "
          f"sem categoria unica: {len(sem_cat)}")
    por_dom = {}
    for c in contexto:
        por_dom[c["dominio"]] = por_dom.get(c["dominio"], 0) + 1
    print("distribuicao:", ", ".join(f"{k or 'ambiguo'}={v}" for k, v in sorted(
        por_dom.items(), key=lambda kv: (kv[0] is None, kv[0]))))
    print()

    modelo = S._modelo()

    def consultar(texto: str) -> np.ndarray:
        v = np.array(list(modelo.embed([texto])), dtype=np.float32)
        return S._normalizar(v)[0]

    print("embutindo as 53 perguntas...", end=" ", flush=True)
    t0 = time.time()
    qs = {c["pergunta"]: consultar(c["pergunta"]) for c in contexto}
    print(f"{time.time() - t0:.0f}s")

    def permitidas_de(c, chave):
        if chave is None:
            return None
        if chave == "dominio":
            return dom.categorias(raiz, c["dominio"]) if c["dominio"] else None
        return {c["categoria"]} if c["categoria"] else None

    # ------------------------------------------------------------ semantico
    def rodar_semantico(chave):
        saida = []
        for c in contexto:
            pontos = vetores @ qs[c["pergunta"]]
            permitidas = permitidas_de(c, chave)
            melhor = {}
            for i, p in enumerate(passagens):
                if permitidas is not None and p["categoria"] not in permitidas:
                    continue
                d = pasta(p["caminho"])
                if d not in melhor or pontos[i] > melhor[d]:
                    melhor[d] = float(pontos[i])
            docs = [d for d, _ in sorted(melhor.items(), key=lambda kv: -kv[1])]
            saida.append((docs, c["alvos"]))
        return saida

    # ----------------------------------------------------------------- BM25
    indice = bm.carregar_indice(raiz)

    def rodar_bm25(chave, bilingue=True):
        saida = []
        for c in contexto:
            consultas = [c["pergunta"]]
            if bilingue and TRADUCAO.get(c["pergunta"]):
                consultas.append(TRADUCAO[c["pergunta"]])
            if len(consultas) > 1:
                res = [(p, 0, d) for p, d in bm.fundir(indice, consultas)]
            else:
                res = bm.bm25(indice, consultas[0])
            permitidas = permitidas_de(c, chave)
            if permitidas is not None:
                res = [r for r in res if r[2]["categoria"] in permitidas]
            saida.append((ranquear_documentos([(p, d) for p, _n, d in res]),
                          c["alvos"]))
        return saida

    # ------------------------------------------------------------- reranker
    def rodar_rerank(chave):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        cross = TextCrossEncoder(S.RERANKER)
        saida = []
        for k, c in enumerate(contexto, 1):
            pontos = vetores @ qs[c["pergunta"]]
            ordem = np.argsort(-pontos)
            permitidas = permitidas_de(c, chave)
            if permitidas is not None:
                ordem = [i for i in ordem if passagens[i]["categoria"] in permitidas]
            escolhidos = list(ordem[:args.topo])
            pares = [(i, S.texto_da_passagem(raiz, passagens[i])) for i in escolhidos]
            pares = [(i, t) for i, t in pares if t]
            if not pares:
                saida.append(([], c["alvos"]))
                continue
            notas = list(cross.rerank(c["pergunta"], [t for _, t in pares]))
            melhor = {}
            for (i, _t), nota in zip(pares, notas):
                d = pasta(passagens[i]["caminho"])
                if d not in melhor or nota > melhor[d]:
                    melhor[d] = float(nota)
            docs = [d for d, _ in sorted(melhor.items(), key=lambda kv: -kv[1])]
            saida.append((docs, c["alvos"]))
            if k % 10 == 0:
                print(f"    {k}/{len(contexto)}", flush=True)
        return saida

    linhas = []

    def medir(rotulo, fn):
        t = time.time()
        r = metricas(fn())
        r["rotulo"] = rotulo
        r["seg"] = time.time() - t
        linhas.append(r)
        print(f"  {rotulo:44s} hit@1 {r['hit1']:2d}/{r['n']}  "
              f"hit@3 {r['hit3']:2d}/{r['n']}  MRR {r['mrr']:.3f}  "
              f"({r['seg']:.0f}s)", flush=True)

    print("BM25 bilingue")
    medir("BM25 bilingue", lambda: rodar_bm25(None))
    medir("BM25 bilingue + --dominio", lambda: rodar_bm25("dominio"))
    medir("BM25 bilingue + --categoria", lambda: rodar_bm25("categoria"))
    print()
    print("semantico")
    medir("semantico", lambda: rodar_semantico(None))
    medir("semantico + --dominio", lambda: rodar_semantico("dominio"))
    medir("semantico + --categoria", lambda: rodar_semantico("categoria"))

    if not args.seco:
        print()
        print(f"semantico + reranker (topo {args.topo}) - ~6s por pergunta")
        medir("semantico + rerank", lambda: rodar_rerank(None))
        medir("semantico + rerank + --dominio", lambda: rodar_rerank("dominio"))
        medir("semantico + rerank + --categoria", lambda: rodar_rerank("categoria"))

    print()
    print("| Metodo | hit@1 | hit@3 | MRR |")
    print("|---|---|---|---|")
    for r in linhas:
        print(f"| {r['rotulo']} | {r['hit1']}/{r['n']} | {r['hit3']}/{r['n']} | "
              f"{r['mrr']:.3f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
