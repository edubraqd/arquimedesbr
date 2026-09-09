"""Adivinha em que prateleira procurar, para quem consulta nao precisar saber.

Medido pela outra sessao em 07/09: dizer a categoria certa leva o
`semantico + rerank` de 29/53 para 43/53 acertos de primeira — mais do que o
proprio reranker rende. So que aquele numero e **teto**: pressupoe alguem que ja
sabe a resposta. Aqui o motor tenta descobrir sozinho.

Como: o centroide de cada categoria sai dos vetores que ja estao no indice —
media dos documentos, e nao das passagens, para que um livro de 1 milhao de
palavras nao defina sozinho a categoria inteira. A pergunta e comparada com os
centroides.

**Devolve mais de uma categoria de proposito.** Filtrar por uma so e apostar
tudo num palpite: se errar, a resposta certa fica inalcancavel. Com duas ou tres,
o recorte ainda corta a maior parte do acervo e o custo do erro cai muito.

    python prever_categoria.py "como responder que esta caro"
    python prever_categoria.py --medir        # acerto contra o gabarito
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import semantico as S

from raiz import RAIZ_PADRAO  # noqa: E402
ARQ_CENTROIDES = ".centroides-categoria.npz"


def construir_centroides(raiz: Path):
    """Centroide por categoria: media dos documentos, nao das passagens."""
    meta, vetores = S.carregar(raiz)
    if meta is None:
        return None, None

    por_doc = defaultdict(list)
    categoria_do_doc = {}
    for i, p in enumerate(meta["passagens"]):
        pasta = Path(p["caminho"]).parent.name
        por_doc[pasta].append(i)
        categoria_do_doc[pasta] = p.get("categoria", "geral")

    por_categoria = defaultdict(list)
    for pasta, indices in por_doc.items():
        centro = vetores[indices].astype(np.float32).mean(axis=0)
        norma = np.linalg.norm(centro)
        if norma > 0:
            por_categoria[categoria_do_doc[pasta]].append(centro / norma)

    nomes, matriz = [], []
    for categoria, centros in sorted(por_categoria.items()):
        centro = np.mean(centros, axis=0)
        norma = np.linalg.norm(centro)
        if norma == 0:
            continue
        nomes.append(categoria)
        matriz.append(centro / norma)
    return nomes, np.array(matriz, dtype=np.float32)


def carregar_centroides(raiz: Path, refazer: bool = False):
    caminho = raiz / ARQ_CENTROIDES
    if not refazer and caminho.exists():
        dados = np.load(caminho, allow_pickle=True)
        return list(dados["nomes"]), dados["m"]
    nomes, matriz = construir_centroides(raiz)
    if nomes:
        np.savez_compressed(caminho, nomes=np.array(nomes), m=matriz)
    return nomes, matriz


def prever(raiz: Path, consulta: str, k: int = 2, refazer: bool = False):
    """Devolve [(categoria, similaridade)] das k mais provaveis."""
    nomes, matriz = carregar_centroides(raiz, refazer)
    if not nomes:
        return []
    q = S._normalizar(
        np.array(list(S._modelo().embed([consulta])), dtype=np.float32)
    )[0]
    pontos = matriz @ q
    ordem = np.argsort(-pontos)[:k]
    return [(nomes[i], float(pontos[i])) for i in ordem]


def bonus_por_passagem(raiz: Path, consulta: str, passagens: list,
                       k: int = 3, peso: float = 0.08) -> np.ndarray:
    """Bonus no ranking para as categorias provaveis — reforco, nao filtro.

    Medido em 07/09 contra o gabarito: a categoria certa e a primeira palpitada
    em so 28/53 (52%), sobe para 45/53 (84%) entre as tres primeiras. Filtrar
    pela primeira, entao, esconderia a resposta em quase metade das perguntas —
    e categoria vizinha e o erro tipico ("carta de vendas" caiu em `marketing`
    em vez de `copy-persuasao`).

    Como reforco, o palpite errado custa pouco: a passagem certa continua no
    ranking, so nao ganha o empurrao.
    """
    previstas = dict(prever(raiz, consulta, k=k))
    if not previstas:
        return np.zeros(len(passagens), dtype=np.float32)
    return np.array(
        [peso * previstas.get(p.get("categoria", ""), 0.0) for p in passagens],
        dtype=np.float32,
    )


def prever_por_voto(passagens, pontos, k: int = 3, topo: int = 200,
                    rrf: int = 10) -> list[str]:
    """Categoria pelas passagens que a busca ja trouxe, em vez do centroide.

    O centroide compara a pergunta com a **media** de uma categoria, e a media
    apaga o que distingue categoria vizinha: medido em 07/09, ele manda "carta de
    vendas" para `marketing` em vez de `copy-persuasao`, e "quando usar RAG" para
    `dados-ml` em vez de `ia-llm`. Aqui nada e promediado — as passagens mais
    parecidas votam na propria categoria, e evidencia fraca espalhada soma.

    Medido contra o gabarito de 53, categoria certa entre as previstas:

    | metodo         | top-1 | top-3 |
    |----------------|-------|-------|
    | centroide      |  52%  |  84%  |
    | voto (este)    |  62%  |  90%  |

    Peso por rank reciproco, nao por similaridade crua: a similaridade do MiniLM
    vive num intervalo estreito, entao somar valor bruto elegeria sempre a
    categoria com mais passagens no indice.

    Dar um voto por documento em vez de um por passagem foi testado e **piora**
    (62% -> 41%): varias passagens do mesmo livro casando e sinal de que o livro
    e o certo, nao vies de tamanho.

    **E mesmo assim nao serve para recortar a busca.** Medido ponta a ponta com
    reranker: 29/53 sem categoria, 29/53 filtrando pelo voto, 29/53 usando o voto
    como bonus. Zero. O motivo e estrutural, nao de ajuste: o voto sai do *mesmo
    ranking* que produz a resposta, entao a categoria so ganha a votacao quando o
    documento certo ja estava bem colocado. Filtrar por ela nao acrescenta
    informacao — e circular.

    O ganho do `--categoria` (29 -> 44 no teto) vem de informacao que **nao esta
    no indice**: saber do que a pergunta trata. Quem tem isso e quem pergunta.
    Agente escolhendo a categoria so de ler a pergunta acerta 92% e leva a busca
    a 41/53 — ver `comparar_preditores.py` e `categorias_agente.json`.

    Fica aqui como resultado negativo documentado, para ninguem tentar de novo.
    """
    import numpy as _np
    from collections import defaultdict as _dd

    ordem = _np.argsort(-pontos)[:topo]
    placar = _dd(float)
    for posicao, i in enumerate(ordem):
        placar[passagens[i].get("categoria", "geral")] += 1.0 / (rrf + posicao)
    return [c for c, _ in sorted(placar.items(), key=lambda kv: -kv[1])][:k]


# --------------------------------------------------------------- medicao


def _categoria_verdadeira(raiz: Path) -> dict:
    """pasta do documento -> categoria, lido do disco."""
    saida = {}
    for pasta in (raiz / "markdown").glob("*/*"):
        if pasta.is_dir():
            saida[pasta.name] = pasta.parent.name
    return saida


def medir(raiz: Path, ks=(1, 2, 3)) -> None:
    from gabarito import GABARITO

    verdadeira = _categoria_verdadeira(raiz)
    nomes, matriz = carregar_centroides(raiz, refazer=True)
    print(f"{len(nomes)} categorias, gabarito de {len(GABARITO)} perguntas\n")

    modelo = S._modelo()
    acertos = {k: 0 for k in ks}
    erros = []
    for pergunta, marcas in GABARITO:
        esperadas = {
            categoria for pasta, categoria in verdadeira.items()
            if any(m in pasta for m in marcas)
        }
        if not esperadas:
            continue
        q = S._normalizar(np.array(list(modelo.embed([pergunta])), dtype=np.float32))[0]
        ordem = [nomes[i] for i in np.argsort(-(matriz @ q))]
        for k in ks:
            if esperadas & set(ordem[:k]):
                acertos[k] += 1
        if not (esperadas & set(ordem[:2])):
            erros.append((pergunta, sorted(esperadas), ordem[:2]))

    n = len(GABARITO)
    for k in ks:
        print(f"categoria certa entre as {k} previstas: {acertos[k]}/{n} "
              f"({acertos[k] * 100 // n}%)")
    if erros:
        print(f"\nerrou feio ({len(erros)}):")
        for pergunta, esperadas, previstas in erros[:10]:
            print(f"  {pergunta[:52]:52} esperava {esperadas} veio {previstas}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("consulta", nargs="*")
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--medir", action="store_true")
    ap.add_argument("--refazer", action="store_true")
    args = ap.parse_args()

    if args.medir:
        medir(args.raiz)
        return 0
    if not args.consulta:
        ap.print_help()
        return 1
    for categoria, pontos in prever(args.raiz, " ".join(args.consulta),
                                    args.k, args.refazer):
        print(f"  {pontos:.3f}  {categoria}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
