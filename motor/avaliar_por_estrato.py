"""Onde cada metodo ganha — o agregado esconde a resposta que decide o uso.

O `avaliar_dominio.py` da um numero por metodo sobre o gabarito inteiro. Com o
gabarito de 140 perguntas isso passou a enganar: 74 das 140 sao tecnicas (papers
de arXiv, alvo literal) contra 56 comerciais (livros, alvo parafraseado). BM25
brilha no primeiro grupo e afunda no segundo, e a media dos dois nao descreve
nenhum.

Aqui os mesmos rankings sao fatiados por dominio do alvo e por leva (as 53
perguntas originais x as 87 escritas em 10/09), para responder a pergunta que
importa: **quando vale pagar 1.157 s de reranker em vez de 3 s de BM25?**

    python avaliar_por_estrato.py --seco   # so BM25 e semantico, ~1 min
    python avaliar_por_estrato.py          # inclui o reranker, ~20 min
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import buscar as bm
import dominio as dom
import semantico as S
from avaliar_dominio import RAIZ, metricas, pasta, ranquear_documentos, alvo_no_disco
from gabarito import GABARITO, TRADUCAO

N_ORIGINAIS = 53  # as perguntas anteriores a leva de 10/09/2026


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raiz", type=Path, default=RAIZ)
    ap.add_argument("--seco", action="store_true", help="pula o reranker")
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

    contexto = []
    for i, (pergunta, alvos) in enumerate(GABARITO):
        cats = alvo_no_disco(raiz, alvos)
        doms = sorted({d for c in cats if (d := dom.de_categoria(raiz, c))})
        contexto.append({
            "pergunta": pergunta,
            "alvos": alvos,
            "categoria": cats[0] if len(cats) == 1 else None,
            "dominio": doms[0] if len(doms) == 1 else None,
            "leva": "originais" if i < N_ORIGINAIS else "leva-10/09",
        })

    print(f"indice: {len(passagens)} passagens | perguntas: {len(contexto)}")
    modelo = S._modelo()
    qs = {c["pergunta"]: S._normalizar(
        np.array(list(modelo.embed([c["pergunta"]])), dtype=np.float32))[0]
        for c in contexto}

    def cats_de(c):
        return {c["categoria"]} if c["categoria"] else None

    def rodar_semantico():
        saida = []
        for c in contexto:
            pontos = vetores @ qs[c["pergunta"]]
            permitidas = cats_de(c)
            melhor = {}
            for i, p in enumerate(passagens):
                if permitidas is not None and p["categoria"] not in permitidas:
                    continue
                d = pasta(p["caminho"])
                if d not in melhor or pontos[i] > melhor[d]:
                    melhor[d] = float(pontos[i])
            saida.append([d for d, _ in sorted(melhor.items(), key=lambda kv: -kv[1])])
        return saida

    indice = bm.carregar_indice(raiz)

    def rodar_bm25():
        saida = []
        for c in contexto:
            consultas = [c["pergunta"]]
            if TRADUCAO.get(c["pergunta"]):
                consultas.append(TRADUCAO[c["pergunta"]])
            res = [(p, 0, d) for p, d in bm.fundir(indice, consultas)]
            permitidas = cats_de(c)
            if permitidas is not None:
                res = [r for r in res if r[2]["categoria"] in permitidas]
            saida.append(ranquear_documentos([(p, d) for p, _n, d in res]))
        return saida

    def rodar_rerank():
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        cross = TextCrossEncoder(S.RERANKER)
        saida = []
        for k, c in enumerate(contexto, 1):
            pontos = vetores @ qs[c["pergunta"]]
            ordem = np.argsort(-pontos)
            permitidas = cats_de(c)
            if permitidas is not None:
                ordem = [i for i in ordem if passagens[i]["categoria"] in permitidas]
            escolhidos = list(ordem[:args.topo])
            pares = [(i, S.texto_da_passagem(raiz, passagens[i])) for i in escolhidos]
            pares = [(i, t) for i, t in pares if t]
            if not pares:
                saida.append([])
                continue
            notas = list(cross.rerank(c["pergunta"], [t for _, t in pares]))
            melhor = {}
            for (i, _t), nota in zip(pares, notas):
                d = pasta(passagens[i]["caminho"])
                if d not in melhor or nota > melhor[d]:
                    melhor[d] = float(nota)
            saida.append([d for d, _ in sorted(melhor.items(), key=lambda kv: -kv[1])])
            if k % 20 == 0:
                print(f"    {k}/{len(contexto)}", flush=True)
        return saida

    modos = []
    for nome, fn in [("BM25 + categoria", rodar_bm25),
                     ("semantico + categoria", rodar_semantico)] + (
                     [] if args.seco else [("sem + rerank + categoria", rodar_rerank)]):
        t0 = time.time()
        print(f"\n{nome}...", flush=True)
        modos.append((nome, fn(), time.time() - t0))

    def fatia(docs, teste):
        return [(d, c["alvos"]) for d, c in zip(docs, contexto) if teste(c)]

    cortes = [
        ("TUDO", lambda c: True),
        ("  dominio comercial", lambda c: c["dominio"] == "comercial"),
        ("  dominio tecnico", lambda c: c["dominio"] == "tecnico"),
        ("  dominio pessoal", lambda c: c["dominio"] == "pessoal"),
        ("  perguntas originais", lambda c: c["leva"] == "originais"),
        ("  perguntas de 10/09", lambda c: c["leva"] == "leva-10/09"),
    ]

    print("\n\n| corte | " + " | ".join(f"{n} hit@1 | {n} hit@3" for n, _r, _t in modos) + " |")
    print("|---" * (1 + 2 * len(modos)) + "|")
    for rotulo, teste in cortes:
        celulas = []
        for _nome, docs, _t in modos:
            m = metricas(fatia(docs, teste))
            celulas += [f"{m['hit1']}/{m['n']}", f"{m['hit3']}/{m['n']}"]
        print(f"| {rotulo} | " + " | ".join(celulas) + " |")

    print("\ntempo:", ", ".join(f"{n} {t:.0f}s" for n, _r, t in modos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
