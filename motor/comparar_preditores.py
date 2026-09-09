"""Compara jeitos de adivinhar a categoria da pergunta, sem reranker.

O centroide (`prever_categoria.py`) acerta so 52% de primeira porque a media de
uma categoria inteira apaga o que a distingue: `vendas`, `copy-persuasao`,
`marketing` e `posicionamento-negocio` viram quase o mesmo vetor.

Aqui entra a alternativa que faltava testar: **voto das passagens** (pseudo-
relevance feedback). Em vez de comparar a pergunta com a media da categoria,
roda a busca sem filtro e deixa as passagens mais parecidas votarem na propria
categoria. Evidencia fraca e espalhada soma; media nao soma, dilui.

    python comparar_preditores.py
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import prever_categoria as PC  # noqa: E402
import semantico as S  # noqa: E402
from gabarito import GABARITO  # noqa: E402

from raiz import RAIZ_PADRAO  # noqa: E402


def votar(passagens, pontos, topo: int = 200, k: int = 3, rrf: int = 10):
    """Categorias mais votadas pelas `topo` passagens mais parecidas.

    Peso por rank reciproco (1/(rrf+posicao)) e nao pela similaridade crua: a
    similaridade do MiniLM vive num intervalo estreito, entao somar valor bruto
    faz a categoria com mais passagens no indice ganhar quase sempre. O rank
    normaliza isso.
    """
    ordem = np.argsort(-pontos)[:topo]
    placar = defaultdict(float)
    for posicao, i in enumerate(ordem):
        placar[passagens[i].get("categoria", "geral")] += 1.0 / (rrf + posicao)
    return [c for c, _ in sorted(placar.items(), key=lambda kv: -kv[1])][:k]


def votar_por_documento(passagens, pontos, topo: int = 200, k: int = 3):
    """Igual ao voto, mas cada documento vota uma vez, com sua melhor passagem.

    Sem isso um livro de 1 milhao de palavras enche o top-200 sozinho e elege a
    propria categoria.
    """
    ordem = np.argsort(-pontos)[:topo]
    melhor_doc = {}
    for i in ordem:
        p = passagens[i]
        doc = Path(p["caminho"]).parent.name
        if doc not in melhor_doc:
            melhor_doc[doc] = (float(pontos[i]), p.get("categoria", "geral"))
    placar = defaultdict(float)
    for posicao, (_doc, (_s, cat)) in enumerate(
            sorted(melhor_doc.items(), key=lambda kv: -kv[1][0])):
        placar[cat] += 1.0 / (10 + posicao)
    return [c for c, _ in sorted(placar.items(), key=lambda kv: -kv[1])][:k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--topo", type=int, default=200)
    args = ap.parse_args()

    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    raiz = args.raiz
    meta, vetores = S.carregar(raiz)
    if meta is None:
        print("indice semantico nao existe")
        return 1
    vetores = vetores.astype(np.float32)
    passagens = meta["passagens"]
    verdadeira = PC._categoria_verdadeira(raiz)
    modelo = S._modelo()

    metodos = {
        "centroide": None,          # tratado a parte
        "voto-passagem": lambda p: votar(passagens, p, args.topo),
        "voto-documento": lambda p: votar_por_documento(passagens, p, args.topo),
    }
    acertos = {nome: {1: 0, 2: 0, 3: 0} for nome in metodos}
    n = 0
    divergencias = []

    for pergunta, marcas in GABARITO:
        esperadas = {cat for pasta, cat in verdadeira.items()
                     if any(m in pasta for m in marcas)}
        if not esperadas:
            continue
        n += 1
        q = S._normalizar(np.array(list(modelo.embed([pergunta])),
                                   dtype=np.float32))[0]
        pontos = vetores @ q

        previsoes = {}
        previsoes["centroide"] = [c for c, _s in PC.prever(raiz, pergunta, k=3)]
        for nome, fn in metodos.items():
            if fn is not None:
                previsoes[nome] = fn(pontos)

        for nome, ordem in previsoes.items():
            for k in (1, 2, 3):
                if esperadas & set(ordem[:k]):
                    acertos[nome][k] += 1

        if (esperadas & set(previsoes["voto-documento"][:1])) and not (
                esperadas & set(previsoes["centroide"][:1])):
            divergencias.append((pergunta, sorted(esperadas),
                                 previsoes["centroide"][0],
                                 previsoes["voto-documento"][0]))

    print(f"{n} perguntas com categoria conhecida\n")
    print(f"{'metodo':18} {'top-1':>12} {'top-2':>12} {'top-3':>12}")
    for nome in metodos:
        a = acertos[nome]
        print(f"{nome:18} " + " ".join(
            f"{a[k]:3d}/{n} ({a[k] * 100 // n:2d}%)" for k in (1, 2, 3)))

    if divergencias:
        print(f"\nvoto acertou de primeira onde o centroide errou "
              f"({len(divergencias)}):")
        for pergunta, esperadas, cen, voto in divergencias[:8]:
            print(f"  {pergunta[:46]:46} esperava {esperadas}")
            print(f"  {'':46} centroide={cen}  voto={voto}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
