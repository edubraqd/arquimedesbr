"""Compara modelos de busca num gabarito, antes de gastar horas reindexando.

A licao que gerou este arquivo: o `paraphrase-multilingual-MiniLM` parecia bom
num teste com 4 documentos e falhou no indice inteiro. Medir com poucos
candidatos nao diz nada — o que decide e o ranking contra um pool realista.

    python avaliar_modelo.py --velocidade          # so mede tokens/s do e5
    python avaliar_modelo.py --docs 15             # roda o gabarito completo
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import buscar as bm
import semantico as S

from raiz import RAIZ_PADRAO as RAIZ  # noqa: E402

MINILM = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
E5 = "intfloat/multilingual-e5-large"

from gabarito import GABARITO, TRADUCAO  # noqa: E402


def capitulos(raiz: Path):
    saida = []
    for p in sorted((raiz / "markdown").rglob("*.md")):
        if p.name == "INDEX.md":
            continue
        bruto = p.read_text(encoding="utf-8", errors="replace")
        if bm._frontmatter(bruto).get("util") == "nao":
            continue
        saida.append((p, S._corpo(bruto)))
    return saida


def amostra(raiz: Path, n_docs: int, semente: int = 7):
    """Documentos do gabarito + distratores sorteados, para um pool realista."""
    todos = capitulos(raiz)
    por_doc = {}
    for p, corpo in todos:
        por_doc.setdefault(p.parent.name, []).append((p, corpo))

    alvos = {
        d for d in por_doc
        for _q, marcas in GABARITO for m in marcas if m in d
    }
    resto = sorted(set(por_doc) - alvos)
    random.Random(semente).shuffle(resto)
    escolhidos = sorted(alvos) + resto[: max(0, n_docs - len(alvos))]
    return [(p, c) for d in escolhidos for p, c in por_doc[d]], sorted(alvos)


def passagens(itens, palavras: int, avanco: int):
    original = (S.PASSAGEM_PALAVRAS, S.AVANCO)
    S.PASSAGEM_PALAVRAS, S.AVANCO = palavras, avanco
    textos, donos = [], []
    for p, corpo in itens:
        for _ini, _n, texto in S._passagens(corpo):
            textos.append(texto)
            donos.append(p.parent.name)
    S.PASSAGEM_PALAVRAS, S.AVANCO = original
    return textos, donos


def embutir(nome_modelo, textos, prefixo_doc="", prefixo_consulta="", lote=64):
    import os

    from fastembed import TextEmbedding

    modelo = TextEmbedding(nome_modelo, threads=os.cpu_count() or 4)
    inicio = time.time()
    vetores = list(
        modelo.embed([prefixo_doc + t for t in textos], batch_size=lote)
    )
    dt = time.time() - inicio
    V = np.array(vetores, dtype=np.float32)
    V /= np.clip(np.linalg.norm(V, axis=1, keepdims=True), 1e-9, None)

    def consultar(pergunta):
        q = np.array(
            list(modelo.embed([prefixo_consulta + pergunta])), dtype=np.float32
        )[0]
        return V @ (q / max(np.linalg.norm(q), 1e-9))

    return consultar, dt


RERANKER = "jinaai/jina-reranker-v2-base-multilingual"


def _rerank_em_lotes(modelo, pergunta, trechos, lote=16):
    """O cross-encoder alocava 1,5 GB tentando pontuar 100 pares de uma vez.

    Medido: com top-100 o onnxruntime aborta com
    "Failed to allocate memory for requested buffer of size 1574879232".
    Em lotes de 16 o pico cabe e o resultado e identico.
    """
    notas = []
    for i in range(0, len(trechos), lote):
        notas.extend(modelo.rerank(pergunta, trechos[i:i + lote]))
    return notas


def com_reranker(consultar, textos, topo: int = 50, nome=RERANKER):
    """Reordena as `topo` melhores passagens com um cross-encoder.

    O retrieval compara vetores calculados sem saber da pergunta; o cross-encoder
    le pergunta e passagem juntas. Custa uma inferencia por par, entao so vale
    sobre um punhado de candidatos — nunca sobre o indice inteiro.

    Os `ms-marco` da lista do fastembed sao so em ingles: com pergunta em
    portugues contra livro em ingles, o unico que serve e um multilingue.
    """
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    modelo = TextCrossEncoder(nome)

    def pontuar(pergunta):
        base = np.asarray(consultar(pergunta))
        ordem = np.argsort(-base)[:topo]
        notas = _rerank_em_lotes(modelo, pergunta, [textos[i] for i in ordem])
        # nota do cross-encoder onde ele opinou; o resto fica atras de todos
        saida = np.full(len(base), -1e9, dtype=np.float32)
        for posicao, indice in enumerate(ordem):
            saida[indice] = notas[posicao]
        return saida

    return pontuar


def reranker_sobre_uniao(fontes, textos, topo=50, nome=RERANKER):
    """Reranqueia a UNIAO dos candidatos de varias fontes de retrieval.

    O semantico e o BM25 empatam em MRR mas erram perguntas diferentes: juntar
    os candidatos antes do cross-encoder aumenta a chance de o certo estar na
    lista. E diferente de fundir os rankings — aqui quem decide a ordem final e
    so o reranker, entao o metodo fraco nao arrasta o forte para baixo.
    """
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    modelo = TextCrossEncoder(nome)

    def pontuar(pergunta):
        candidatos = []
        for consultar in fontes:
            base = np.asarray(consultar(pergunta))
            candidatos.extend(np.argsort(-base)[:topo].tolist())
        ordem = list(dict.fromkeys(candidatos))          # sem repetir, ordem estavel
        notas = _rerank_em_lotes(modelo, pergunta, [textos[i] for i in ordem])
        saida = np.full(len(textos), -1e9, dtype=np.float32)
        for posicao, indice in enumerate(ordem):
            saida[indice] = notas[posicao]
        return saida

    return pontuar


def pontuador_bm25_passagens(textos, donos, traduzir=True):
    """BM25 sobre as PASSAGENS, para poder unir candidatos com o semantico."""
    from collections import Counter

    docs = []
    for texto in textos:
        tokens = bm.tokenizar(texto)
        tf = Counter(tokens)
        docs.append({"caminho": len(docs), "n": len(tokens), "tf": dict(tf)})
    df = Counter()
    for d in docs:
        df.update(d["tf"].keys())
    indice = {"docs": docs, "df": dict(df), "total": len(docs),
              "media": sum(d["n"] for d in docs) / max(len(docs), 1)}

    def pontuar(pergunta):
        consultas = [pergunta] + ([TRADUCAO[pergunta]] if traduzir else [])
        melhor = np.zeros(len(textos), dtype=np.float32)
        for c in consultas:
            for pos, (_p, _n, d) in enumerate(bm.bm25(indice, c)[:400]):
                i = d["caminho"]
                melhor[i] = max(melhor[i], 1 / (60 + pos + 1))
        return melhor

    return pontuar


def avaliar(pontuar, donos, rotulo):
    """recall@1, recall@3 e MRR sobre o gabarito, agrupando por documento."""
    acertos1 = acertos3 = 0
    rr = []
    for pergunta, marcas in GABARITO:
        pontos = pontuar(pergunta)
        melhor = {}
        for dono, valor in zip(donos, pontos):
            if dono not in melhor or valor > melhor[dono]:
                melhor[dono] = float(valor)
        ordem = [d for d, _v in sorted(melhor.items(), key=lambda kv: -kv[1])]
        posicao = next(
            (i for i, d in enumerate(ordem) if any(m in d for m in marcas)), None
        )
        if posicao is not None:
            rr.append(1 / (posicao + 1))
            acertos1 += posicao == 0
            acertos3 += posicao < 3
        else:
            rr.append(0.0)
    n = len(GABARITO)
    print(f"{rotulo:34} recall@1 {acertos1}/{n}  recall@3 {acertos3}/{n}  "
          f"MRR {sum(rr) / n:.3f}")
    return sum(rr) / n


def pontuador_bm25(itens, bilingue: bool):
    """BM25 sobre o mesmo pool, para o incumbente competir em pe de igualdade."""
    docs = []
    for p, corpo in itens:
        tokens = bm.tokenizar(corpo)
        docs.append({"caminho": str(p), "dono": p.parent.name,
                     "n": len(tokens), "tf": {}})
        for t in tokens:
            docs[-1]["tf"][t] = docs[-1]["tf"].get(t, 0) + 1
    from collections import Counter
    df = Counter()
    for d in docs:
        df.update(d["tf"].keys())
    indice = {"docs": docs, "df": dict(df), "total": len(docs),
              "media": sum(d["n"] for d in docs) / max(len(docs), 1)}

    EN = TRADUCAO

    def pontuar(pergunta):
        consultas = [pergunta] + ([EN[pergunta]] if bilingue else [])
        melhor = {}
        for c in consultas:
            for pos, (_p, _n, d) in enumerate(bm.bm25(indice, c)[:400]):
                melhor[d["caminho"]] = max(
                    melhor.get(d["caminho"], 0.0), 1 / (60 + pos + 1)
                )
        return [melhor.get(str(p), 0.0) for p, _c in itens]

    return pontuar, [p.parent.name for p, _c in itens]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=0)
    ap.add_argument("--topo", type=int, default=50)
    ap.add_argument("--e5", action="store_true", help="inclui o e5 (horas)")
    args = ap.parse_args()

    itens, alvos = amostra(RAIZ, args.docs)
    print(f"pool: {len(itens)} capitulos, {len(alvos)} alvos, {len(GABARITO)} perguntas")

    pontuar_cap, donos_cap = pontuador_bm25(itens, True)
    avaliar(pontuar_cap, donos_cap, "BM25 bilingue (capitulo)")

    textos, donos = passagens(itens, 60, 50)
    print()
    print(f"MiniLM: {len(textos)} passagens de 60 palavras")
    consultar, dt = embutir(MINILM, textos)
    print(f"  embutido em {dt / 60:.1f} min")
    avaliar(consultar, donos, "MiniLM sozinho")

    bm_pass = pontuador_bm25_passagens(textos, donos)
    avaliar(bm_pass, donos, "BM25 bilingue (passagem)")

    for topo in (50, 100):
        inicio_t = time.time()
        avaliar(com_reranker(consultar, textos, topo), donos,
                f"MiniLM + reranker top-{topo}")
        print(f"  {(time.time() - inicio_t) / len(GABARITO):.1f}s por consulta")

    inicio_t = time.time()
    avaliar(reranker_sobre_uniao([consultar, bm_pass], textos, args.topo), donos,
            f"uniao MiniLM+BM25 -> reranker top-{args.topo} de cada")
    print(f"  {(time.time() - inicio_t) / len(GABARITO):.1f}s por consulta")

    if args.e5:
        textos_e5, donos_e5 = passagens(itens, 200, 170)
        print()
        print(f"e5-large: {len(textos_e5)} passagens de 200 palavras")
        consultar_e5, dt = embutir(E5, textos_e5, "passage: ", "query: ")
        print(f"  embutido em {dt / 60:.1f} min")
        avaliar(consultar_e5, donos_e5, "e5-large sozinho")
        avaliar(com_reranker(consultar_e5, textos_e5, args.topo), donos_e5,
                "e5-large + reranker")
    return 0


if __name__ == "__main__":
    sys.exit(main())
