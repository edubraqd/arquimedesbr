"""Grafo de conceitos da base — deterministico, offline, sem LLM.

Nao substitui o graphify (que le semantica com modelo); cobre a parte barata:
quais conceitos cada documento carrega, quais documentos falam da mesma coisa e
quais conceitos atravessam categorias diferentes — que e onde costuma estar a
ideia nao obvia.

    python grafear.py                 # reconstroi grafo.json + GRAFO.md
    python grafear.py --conceitos 40  # mais conceitos por documento
    python grafear.py --ponte "preco" # quem mais fala desse conceito
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from buscar import _frontmatter, tokenizar  # noqa: E402

from raiz import RAIZ_PADRAO  # noqa: E402
PERCENTIL_ARESTA = 0.90   # so a cauda de cima do cosseno vira ligacao
PISO_ARESTA = 0.09        # abaixo disso nao e semelhanca, e ruido de vocabulario
VIZINHOS_MIN = 3          # cada documento mantem seus 3 vizinhos mais proximos
MIN_OCORRENCIAS = 4       # termo raro demais nao vira conceito


def _termos_do_arquivo(caminho: Path) -> list:
    texto = caminho.read_text(encoding="utf-8", errors="replace")
    if texto.startswith("---"):
        fim = texto.find("\n---", 3)
        if fim != -1:
            texto = texto[fim + 4:]
    unigramas = tokenizar(texto)
    bigramas = [
        f"{a} {b}" for a, b in zip(unigramas, unigramas[1:])
        if len(a) > 3 and len(b) > 3
    ]
    return unigramas + bigramas


def coletar(raiz: Path) -> dict:
    """tf por documento (a pasta do livro), nao por capitulo."""
    docs = {}
    for caminho in sorted((raiz / "markdown").rglob("*.md")):
        if caminho.name == "INDEX.md":
            continue
        pasta = caminho.parent.name
        categoria = caminho.parent.parent.name
        d = docs.setdefault(
            pasta,
            {"pasta": pasta, "categoria": categoria, "titulo": pasta,
             "tf": Counter(), "capitulos": 0, "n": 0},
        )
        if d["capitulos"] == 0:
            meta = _frontmatter(caminho.read_text(encoding="utf-8", errors="replace")[:1200])
            d["titulo"] = meta.get("titulo", pasta)
        termos = _termos_do_arquivo(caminho)
        d["tf"].update(termos)
        d["n"] += len(termos)
        d["capitulos"] += 1
    return docs


def tfidf(docs: dict, top: int):
    """Devolve (vetor completo normalizado, top conceitos) por documento.

    A similaridade usa o vetor inteiro: comparar so os top-N nao acha vizinho,
    porque o topo de dois livros diferentes quase nunca coincide.
    """
    N = len(docs)
    df = Counter()
    for d in docs.values():
        df.update({t for t, c in d["tf"].items() if c >= MIN_OCORRENCIAS})
    pesos, conceitos = {}, {}
    for pasta, d in docs.items():
        vetor = {}
        for termo, c in d["tf"].items():
            if c < MIN_OCORRENCIAS or termo not in df:
                continue
            if df[termo] > N * 0.7:          # termo em quase todo mundo nao distingue
                continue
            idf = math.log(N / df[termo]) + 1
            vetor[termo] = (1 + math.log(c)) * idf
        norma = math.sqrt(sum(v * v for v in vetor.values())) or 1.0
        vetor = {t: v / norma for t, v in vetor.items()}
        pesos[pasta] = vetor
        conceitos[pasta] = list(dict(sorted(vetor.items(), key=lambda kv: -kv[1])[:top]))
    return pesos, conceitos


def cosseno(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def comunidades(nos: list, sims: dict, corte: float) -> dict:
    """Aglomerativo com average-linkage: junta os dois grupos mais parecidos ate
    que o melhor par fique abaixo do corte.

    Label propagation colapsava tudo num grupo so: com 39 nos e cauda densa, um
    unico rotulo se espalhava pelo grafo inteiro.
    """
    grupos = {i: [n] for i, n in enumerate(nos)}

    def media(ga: list, gb: list) -> float:
        pares = [sims.get(frozenset((a, b)), 0.0) for a in ga for b in gb if a != b]
        return sum(pares) / len(pares) if pares else 0.0

    while len(grupos) > 1:
        melhor, par = 0.0, None
        ids = list(grupos)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                s = media(grupos[a], grupos[b])
                if s > melhor:
                    melhor, par = s, (a, b)
        if par is None or melhor < corte:
            break
        a, b = par
        grupos[a] = grupos[a] + grupos.pop(b)

    return {no: gid for gid, membros in grupos.items() for no in membros}


def construir(raiz: Path, top: int) -> dict:
    docs = coletar(raiz)
    pesos, conceitos = tfidf(docs, top)
    nomes = list(docs)

    todos = []
    for i, a in enumerate(nomes):
        for b in nomes[i + 1:]:
            todos.append((a, b, cosseno(pesos[a], pesos[b])))

    # limiar adaptativo: so a cauda de cima vira aresta, senao o grafo fica denso
    ordenados = sorted(s for _, _, s in todos)
    corte = max(PISO_ARESTA, ordenados[int(len(ordenados) * PERCENTIL_ARESTA)]) if ordenados else PISO_ARESTA

    # cada documento guarda seus VIZINHOS_MIN melhores, para ninguem ficar solto
    melhores = defaultdict(list)
    for a, b, s in todos:
        melhores[a].append((s, b))
        melhores[b].append((s, a))
    garantidos = set()
    for no, lista in melhores.items():
        for s, outro in sorted(lista, reverse=True)[:VIZINHOS_MIN]:
            if s >= PISO_ARESTA:
                garantidos.add(frozenset((no, outro)))

    arestas = [
        (a, b, round(s, 4))
        for a, b, s in todos
        if s >= corte or frozenset((a, b)) in garantidos
    ]
    arestas.sort(key=lambda e: -e[2])

    sims = {frozenset((a, b)): s for a, b, s in todos}
    rotulos = comunidades(nomes, sims, corte)
    grupos = defaultdict(list)
    for pasta, r in rotulos.items():
        grupos[r].append(pasta)

    # conceito que atravessa categoria: alto peso em docs de categorias distintas
    por_conceito = defaultdict(list)
    for pasta, topo in conceitos.items():
        for termo in topo:
            por_conceito[termo].append((pasta, pesos[pasta][termo]))
    pontes = []
    for termo, itens in por_conceito.items():
        cats = {docs[p]["categoria"] for p, _ in itens}
        if len(cats) >= 2 and len(itens) >= 2:
            pontes.append(
                {
                    "conceito": termo,
                    "peso": round(sum(p for _, p in itens), 4),
                    "categorias": sorted(cats),
                    "documentos": [docs[p]["titulo"] for p, _ in
                                   sorted(itens, key=lambda kv: -kv[1])[:6]],
                }
            )
    pontes.sort(key=lambda x: (-len(x["categorias"]), -x["peso"]))

    return {
        "documentos": [
            {
                "id": p,
                "titulo": docs[p]["titulo"],
                "categoria": docs[p]["categoria"],
                "capitulos": docs[p]["capitulos"],
                "comunidade": rotulos[p],
                "conceitos": conceitos[p],
            }
            for p in nomes
        ],
        "arestas": [{"a": a, "b": b, "peso": p} for a, b, p in arestas],
        "comunidades": [
            {"id": r, "documentos": sorted(g)} for r, g in sorted(grupos.items())
        ],
        "pontes": pontes[:120],
    }


def escrever_relatorio(raiz: Path, g: dict) -> Path:
    por_id = {d["id"]: d for d in g["documentos"]}
    linhas = [
        "# Grafo de conceitos da base",
        "",
        "Construido por `motor/grafear.py` — TF-IDF sobre unigramas e bigramas, "
        "similaridade de cosseno entre documentos, comunidades por aglomeracao "
        "average-linkage. Deterministico: mesma base, mesmo grafo. Nenhum modelo leu "
        "o texto, entao isto mostra **vocabulario compartilhado**, nao concordancia "
        "de ideias.",
        "",
        "> Vies conhecido: contagem de palavra tambem agrupa por **idioma**. Cluster "
        "com livro de Rust ao lado de livro de copy costuma significar \"ambos em "
        "portugues\", nao parentesco de tema. Olhe a categoria antes de concluir "
        "qualquer coisa de uma vizinhanca.",
        "",
        f"{len(g['documentos'])} documentos · {len(g['arestas'])} ligacoes · "
        f"{len(g['comunidades'])} comunidades",
        "",
        "## Comunidades",
        "",
    ]
    for c in g["comunidades"]:
        if len(c["documentos"]) < 2:
            continue
        cats = sorted({por_id[d]["categoria"] for d in c["documentos"]})
        linhas.append(f"### {' + '.join(cats)}")
        linhas.append("")
        for d in c["documentos"]:
            doc = por_id[d]
            linhas.append(
                f"- **{doc['titulo']}** (`{doc['categoria']}`, {doc['capitulos']} cap.) — "
                + ", ".join(doc["conceitos"][:8])
            )
        linhas.append("")

    soltos = [c["documentos"][0] for c in g["comunidades"] if len(c["documentos"]) == 1]
    if soltos:
        linhas.append("### Sem vizinho proximo")
        linhas.append("")
        for d in soltos:
            doc = por_id[d]
            linhas.append(f"- **{doc['titulo']}** (`{doc['categoria']}`)")
        linhas.append("")

    linhas += ["## Ligacoes mais fortes", "",
               "| Documento | Documento | Peso |", "|---|---|---|"]
    for a in g["arestas"][:25]:
        linhas.append(
            f"| {por_id[a['a']]['titulo'][:48]} | {por_id[a['b']]['titulo'][:48]} "
            f"| {a['peso']} |"
        )
    linhas += ["", "## Conceitos que atravessam categorias", "",
               "Termo forte em documentos de areas diferentes — e onde a base cruza.",
               "", "| Conceito | Categorias | Documentos |", "|---|---|---|"]
    for p in g["pontes"][:40]:
        linhas.append(
            f"| {p['conceito']} | {', '.join(p['categorias'])} "
            f"| {'; '.join(t[:40] for t in p['documentos'][:3])} |"
        )
    caminho = raiz / "GRAFO.md"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def main() -> int:
    ap = argparse.ArgumentParser(description="Grafo de conceitos da base")
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--conceitos", type=int, default=25)
    ap.add_argument("--ponte", help="mostra quem fala desse conceito e sai")
    args = ap.parse_args()

    destino = args.raiz / "grafo.json"
    if args.ponte:
        g = json.loads(destino.read_text(encoding="utf-8"))
        alvo = args.ponte.lower()
        achou = [p for p in g["pontes"] if alvo in p["conceito"]]
        if not achou:
            print(f'"{args.ponte}" nao e conceito-ponte no grafo')
            return 1
        for p in achou[:10]:
            print(f"{p['conceito']}  [{', '.join(p['categorias'])}]")
            for t in p["documentos"]:
                print(f"    {t}")
        return 0

    g = construir(args.raiz, args.conceitos)
    destino.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    relatorio = escrever_relatorio(args.raiz, g)
    print(
        f"{len(g['documentos'])} documentos, {len(g['arestas'])} ligacoes, "
        f"{len([c for c in g['comunidades'] if len(c['documentos']) > 1])} comunidades"
    )
    print(f"grafo:     {destino}")
    print(f"relatorio: {relatorio}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
