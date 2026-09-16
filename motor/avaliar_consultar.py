"""Mede o pipeline do `consultar.py` contra o do `semantico.py`, lado a lado.

Motivo de existir: a tabela de `dominio.py` (42/53 com `--categoria` e reranker)
foi medida no caminho do `semantico.reranquear`, que reranqueia as **50 melhores
passagens**. O `consultar.py` faz outra coisa: pega a **melhor passagem de cada
documento**, corta em 10 documentos e reranqueia esses 10. Sao pipelines
diferentes, e desde 10/09/2026 o `consultar.py` e a porta de entrada da base --
entao o numero dele precisa ser dele, nao emprestado.

Os dois modos recebem o **mesmo** recorte de categoria (o de
`categorias_agente.json`, escolhido por agente lendo so a pergunta), para que a
diferenca medida seja a do pipeline, nao a do recorte.

Tres pipelines:

| modo       | o que reranqueia                                  |
|------------|---------------------------------------------------|
| `cli`      | **o que o consultar.py faz**: top 6 documentos, reranqueia esses 6 |
| `cli-r2`   | `cli` mais uma rodada de Rocchio quando o alvo nao caiu nos 6 |
| `cartao`   | melhor passagem de cada documento, top 10         |
| `cartao50` | as 50 melhores passagens, **depois** colapsa em documento |
| `passagem` | as 50 melhores passagens (o caminho do semantico) |

`cartao` e `cartao50` sao de uma investigacao anterior do mesmo dia: a primeira
medicao mostrou `cartao` perdendo 25 acertos de primeira contra `passagem`, e
`cartao50` testou se a culpa era do pool de 10 (era: com pool de 50 ele empata
com `passagem` em tudo). Ficaram no arquivo porque isolam a variavel. **O modo
que mede o produto e `cli`**, que corta em 6 antes de reranquear como o
`consultar.py` faz de fato -- e mede igual ao `cartao` (62 e 117 contra 62 e 116),
ou seja a diferenca entre pool de 6 e de 10 nao aparece.

**`hit@12` e a metrica do protocolo**, nao `hit@1` nem `hit@6`: a sessao le seis
cartoes, julga, e quando nenhum serve pede a rodada 2 e le outros seis. Alvo em
terceiro lugar da segunda tela nao custa nada a quem segue o protocolo.

    python avaliar_consultar.py                  # os tres modos
    python avaliar_consultar.py --modos cartao50
    python avaliar_consultar.py --todas          # as 140, as sem categoria sem recorte
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import consultar as C  # noqa: E402
import medir_auto_categoria as M  # noqa: E402
import semantico as S  # noqa: E402
from gabarito import GABARITO, TRADUCAO  # noqa: E402

from raiz import RAIZ_PADRAO  # noqa: E402
CANDIDATOS_CARTAO = 10   # C._melhor_por_documento(..., n=6 + folga 4)
TOPO_PASSAGEM = 50       # S.reranquear(topo=50)
CARTOES = 6              # o --n padrao do consultar.py


def _documentos_em_ordem(caminhos: list[str]) -> list[str]:
    """Pastas de documento na ordem em que aparecem, sem repetir."""
    vistos, ordem = set(), []
    for c in caminhos:
        pasta = Path(c).parent.name
        if pasta not in vistos:
            vistos.add(pasta)
            ordem.append(pasta)
    return ordem


def _posicao_do_alvo(docs: list[str], marcas) -> int | None:
    for n, pasta in enumerate(docs, 1):
        if any(m in pasta for m in marcas):
            return n
    return None


def _primeira_por_documento(indices: list[int], passagens) -> list[int]:
    """Uma passagem por documento, mantendo a ordem recebida."""
    vistos, saida = set(), []
    for i in indices:
        pasta = Path(passagens[i]["caminho"]).parent.name
        if pasta not in vistos:
            vistos.add(pasta)
            saida.append(i)
    return saida


def _filtrar(pontos: np.ndarray, passagens, permitidas) -> np.ndarray:
    if not permitidas:
        return pontos
    fora = np.array([p.get("categoria") not in set(permitidas)
                     for p in passagens])
    return np.where(fora, -1e9, pontos)


def _rerank(cross, raiz, passagens, indices, pergunta) -> list[int]:
    pares = [(i, S.texto_da_passagem(raiz, passagens[i])) for i in indices]
    pares = [(i, t) for i, t in pares if t]
    if not pares:
        return []
    notas = list(cross.rerank(pergunta, [t for _i, t in pares]))
    return [i for i, _n in sorted(zip([i for i, _t in pares], notas),
                                  key=lambda kv: -kv[1])]


def _posicoes_cli(raiz, modo, passagens, alvo, cross, indice_bm, pergunta,
                  marcas, permitidas):
    """O caminho do consultar.py de verdade: `C.ranquear` + reranker.

    Desde 16/09 o avaliador chama a mesma funcao que a CLI, em vez de
    reimplementar o pipeline -- foi assim que o `cli-r2` mediu 133/140 com
    dedup por documento enquanto a CLI deduplicava por passagem.
    """
    en = TRADUCAO.get(pergunta)
    consultas = [pergunta] + ([en] if en and modo != "cli-pt" else [])
    q = C._vetor_das_consultas(consultas)
    bm = None if modo == "cli-denso" else indice_bm
    cands = C.ranquear(passagens, alvo, q, consultas, permitidas, set(), CARTOES, bm)
    ordenados = _rerank(cross, raiz, passagens, [i for _d, (_s, i) in cands], pergunta)
    if modo != "cli-r2":
        return ordenados
    docs1 = _documentos_em_ordem([passagens[i]["caminho"] for i in ordenados])
    if _posicao_do_alvo(docs1, marcas) is not None:
        return ordenados
    # nenhum dos seis servia: --nao 1..6, a consulta foge deles, e nenhum
    # documento ja mostrado volta (dedup por documento, como na CLI)
    q2 = C.rocchio(q, alvo, [], list(ordenados))
    excluir = {C._pasta(passagens[i]["caminho"]) for i in ordenados}
    cands2 = C.ranquear(passagens, alvo, q2, consultas, permitidas, excluir,
                        CARTOES, bm)
    return ordenados + _rerank(cross, raiz, passagens,
                               [i for _d, (_s, i) in cands2], pergunta)


def avaliar(raiz: Path, modo: str, com_recorte: bool, perguntas) -> dict:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    meta, vetores = S.carregar(raiz)
    passagens = meta["passagens"]
    cross = TextCrossEncoder(S.RERANKER)
    modelo = S._modelo()
    C._MODELO = modelo
    alvo = vetores.astype(np.float32)
    indice_bm = C._indice_bm(raiz) if modo.startswith("cli") else None

    posicoes: list = []
    inicio = time.time()
    for pergunta, marcas in perguntas:
        escolha = M._ESCOLHA.get(pergunta) if com_recorte else None
        permitidas = set(escolha) if escolha else None

        if modo.startswith("cli"):
            ordenados = _posicoes_cli(raiz, modo, passagens, alvo, cross,
                                      indice_bm, pergunta, marcas, permitidas)
        else:
            q = S._normalizar(np.array(list(modelo.embed([pergunta])),
                                       dtype=np.float32))[0]
            pontos = _filtrar(alvo @ q, passagens, escolha)
            if modo == "cartao":
                # o caminho do consultar.py ate 10/09: melhor passagem por
                # documento, top 10, e o reranker reordena esses 10
                candidatos = C._melhor_por_documento(pontos, passagens, None,
                                                     CANDIDATOS_CARTAO)
                indices = [i for _d, (_s, i) in candidatos]
            else:
                # cartao50 e passagem partem do mesmo pool; o que muda e depois
                indices = [int(i) for i in np.argsort(-pontos)[:TOPO_PASSAGEM]]
            ordenados = _rerank(cross, raiz, passagens, indices, pergunta)
            if modo == "cartao50":
                # colapsa DEPOIS do reranker: cada documento entra pela sua
                # melhor passagem **na nota do cross-encoder**, nao na do cosseno
                ordenados = _primeira_por_documento(ordenados, passagens)

        docs = _documentos_em_ordem([passagens[i]["caminho"] for i in ordenados])
        posicoes.append((pergunta, _posicao_do_alvo(docs, marcas)))

    return {"modo": modo, "posicoes": posicoes,
            "segundos": time.time() - inicio}


def resumir(posicoes) -> dict:
    """hit@1/3/6/12 e MRR de uma lista de posicoes (None = nao achou)."""
    pos = [p for _q, p in posicoes]
    n = len(pos) or 1
    return {"n": len(pos),
            "hit1": sum(1 for p in pos if p == 1),
            "hit3": sum(1 for p in pos if p and p <= 3),
            "hit6": sum(1 for p in pos if p and p <= 6),
            # hit@12 = duas telas de seis cartoes; para os modos sem rodada 2
            # e igual ao hit@6 (a lista tem 6)
            "hit12": sum(1 for p in pos if p and p <= 12),
            "mrr": sum(1.0 / p for p in pos if p) / n}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--modos", default="cli,cli-r2,passagem",
                    help="cli = consultar.py de hoje (BM25 + PT+EN); cli-pt = "
                         "sem --tambem; cli-denso = sem BM25; cli-r2 = cli mais "
                         "a rodada 2; cartao, cartao50, passagem = os outros")
    ap.add_argument("--estrato", action="store_true",
                    help="tambem fatia por dominio do alvo (comercial/tecnico/pessoal)")
    ap.add_argument("--sem-recorte", action="store_true")
    ap.add_argument("--todas", action="store_true",
                    help="as 140 perguntas; sem isto, so as que tem categoria "
                         "de agente, para a comparacao nao misturar recorte")
    args = ap.parse_args()

    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    com_recorte = not args.sem_recorte
    perguntas = list(GABARITO)
    if com_recorte:
        M.carregar_escolha(args.raiz, "agente")
        faltam = [p for p, _m in GABARITO if p not in M._ESCOLHA]
        if faltam and not args.todas:
            # misturar pergunta com e sem recorte faz a media nao medir nada
            perguntas = [(p, m) for p, m in GABARITO if p in M._ESCOLHA]
            print(f"{len(faltam)} das {len(GABARITO)} perguntas nao tem "
                  "categoria de agente e ficaram de fora (--todas inclui)")
        elif faltam:
            print(f"aviso: {len(faltam)} perguntas sem categoria de agente - "
                  "elas rodam sem recorte, e a media mistura os dois casos")

    total = len(perguntas)
    recorte = "categoria de agente" if com_recorte else "sem recorte"
    print(f"{total} perguntas - {recorte}")
    print()
    cab = ["modo".ljust(10), "hit@1".rjust(8), "hit@3".rjust(8),
           "hit@6".rjust(8), "hit@12".rjust(8), "MRR".rjust(7),
           "s/pergunta".rjust(11)]
    print(" ".join(cab))

    def linha(nome, res, n, segundos=None):
        campos = [nome.ljust(10),
                  f"{res['hit1']}/{n}".rjust(8), f"{res['hit3']}/{n}".rjust(8),
                  f"{res['hit6']}/{n}".rjust(8), f"{res['hit12']}/{n}".rjust(8),
                  f"{res['mrr']:.3f}".rjust(7)]
        if segundos is not None:
            campos.append(f"{segundos / max(n, 1):.1f}".rjust(11))
        print(" ".join(campos))

    dominio_de = {}
    if args.estrato:
        import dominio as dom
        from avaliar_dominio import alvo_no_disco
        for pergunta, marcas in perguntas:
            cats = alvo_no_disco(args.raiz, marcas)
            doms = sorted({d for c in cats if (d := dom.de_categoria(args.raiz, c))})
            dominio_de[pergunta] = doms[0] if len(doms) == 1 else "misto"

    for modo in args.modos.split(","):
        r = avaliar(args.raiz, modo.strip(), com_recorte, perguntas)
        linha(r["modo"], resumir(r["posicoes"]), total, r["segundos"])
        if args.estrato:
            for nome in ("comercial", "tecnico", "pessoal", "misto"):
                fatia = [(q, p) for q, p in r["posicoes"] if dominio_de.get(q) == nome]
                if fatia:
                    linha(f"  {nome}", resumir(fatia), len(fatia))
    return 0


if __name__ == "__main__":
    sys.exit(main())
