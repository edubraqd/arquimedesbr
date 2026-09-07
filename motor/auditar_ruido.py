"""Mede o preco de cada documento na base: ele responde ou so atrapalha?

Todo documento novo e uma faca de dois gumes. Responde perguntas que antes
ficavam sem resposta, mas tambem entra como distrator em toda busca sobre outro
assunto. Este script poe numero nos dois lados, usando o indice de producao e o
gabarito de 53 perguntas:

- **cobertura**: em quantas perguntas o documento certo aparece no top-3;
- **ruido**: quantas vezes um documento que nao e alvo de nenhuma pergunta
  ocupa lugar no top-3, e de que tipo ele e.

Rodar antes e depois de incluir uma leva responde "valeu a pena?" com medida em
vez de opiniao.

    python auditar_ruido.py                 # usa o indice atual
    python auditar_ruido.py --sem-rerank    # mais rapido, mede o retrieval cru
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import semantico as S
from buscar import _frontmatter
from gabarito import GABARITO

from raiz import RAIZ_PADRAO  # noqa: E402


def _fichas(raiz: Path) -> dict:
    """pasta do documento -> (titulo, tipo, categoria)."""
    saida = {}
    for pasta in sorted((raiz / "markdown").glob("*/*")):
        caps = [p for p in pasta.glob("*.md") if p.name != "INDEX.md"]
        if not caps:
            continue
        campos = _frontmatter(caps[0].read_text(encoding="utf-8", errors="replace"))
        saida[pasta.name] = (
            campos.get("titulo", pasta.name),
            campos.get("tipo", "livro"),
            campos.get("categoria", pasta.parent.name),
        )
    return saida


def auditar(raiz: Path, rerank: bool = True, topo: int = 3) -> None:
    fichas = _fichas(raiz)
    alvos_do_gabarito = {m for _q, marcas in GABARITO for m in marcas}

    def e_alvo(pasta: str, marcas) -> bool:
        return any(m in pasta for m in marcas)

    acertos = 0
    intrusos = Counter()
    intrusos_por_tipo = Counter()
    sem_resposta = []

    for i, (pergunta, marcas) in enumerate(GABARITO, 1):
        achados = (
            S.reranquear(raiz, pergunta, n=topo)
            if rerank else S.procurar(raiz, pergunta, n=topo)
        )
        if not achados:
            continue
        pastas = [Path(p["caminho"]).parent.name for _n, p in achados]
        if any(e_alvo(x, marcas) for x in pastas):
            acertos += 1
        else:
            sem_resposta.append((pergunta, pastas[0]))
        for pasta in pastas:
            # intruso = ocupa o top-3 sem ser alvo desta pergunta nem de nenhuma
            if e_alvo(pasta, marcas):
                continue
            if any(a in pasta for a in alvos_do_gabarito):
                continue
            intrusos[pasta] += 1
            intrusos_por_tipo[fichas.get(pasta, ("", "?", ""))[1]] += 1
        print(f"  {i}/{len(GABARITO)}", end="\r", flush=True)

    n = len(GABARITO)
    print(f"\ncobertura: alvo no top-{topo} em {acertos}/{n} perguntas")
    print(f"ruido: {sum(intrusos.values())} aparicoes de documento que nao "
          f"responde nada do gabarito\n")

    if intrusos_por_tipo:
        print("por tipo de documento:")
        for tipo, quantas in intrusos_por_tipo.most_common():
            print(f"  {tipo:10} {quantas}")
        print()
    if intrusos:
        print("quem mais aparece sem ser chamado:")
        for pasta, quantas in intrusos.most_common(10):
            titulo, tipo, _cat = fichas.get(pasta, (pasta, "?", ""))
            print(f"  {quantas:3}x  [{tipo}] {titulo[:62]}")
        print()
    if sem_resposta:
        print(f"perguntas sem o alvo no top-{topo} ({len(sem_resposta)}):")
        for pergunta, primeiro in sem_resposta[:12]:
            titulo = fichas.get(primeiro, (primeiro, "", ""))[0]
            print(f"  {pergunta[:58]:58} -> veio {titulo[:34]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--sem-rerank", action="store_true")
    ap.add_argument("--topo", type=int, default=3)
    args = ap.parse_args()
    auditar(args.raiz, rerank=not args.sem_rerank, topo=args.topo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
