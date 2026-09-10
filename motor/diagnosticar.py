"""Onde a busca erra, e contra quem perde.

O `avaliar_dominio.py` responde "quanto acerta". Este responde "o que impede
de acertar" -- que e a pergunta que diz o que consertar. Sem ele, melhorar a
busca vira palpite: mexe-se num parametro, o numero sobe ou desce, e ninguem
sabe por que.

Para cada pergunta do gabarito, registra em que posicao o alvo aparece e, quando
ele fica fora do top-3, QUEM ganhou dele. Depois agrupa os erros em familias:

- `distrator-de-outra-categoria`: quem venceu nao e nem do dominio da pergunta.
  Sintoma de vocabulario colidindo entre areas; remedio e recorte.
- `distrator-vizinho`: quem venceu e da mesma categoria do alvo. Recorte nao
  resolve; e questao de ranqueamento ou de o corpus ter dois livros que de fato
  respondem.
- `alvo-invisivel`: o alvo nao aparece nem no top-50. Nao e ranqueamento, e
  recuperacao: a passagem certa nao esta perto da pergunta em espaco vetorial.

    python diagnosticar.py                  # semantico puro, ~30 s
    python diagnosticar.py --categoria      # com o recorte do alvo
    python diagnosticar.py --n 10           # quantos erros detalhar
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import dominio as dom  # noqa: E402
import semantico as S  # noqa: E402
from gabarito import GABARITO  # noqa: E402

from raiz import RAIZ_PADRAO  # noqa: E402

TOPO = 50


def pasta(caminho: str) -> str:
    partes = caminho.replace("\\", "/").split("/")
    return "/".join(partes[1:3]) if len(partes) >= 3 else caminho


def casa(alvos, doc: str) -> bool:
    nome = doc.split("/")[-1]
    return any(a in nome for a in alvos)


def ranquear(vetores, passagens, consulta, indices=None):
    """Melhor passagem por documento, em ordem. Devolve [(doc, score, meta)]."""
    if indices is None:
        sub, subp = vetores, passagens
    else:
        sub = vetores[indices]
        subp = [passagens[i] for i in indices]
    if not len(sub):
        return []
    pontos = sub @ consulta
    melhor: dict = {}
    for i in np.argsort(-pontos)[: TOPO * 40]:
        p = subp[i]
        d = pasta(p["caminho"])
        if d not in melhor:
            melhor[d] = (float(pontos[i]), p)
    return sorted(
        ((d, s, m) for d, (s, m) in melhor.items()), key=lambda x: -x[1]
    )[:TOPO]


def familia(alvos, posicao: int, ranking, categorias_alvo) -> str:
    if posicao == 1:
        return "acerto"
    if posicao <= 3:
        return "acerto-top3"
    if posicao == 0:
        return "alvo-invisivel"
    vencedor = ranking[0]
    cat = vencedor[2].get("categoria", "")
    if cat in categorias_alvo:
        return "distrator-vizinho"
    return "distrator-de-outra-categoria"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--categoria", action="store_true",
                    help="recorta pela categoria do alvo (mede o teto)")
    ap.add_argument("--n", type=int, default=8, help="quantos erros detalhar")
    args = ap.parse_args()

    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    meta, vetores = S.carregar(args.raiz)
    if meta is None:
        print("indice semantico nao existe - rode: python semantico.py indexar")
        return 1
    vetores = vetores.astype(np.float32)
    passagens = meta["passagens"]
    modo = meta.get("contexto", "nenhum")
    docs = {pasta(p["caminho"]) for p in passagens}
    print(f"indice: {len(passagens)} passagens, {len(docs)} documentos, "
          f"contexto={modo}\n")

    modelo = S._modelo()
    perguntas = [p for p, _ in GABARITO]
    consultas = S._normalizar(np.array(list(modelo.embed(perguntas)),
                                       dtype=np.float32))

    por_categoria: dict = {}
    for i, p in enumerate(passagens):
        por_categoria.setdefault(p.get("categoria", ""), []).append(i)

    placar, erros = Counter(), []
    reciproco = 0.0
    for (pergunta, alvos), consulta in zip(GABARITO, consultas):
        cats_alvo = sorted({
            d.split("/")[0] for d in docs if casa(alvos, d)
        })
        indices = None
        if args.categoria and len(cats_alvo) == 1:
            indices = por_categoria.get(cats_alvo[0])
        ranking = ranquear(vetores, passagens, consulta, indices)
        posicao = next((i + 1 for i, (d, _s, _m) in enumerate(ranking)
                        if casa(alvos, d)), 0)
        reciproco += 1 / posicao if posicao else 0.0
        fam = familia(alvos, posicao, ranking, cats_alvo)
        placar[fam] += 1
        if fam not in ("acerto", "acerto-top3"):
            erros.append((fam, pergunta, alvos, posicao, ranking[:2]))

    n = len(GABARITO)
    print(f"MRR {reciproco / n:.3f}   "
          f"hit@1 {placar['acerto']}/{n}   "
          f"hit@3 {placar['acerto'] + placar['acerto-top3']}/{n}\n")
    print("familias de erro:")
    for fam, q in placar.most_common():
        if fam.startswith("acerto"):
            continue
        print(f"  {q:>3}  {fam}")

    print(f"\n--- {min(args.n, len(erros))} erros em detalhe ---")
    for fam, pergunta, alvos, posicao, topo in erros[: args.n]:
        onde = f"alvo em {posicao}o" if posicao else "alvo fora do top-50"
        print(f"\n[{fam}] {onde}")
        print(f"  pergunta: {pergunta}")
        print(f"  alvo:     {', '.join(alvos)}")
        for d, s, m in topo:
            print(f"  venceu:   {s:+.3f}  {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
