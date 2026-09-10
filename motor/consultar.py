"""Consulta barata em tokens, com rodadas de realimentacao.

O `semantico.py --passagens` devolve ~420 palavras por resultado. Bom para ler,
caro para decidir: a sessao gasta ~1.700 tokens so para descobrir que o segundo
resultado era o certo. Aqui a conversa e invertida.

    1. `consultar.py "pergunta"`      -> cartoes de ~25 palavras. ~200 tokens.
    2. a sessao julga qual serve.
    3. `--abrir 2`                    -> a janela inteira, so do escolhido.
       ou
       `--sim 2 --nao 1 --sessao X`   -> o motor gira de novo, pontuando.

Quem faz o trabalho e Python: vetor, aritmetica e cross-encoder. O modelo de
linguagem so julga, e julgar cabe em cartao.

## A rodada seguinte (Rocchio)

Marcado o que serve e o que nao serve, a consulta se move no espaco vetorial em
direcao ao que serve e para longe do que nao serve:

    q' = alfa*q + beta*media(relevantes) - gama*media(nao relevantes)

Valores de *Introduction to Information Retrieval*, cap. "Relevance feedback and
query expansion" (p. 214-231), que esta nesta base: **alfa 1, beta 0,75,
gama 0,15**. O livro e explicito sobre a assimetria -- "positive feedback turns
out to be much more valuable than negative feedback, and so most IR systems set
gama < beta" -- e sobre a pre-condicao: a consulta inicial precisa ja estar perto
do alvo.

Nesta base essa pre-condicao esta **medida**: em 53 perguntas, o documento certo
nunca ficou fora do top-50 (`diagnosticar.py`). E por isso que realimentacao tem
chance aqui, enquanto contexto na passagem, correcao de hubness e mais
candidatos para o reranker foram medidos e rejeitados -- os tres atacavam
recuperacao, que nao e o gargalo.

Nada disso chama rede nem gasta token: Rocchio e soma de vetores.

    python consultar.py "como responder que esta caro" --categoria vendas
    python consultar.py --sessao a1b2 --abrir 2
    python consultar.py --sessao a1b2 --sim 2,4 --nao 1
    python consultar.py --sessao a1b2 --estado
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import textwrap
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import dominio as dom  # noqa: E402
import semantico as S  # noqa: E402

from raiz import RAIZ_PADRAO  # noqa: E402
ARQ_SESSOES = ".sessoes-busca.json"

# Introduction to Information Retrieval, cap. 9 (p. 214-231)
ALFA, BETA, GAMA = 1.0, 0.75, 0.15

PALAVRAS_CARTAO = 25
MAX_SESSOES = 40


# ------------------------------------------------------------------- sessao


def _sessoes(raiz: Path) -> dict:
    p = raiz / ARQ_SESSOES
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _gravar_sessoes(raiz: Path, dados: dict) -> None:
    # so as MAX_SESSOES mais recentes: o arquivo e cache, nao historico
    recentes = sorted(dados.items(), key=lambda kv: -kv[1].get("quando", 0))
    S.escrever_atomico(
        raiz / ARQ_SESSOES,
        lambda p: p.write_text(json.dumps(dict(recentes[:MAX_SESSOES]),
                                          ensure_ascii=False), encoding="utf-8"))


def _id_de_sessao(consulta: str) -> str:
    bruto = f"{consulta}\x00{time.time()}"
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:6]


# ----------------------------------------------------------------- ranking


def _pasta(caminho: str) -> str:
    partes = caminho.replace("\\", "/").split("/")
    return "/".join(partes[1:3]) if len(partes) >= 3 else caminho


def _indices_permitidos(passagens, raiz, categoria, dominio):
    if categoria:
        permitidas = {categoria}
    elif dominio:
        permitidas = dom.categorias(raiz, dominio)
    else:
        return None
    if not permitidas:
        return None
    return np.asarray([i for i, p in enumerate(passagens)
                       if p.get("categoria") in permitidas])


def _melhor_por_documento(pontos, passagens, indices, quantos):
    """Um resultado por documento: o melhor trecho dele."""
    ordem = np.argsort(-pontos)
    melhor: dict = {}
    for k in ordem:
        i = int(indices[k]) if indices is not None else int(k)
        d = _pasta(passagens[i]["caminho"])
        if d not in melhor:
            melhor[d] = (float(pontos[k]), i)
        if len(melhor) >= quantos:
            break
    return sorted(melhor.items(), key=lambda kv: -kv[1][0])[:quantos]


def _reranquear(raiz, passagens, candidatos, consulta_txt):
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    cross = TextCrossEncoder(S.RERANKER)
    textos = [(d, i, S.texto_da_passagem(raiz, passagens[i]))
              for d, (_s, i) in candidatos]
    textos = [(d, i, t) for d, i, t in textos if t]
    if not textos:
        return candidatos
    notas = list(cross.rerank(consulta_txt, [t for _d, _i, t in textos]))
    juntos = [(d, (float(n), i)) for (d, i, _t), n in zip(textos, notas)]
    return sorted(juntos, key=lambda kv: -kv[1][0])


# ------------------------------------------------------------------ saida


def _cartao(raiz, passagens, n, doc, pontos, i) -> str:
    p = passagens[i]
    texto = S.texto_da_passagem(raiz, p) or ""
    palavras = texto.split()[:PALAVRAS_CARTAO]
    trecho = " ".join(palavras) + ("..." if len(texto.split()) > PALAVRAS_CARTAO else "")
    cab = (f"{n}. {pontos:+.3f}  {p.get('titulo', doc)[:58]} "
           f"— {p.get('capitulo', '')[:44]} · p.{p.get('paginas', '?')}")
    return cab + "\n   " + trecho


def _imprimir(raiz, passagens, resultados, sessao_id, rodada):
    for n, (doc, (pontos, i)) in enumerate(resultados, 1):
        print(_cartao(raiz, passagens, n, doc, pontos, i))
    print(f"\nsessao {sessao_id} · rodada {rodada}")
    print(f"  abrir:      python consultar.py --sessao {sessao_id} --abrir <n>")
    print(f"  nao serviu: python consultar.py --sessao {sessao_id} "
          f"--sim <n,n> --nao <n,n>")


# ------------------------------------------------------------------ acoes


def _vetor_da_consulta(texto: str) -> np.ndarray:
    modelo = S._modelo()
    return S._normalizar(np.array(list(modelo.embed([texto])),
                                  dtype=np.float32))[0]


def rocchio(q: np.ndarray, vetores: np.ndarray,
            relevantes: list, nao: list) -> np.ndarray:
    novo = ALFA * q
    if relevantes:
        novo = novo + BETA * vetores[relevantes].mean(axis=0)
    if nao:
        novo = novo - GAMA * vetores[nao].mean(axis=0)
    norma = np.linalg.norm(novo)
    return novo / norma if norma else q


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("consulta", nargs="*")
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--n", type=int, default=6, help="quantos cartoes")
    ap.add_argument("--categoria")
    ap.add_argument("--dominio")
    ap.add_argument("--sem-rerank", action="store_true",
                    help="pula o cross-encoder (~6 s mais rapido, pior)")
    ap.add_argument("--sessao", help="continua uma consulta ja aberta")
    ap.add_argument("--abrir", type=int, help="janela inteira do resultado n")
    ap.add_argument("--janela", type=int, default=420)
    ap.add_argument("--sim", default="", help="resultados que servem: 2,4")
    ap.add_argument("--nao", default="", help="resultados que nao servem: 1")
    ap.add_argument("--estado", action="store_true", help="mostra a sessao")
    args = ap.parse_args()

    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    raiz = args.raiz
    meta, vetores = S.carregar(raiz)
    if meta is None:
        print("indice semantico nao existe - rode: python semantico.py indexar")
        return 1
    passagens = meta["passagens"]
    sessoes = _sessoes(raiz)

    def numeros(bruto):
        return [int(x) for x in bruto.replace(" ", "").split(",") if x]

    # ------------------------------------------------- continuar uma sessao
    if args.sessao:
        s = sessoes.get(args.sessao)
        if not s:
            print(f"sessao {args.sessao} nao existe (ou ja saiu do cache)")
            return 1
        mostrados = s["mostrados"]          # [indice de passagem, ...]

        if args.estado:
            print(f"sessao {args.sessao} · rodada {s['rodada']}")
            print(f"  consulta: {s['consulta']}")
            print(f"  serviram:     {s['relevantes']}")
            print(f"  nao serviram: {s['nao']}")
            return 0

        if args.abrir:
            if not 1 <= args.abrir <= len(mostrados):
                print(f"escolha entre 1 e {len(mostrados)}")
                return 1
            i = mostrados[args.abrir - 1]
            p = passagens[i]
            janela = S.janela_da_passagem(raiz, p, args.janela) or ""
            print(f"{p.get('titulo','')} — {p.get('capitulo','')} "
                  f"· p.{p.get('paginas','?')}")
            print(f"{p['caminho']}\n")
            print(textwrap.fill(janela, 96))
            return 0

        # nova rodada: move a consulta e reranqueia
        sim = [mostrados[n - 1] for n in numeros(args.sim)
               if 1 <= n <= len(mostrados)]
        nao = [mostrados[n - 1] for n in numeros(args.nao)
               if 1 <= n <= len(mostrados)]
        if not sim and not nao:
            print("nada a fazer: passe --sim e/ou --nao, ou --abrir")
            return 1
        s["relevantes"] = sorted(set(s["relevantes"]) | set(sim))
        s["nao"] = sorted(set(s["nao"]) | set(nao))
        q = rocchio(np.asarray(s["q"], dtype=np.float32),
                    vetores.astype(np.float32), s["relevantes"], s["nao"])
        s["q"] = q.tolist()
        s["rodada"] += 1
        consulta_txt = s["consulta"]
        indices = np.asarray(s["indices"]) if s["indices"] else None
        vistos = set(s["relevantes"]) | set(s["nao"])
    else:
        consulta_txt = " ".join(args.consulta).strip()
        if not consulta_txt:
            ap.print_help()
            return 1
        q = _vetor_da_consulta(consulta_txt)
        indices = _indices_permitidos(passagens, raiz, args.categoria,
                                      args.dominio)
        s = {"consulta": consulta_txt, "q": q.tolist(), "rodada": 1,
             "relevantes": [], "nao": [], "mostrados": [],
             "indices": indices.tolist() if indices is not None else None}
        args.sessao = _id_de_sessao(consulta_txt)
        vistos = set()

    alvo = vetores.astype(np.float32)
    if indices is not None:
        pontos = alvo[indices] @ q
    else:
        pontos = alvo @ q

    # pede folga para descartar o que a sessao ja julgou sem encurtar a lista
    candidatos = _melhor_por_documento(pontos, passagens, indices,
                                       args.n + len(vistos) + 4)
    candidatos = [c for c in candidatos if c[1][1] not in vistos][:args.n]

    if not args.sem_rerank and candidatos:
        candidatos = _reranquear(raiz, passagens, candidatos, consulta_txt)

    s["mostrados"] = [i for _d, (_p, i) in candidatos]
    s["quando"] = time.time()
    sessoes[args.sessao] = s
    _gravar_sessoes(raiz, sessoes)

    _imprimir(raiz, passagens, candidatos, args.sessao, s["rodada"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
