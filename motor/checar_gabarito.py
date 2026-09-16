# -*- coding: utf-8 -*-
"""Confere o gabarito: marca orfa, marca ambigua, pergunta repetida, cobertura."""
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from raiz import RAIZ_PADRAO  # noqa: E402
from gabarito import PERGUNTAS, GABARITO, TRADUCAO  # noqa: E402

raiz = RAIZ_PADRAO / "markdown"
docs = sorted({(p.parent.name, p.parent.parent.name) for p in raiz.rglob("INDEX.md")
               if p.parent.parent.name != "markdown"})
nomes = [d for d, _c in docs]

print(f"perguntas: {len(PERGUNTAS)} | GABARITO: {len(GABARITO)} | TRADUCAO: {len(TRADUCAO)}")

pt = [q for q, _e, _m in PERGUNTAS]
rep = [q for q, n in Counter(pt).items() if n > 1]
print("perguntas repetidas:", rep or "nenhuma")

orfas, ambiguas = [], []
for _q, _e, marcas in PERGUNTAS:
    for m in marcas:
        bate = [n for n in nomes if m in n]
        if not bate:
            orfas.append(m)
        elif len(bate) > 1:
            ambiguas.append((m, bate))

print("\nMARCAS ORFAS (nao casam com pasta nenhuma):", len(orfas))
for m in orfas:
    print("   ", m)

print("\nMARCAS AMBIGUAS (casam com mais de uma pasta):", len(ambiguas))
for m, bate in ambiguas:
    print("   ", m, "->", [b[:50] for b in bate])

marcas = [m for _q, _e, ms in PERGUNTAS for m in ms]
cobertos = {d for d in nomes if any(m in d for m in marcas)}
print(f"\ncobertura: {len(cobertos)}/{len(nomes)} documentos "
      f"({len(nomes) - len(cobertos)} ainda sem pergunta)")

falta = defaultdict(list)
for d, c in docs:
    if d not in cobertos:
        falta[c].append(d)
print("\nainda descoberto, por categoria:")
for c in sorted(falta, key=lambda k: -len(falta[k])):
    print(f"  {c} ({len(falta[c])}): " + ", ".join(x[:38] for x in falta[c])[:150])
