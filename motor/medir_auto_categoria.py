"""Mede se prever a categoria sozinho realmente melhora a busca.

Tres modos, mesmas 53 perguntas, mesmo indice:

- **cru**: semantico + reranker, sem nocao de categoria;
- **filtro**: so as 3 categorias previstas entram (aposta no palpite);
- **reforco**: nada e excluido, as previstas so ganham bonus no ranking.

O `--categoria` manual chega a 43/53, mas usa a categoria do alvo — e teto, nao
resultado. Aqui ninguem conta a resposta ao motor.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import prever_categoria as PC
import semantico as S
from gabarito import GABARITO

from raiz import RAIZ_PADRAO  # noqa: E402


def _acertou(caminho: str, marcas) -> bool:
    pasta = Path(caminho).parent.name
    return any(m in pasta for m in marcas)


_ESCOLHA: dict = {}


def carregar_escolha(raiz: Path, modo: str) -> None:
    """Preenche _ESCOLHA com a categoria por pergunta, conforme o modo."""
    import json
    from pathlib import Path as _P
    global _ESCOLHA
    _ESCOLHA = {}
    if modo == "oracle":
        verdadeira = PC._categoria_verdadeira(raiz)
        for pergunta, marcas in GABARITO:
            cats = {c for pasta, c in verdadeira.items()
                    if any(m in pasta for m in marcas)}
            if cats:
                _ESCOLHA[pergunta] = sorted(cats)
    elif modo == "agente":
        arq = _P(__file__).parent / "categorias_agente.json"
        if not arq.exists():
            raise SystemExit(f"falta {arq}")
        bruto = json.loads(arq.read_text(encoding="utf-8"))
        for pergunta, _m in GABARITO:
            if bruto.get(pergunta):
                _ESCOLHA[pergunta] = bruto[pergunta]


def avaliar(raiz: Path, modo: str, topo: int = 50, k: int = 3,
            peso: float = 0.08) -> None:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    meta, vetores = S.carregar(raiz)
    reranker = TextCrossEncoder(S.RERANKER)
    modelo = S._modelo()
    vetores_f = vetores.astype(np.float32)

    hit1 = hit3 = 0
    rr = []
    inicio = time.time()
    for pergunta, marcas in GABARITO:
        q = S._normalizar(np.array(list(modelo.embed([pergunta])),
                                   dtype=np.float32))[0]
        pontos = vetores_f @ q

        if modo == "reforco":
            pontos = pontos + PC.bonus_por_passagem(
                raiz, pergunta, meta["passagens"], k=k, peso=peso)
        elif modo == "filtro":
            previstas = {c for c, _s in PC.prever(raiz, pergunta, k=k)}
            fora = np.array([p.get("categoria") not in previstas
                             for p in meta["passagens"]])
            pontos = np.where(fora, -1e9, pontos)
        elif modo in ("oracle", "agente"):
            # oracle: categoria do alvo (teto). agente: categoria escrita a mao
            # em categorias_agente.json, para medir o caminho que roda de fato.
            previstas = _ESCOLHA.get(pergunta)
            if previstas:
                fora = np.array([p.get("categoria") not in set(previstas)
                                 for p in meta["passagens"]])
                pontos = np.where(fora, -1e9, pontos)
        elif modo in ("voto-filtro", "voto-reforco"):
            # O voto sai da propria primeira passada: nada e reembutido.
            previstas = PC.prever_por_voto(meta["passagens"], pontos, k=k)
            if modo == "voto-filtro":
                fora = np.array([p.get("categoria") not in set(previstas)
                                 for p in meta["passagens"]])
                pontos = np.where(fora, -1e9, pontos)
            else:
                forca = {c: (len(previstas) - i) / len(previstas)
                         for i, c in enumerate(previstas)}
                pontos = pontos + np.array(
                    [peso * forca.get(p.get("categoria", ""), 0.0)
                     for p in meta["passagens"]], dtype=np.float32)

        ordem = np.argsort(-pontos)[:topo]
        trechos = [S.texto_da_passagem(raiz, meta["passagens"][i]) for i in ordem]
        pares = [(i, t) for i, t in zip(ordem, trechos) if t]
        if not pares:
            rr.append(0.0)
            continue
        notas = []
        textos = [t for _i, t in pares]
        for j in range(0, len(textos), 16):        # lote pequeno: o modelo e grande
            notas.extend(reranker.rerank(pergunta, textos[j:j + 16]))

        melhor = {}
        for (i, _t), nota in zip(pares, notas):
            caminho = meta["passagens"][i]["caminho"]
            if caminho not in melhor or nota > melhor[caminho]:
                melhor[caminho] = nota
        ranking = sorted(melhor, key=lambda c: -melhor[c])

        pos = next((n for n, c in enumerate(ranking) if _acertou(c, marcas)), None)
        if pos is None:
            rr.append(0.0)
        else:
            rr.append(1 / (pos + 1))
            hit1 += pos == 0
            hit3 += pos < 3

    n = len(GABARITO)
    print(f"{modo:9} hit@1 {hit1}/{n}  hit@3 {hit3}/{n}  MRR {sum(rr) / n:.3f}"
          f"  ({(time.time() - inicio) / n:.1f}s por pergunta)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--modos", default="cru,voto-filtro,voto-reforco")
    ap.add_argument("--peso", type=float, default=0.08)
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()
    for modo in args.modos.split(","):
        carregar_escolha(args.raiz, modo.strip())
        avaliar(args.raiz, modo.strip(), k=args.k, peso=args.peso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
