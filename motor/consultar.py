"""Consulta barata em tokens, com rodadas de realimentacao.

Porta de entrada da base: **a sessao pergunta, o Python e o bibliotecario**.
Vetor, aritmetica de Rocchio e cross-encoder rodam aqui; o modelo de linguagem
so julga cartao, escolhe a prateleira e pede a rodada seguinte.

O `semantico.py --passagens` devolve ~420 palavras por resultado. Bom para ler,
caro para decidir: paga a janela dos seis antes de saber qual serve. Aqui a
conversa e invertida.

    1. `consultar.py "pergunta" --categoria vendas`  -> cartoes de ~25 palavras
    2. a sessao julga qual serve.
    3. `--abrir 2`                    -> a janela inteira, so do escolhido.
       ou
       `--sim 2 --nao 1 --sessao X`   -> o motor gira de novo, pontuando.

**Medido em 10/09/2026**, mesma pergunta, `--categoria vendas`, 6 resultados
(178 documentos, 210.526 passagens):

| saida                           |       chars | tempo |
|---------------------------------|-------------|-------|
| cartoes (rodada 1)              | 1.655-1.870 | 8-13 s |
| `--abrir 1` (janela do escolhido)|      2.645 | rapido: nao embute, nao reranqueia |
| `semantico.py --passagens`      | 9.707-10.249| idem cartoes |

Cartao + abrir um = **2,3x menos** texto que `--passagens`. Quando o cartao ja
responde, **5,6x**. (A primeira versao deste arquivo dizia "~200 tokens" e
"~1.700 tokens"; nenhum dos dois foi medido. Estes foram.)

## Recorte e obrigatorio

Consulta nova sem `--categoria`/`--dominio`/`--sem-recorte` **para** e lista as
categorias. Nao e zelo: no caminho do `semantico.py` o `--categoria` leva o
acerto de primeira de 29/53 para 42/53 (tabela em `dominio.py`). Quem escolhe
tem de ser a sessao -- agente lendo a pergunta acerta 92% da categoria, maquina
52% (`medir_auto_categoria.py`), porque o voto sai do mesmo ranking que ele
deveria corrigir. Continuar sessao (`--sessao`) nao repete a exigencia: o
recorte da rodada 1 vale para as seguintes.

**Tempo medido em 10/09:** 8-13 s por rodada (tres pares de rodadas: 10-11 s
com `--categoria vendas`, 11-12 s com `--categoria seguranca-llm`, 12-13 s com
`--sem-recorte`; uma rodada mais cedo deu 8,3 s). **O recorte economiza ~1-2 s,
nao metade do tempo** -- quase tudo aqui e custo fixo: o npz de 149 MB, o modelo
de embedding e o cross-encoder de 1,1 GB. A metade do tempo que a skill cita e
do `semantico.py`, que reranqueia 50 passagens; este reranqueia 10. O recorte
nesta porta vale por **acerto**, nao por velocidade.

## O pool curto e de graca -- e a rodada 2 paga o resto

Medido em 10/09/2026 por `avaliar_consultar.py`, nas **140 perguntas** do
gabarito, todas com categoria escolhida por agente lendo so a pergunta
(`categorias_agente.json`), contra 178 documentos:

| pipeline | hit@1 | hit@3 | hit@6 | hit@12 | MRR | s/pergunta |
|---|---|---|---|---|---|---|
| `cli` -- rodada 1 do `consultar.py` | 69/140 | 111/140 | 126/140 | 126/140 | 0,650 | 1,2 |
| `cli-r2` -- com a rodada 2 de Rocchio | 69/140 | 111/140 | 126/140 | **133/140** | 0,657 | 1,3 |
| `passagem` -- `semantico.py`, 50 passagens | 95/140 | 115/140 | 127/140 | 128/140 | 0,765 | 7,6 |

Tres leituras, em ordem de importancia:

1. **`hit@12` -- duas telas de seis -- e onde o ciclo ganha: 133 contra 128.** A
   rodada 2 recupera **7 dos 14** que a rodada 1 errou (126 -> 133), de graca:
   Rocchio e soma de vetores, nao chama rede nem gasta token. Sozinha, a rodada 1
   perdia 1 para o pipeline caro; com realimentacao, ganha 5. **E piso:** a
   medicao marca os seis como "nao serve", so o lado fraco do mecanismo
   (gama 0,15); marcar um como parcial (`--sim`, beta 0,75) nao esta medido.
2. **`hit@6` praticamente empata** (126 contra 127) com 1/5 do pool e 6x mais
   rapido. O pool curto nao muda **se** o alvo esta na lista, muda a posicao.
3. **`hit@1` perde 26** (69 contra 95). Irrelevante para quem le os seis cartoes;
   fatal para quem abre o primeiro -- e o unico erro caro deste protocolo.

**Ressalva que nao pode ser perdida: estes numeros nao sao comparaveis com os da
medicao anterior do mesmo dia** (`cli` 62/117, `cli-r2` 122, `passagem` 87/119).
Entre as duas, 12 documentos trocaram de categoria numa rodada de curadoria, e
**10 dos 11 moves foram para a categoria que o agente havia escolhido** -- o
filtro passou a conter o alvo por construcao. A regua andou, nao so a busca. O
sinal do circuito fechado: a taxa de acerto de categoria foi de 86% para 94% nas
perguntas limpas sem ninguem ler nada de novo.

**O que continua valido e a comparacao entre pipelines**, porque os tres rodam
sobre o mesmo catalogo. O que nao vale e ler o +7 de `hit@1` como melhora de
busca.

Por isso este arquivo fica com o pool curto **e** com a rodada 2: separados, cada
um perde para o `semantico.py`; juntos, ganham, a 1/5 do tempo.

Dois detalhes honestos. O `hit@12` do `passagem` quase nao passa do `hit@6` dele
(128 contra 127): a lista mais profunda nao rende -- e a realimentacao, nao a
profundidade, que acha o que faltou. E uma medicao com 53 perguntas, mais cedo no
mesmo dia, dava empate exato de `hit@6` (47/47); esta superada.

Refazer: `python avaliar_consultar.py --todas` (~15 min).

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

## Desde 16/09/2026: BM25 fundido, vetor PT+EN, dedup por documento

Medido em 140 perguntas com recorte de agente, reranqueando 6 (hit@1/3/6):
denso PT 67/107/121; denso PT+EN 72/109/129; BM25->rerank 79/112/126; RRF
denso+BM25 74/114/127; RRF com PT+EN 74/112/129. A regra "nao use --hibrido"
do SKILL.md vinha de 12 perguntas. Entao:

- `--tambem "<pergunta em ingles>"`: soma os dois vetores e roda o BM25 nos
  dois idiomas. 33 dos 58 primeiros livros eram em ingles; hoje a maioria.
- cada rodada funde os 30 melhores documentos do vetor com os 30 do BM25 por
  rank reciproco (`fundir_rrf`), e reranqueia os 6. `--sem-bm25` desliga.
- a rodada 2 nao repete **documento** ja mostrado. Antes o dedup era por
  passagem: a consulta andava, outro capitulo do mesmo livro virava a melhor
  passagem dele, e o livro julgado voltava como novidade.
- `--mais <n>`: outros capitulos do documento do cartao n, ranqueados pela
  consulta atual. Ganham numero e podem ser abertos.
- categoria esgotada completa com o dominio dela, avisando.
- `--abrir` e `--estado` nao carregam indice nem modelo: a sessao guarda o
  bastante (caminho, ini, n) de cada cartao. A sessao tambem deixou de
  guardar 120k indices de passagem; guarda a categoria.

    python consultar.py --categorias
    python consultar.py "como responder que esta caro" --categoria vendas
    python consultar.py "como responder que esta caro" --tambem "price objection" --categoria vendas
    python consultar.py --sessao a1b2 --abrir 2
    python consultar.py --sessao a1b2 --mais 2
    python consultar.py --sessao a1b2 --sim 2,4 --nao 1
    python consultar.py --sessao a1b2 --estado
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import textwrap
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import buscar as bm  # noqa: E402
import dominio as dom  # noqa: E402
import semantico as S  # noqa: E402

from raiz import RAIZ_PADRAO  # noqa: E402
ARQ_SESSOES = ".sessoes-busca.json"
PORTA_PADRAO = int(os.environ.get("CONSULTAR_PORTA", "8766"))   # servidor.py

# Introduction to Information Retrieval, cap. 9 (p. 214-231)
ALFA, BETA, GAMA = 1.0, 0.75, 0.15

PALAVRAS_CARTAO = 25
MAX_SESSOES = 40

EXIGE_RECORTE = """consultar.py exige recorte antes de ranquear. Escolha um:

  --categoria <cat>   o que rende: 42/53 acertos de primeira contra 29/53 sem
                      recorte (medido no caminho do semantico.py)
  --dominio <nome>    na duvida entre duas categorias (errar dominio e dificil,
                      errar categoria e facil)
  --sem-recorte       assume o custo acima, de proposito (o tempo muda pouco:
                      ~1-2 s; o que cai e o acerto)

Leia a pergunta e escolha voce mesmo: agente acerta 92% da categoria, maquina
52% (motor/medir_auto_categoria.py). O que existe na base hoje:"""


def _contagem_por_categoria(raiz: Path) -> dict[str, int]:
    """Quantos documentos por categoria, lido das pastas. Sem abrir indice."""
    base = raiz / "markdown"
    if not base.exists():
        return {}
    return {d.name: sum(1 for sub in d.iterdir() if sub.is_dir())
            for d in sorted(base.iterdir()) if d.is_dir()}


def _texto_das_categorias(raiz: Path) -> str:
    """Uma linha por dominio, `categoria (n)`. Cabe em poucas centenas de chars.

    Categoria sem dominio sai numa linha propria em vez de ser omitida: e a
    mesma regra de `dominio.categorias()` -- documento novo nunca some calado.
    """
    contagem = _contagem_por_categoria(raiz)
    if not contagem:
        return "  (nenhuma: markdown/ esta vazio)"
    mapa = dom.carregar(raiz)
    linhas, vistas = [], set()
    for nome in sorted(mapa):
        cats = [c for c in sorted(mapa[nome]) if c in contagem]
        vistas.update(cats)
        if cats:
            linhas.append(f"  {nome}: "
                          + " ".join(f"{c}({contagem[c]})" for c in cats))
    sobra = sorted(set(contagem) - vistas)
    if sobra:
        linhas.append("  sem dominio (entram em todos): "
                      + " ".join(f"{c}({contagem[c]})" for c in sobra))
    return "\n".join(linhas)


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
    # so as MAX_SESSOES mais recentes: o arquivo e cache, nao historico.
    # Sessao de antes de 16/09 guardava 120k indices de passagem (5 MB por
    # arquivo); nao serve mais e sai aqui.
    recentes = sorted(((k, v) for k, v in dados.items() if "indices" not in v),
                      key=lambda kv: -kv[1].get("quando", 0))
    S.escrever_atomico(
        raiz / ARQ_SESSOES,
        lambda p: p.write_text(json.dumps(dict(recentes[:MAX_SESSOES]),
                                          ensure_ascii=False), encoding="utf-8"))


def _id_de_sessao(consulta: str) -> str:
    bruto = f"{consulta}\x00{time.time()}"
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:6]


# ----------------------------------------------------------------- ranking

POOL = 30          # candidatos de cada motor antes da fusao
RRF_K = 60         # Cormack, Clarke & Buettcher (2009); o mesmo do semantico.hibrido


def _pasta(caminho: str) -> str:
    partes = caminho.replace("\\", "/").split("/")
    return "/".join(partes[1:3]) if len(partes) >= 3 else caminho


def _permitidas(raiz, categoria, dominio):
    if categoria:
        return {categoria}
    if dominio:
        return dom.categorias(raiz, dominio)
    return None


def _indices_permitidos(passagens, permitidas):
    if permitidas is None:
        return None
    return np.asarray([i for i, p in enumerate(passagens)
                       if p.get("categoria") in permitidas], dtype=np.int64)


def _melhor_por_documento(pontos, passagens, indices, quantos,
                          chave=_pasta, excluir=frozenset()):
    """Um resultado por grupo: o melhor trecho dele.

    O grupo e o documento (`chave=_pasta`); `chave=str` agrupa por capitulo,
    que e o que `--mais` quer. `excluir` tira grupos inteiros -- e o que faz a
    rodada 2 nao repetir documento julgado.
    """
    ordem = np.argsort(-pontos)
    melhor: dict = {}
    for k in ordem:
        i = int(indices[k]) if indices is not None else int(k)
        d = chave(passagens[i]["caminho"])
        if d in excluir:
            continue
        if d not in melhor:
            melhor[d] = (float(pontos[k]), i)
        if len(melhor) >= quantos:
            break
    return sorted(melhor.items(), key=lambda kv: -kv[1][0])[:quantos]


def _docs_bm25(indice, consultas, permitidas, excluir, quantos):
    """Documentos por BM25 (PT e EN fundidos), um por documento, no recorte."""
    saida, vistos = [], set(excluir)
    for _p, d in bm.fundir(indice, consultas):
        if permitidas is not None and d["categoria"] not in permitidas:
            continue
        doc = _pasta(d["caminho"])
        if doc in vistos:
            continue
        vistos.add(doc)
        saida.append((doc, d["caminho"]))
        if len(saida) >= quantos:
            break
    return saida


def _melhor_no_capitulo(pontos, passagens, indices, caminhos):
    """Para cada capitulo pedido, a passagem dele mais parecida com a consulta.

    O BM25 aponta capitulo; o cartao precisa de uma passagem. Sem isto o
    cartao do BM25 seria o comeco do capitulo, e o reranker leria texto que
    nao tem a ver com a pergunta.
    """
    melhor: dict = {}
    for k, s in enumerate(pontos):
        i = int(indices[k]) if indices is not None else k
        c = passagens[i]["caminho"]
        if c in caminhos and (c not in melhor or s > melhor[c][0]):
            melhor[c] = (float(s), i)
    return melhor


def fundir_rrf(densos, lexicos, quantos, k=RRF_K):
    """Rank reciproco: soma 1/(k+posicao) das duas listas, sem calibrar escala.

    Medido em 16/09 (140 perguntas, recorte de agente): denso 121/140 no hit@6,
    RRF com BM25 127/140, e com vetor PT+EN 129/140. A passagem do documento e
    a do denso quando ele o trouxe; senao a melhor do capitulo que o BM25 achou.
    """
    placar, passagem = {}, {}
    for lista in (densos, lexicos):
        for r, (doc, (_s, i)) in enumerate(lista):
            placar[doc] = placar.get(doc, 0.0) + 1.0 / (k + r + 1)
            passagem.setdefault(doc, i)
    topo = sorted(placar.items(), key=lambda kv: -kv[1])[:quantos]
    return [(doc, (s, passagem[doc])) for doc, s in topo]


def ranquear(passagens, alvo, q, consultas, permitidas, excluir, quantos,
             indice_bm=None):
    """Candidatos de uma rodada: [(documento, (pontos, indice da passagem))].

    Denso (vetor `q`) e BM25 (`consultas`, PT e EN) fundidos por RRF, um por
    documento, ja sem os documentos em `excluir`. `indice_bm=None` e so denso.
    E o mesmo caminho que `avaliar_consultar.py` mede.
    """
    indices = _indices_permitidos(passagens, permitidas)
    pontos = (alvo[indices] if indices is not None else alvo) @ q
    densos = _melhor_por_documento(pontos, passagens, indices, POOL, excluir=excluir)
    if indice_bm is None:
        return densos[:quantos]
    lex = _docs_bm25(indice_bm, consultas, permitidas, excluir, POOL)
    melhor = _melhor_no_capitulo(pontos, passagens, indices, {c for _d, c in lex})
    lexicos = [(d, melhor[c]) for d, c in lex if c in melhor]
    return fundir_rrf(densos, lexicos, quantos)


def rodada(raiz, passagens, alvo, q, consultas, categoria, dominio, excluir,
           quantos, indice_bm=None):
    """`ranquear` no recorte pedido; categoria esgotada completa com o dominio.

    Categoria de 2 documentos, ambos julgados, devolvia lista vazia e a sessao
    morria ali. Agora o que falta vem do dominio da categoria, avisando --
    a sessao decide se vale ler.
    """
    permitidas = _permitidas(raiz, categoria, dominio)
    cands = ranquear(passagens, alvo, q, consultas, permitidas, excluir,
                     quantos, indice_bm)
    aviso = ""
    if categoria and len(cands) < quantos:
        nome = dom.de_categoria(raiz, categoria)
        if nome:
            ja = set(excluir) | {doc for doc, _x in cands}
            extra = ranquear(passagens, alvo, q, consultas,
                             dom.categorias(raiz, nome), ja,
                             quantos - len(cands), indice_bm)
            if extra:
                aviso = (f"categoria {categoria} esgotada: {len(extra)} "
                         f"cartao(oes) vieram do dominio {nome}")
                cands = cands + extra
    return cands, aviso


def _reranquear(raiz, passagens, candidatos, consulta_txt):
    cross = _cross()
    textos = [(d, i, S.texto_da_passagem(raiz, passagens[i]))
              for d, (_s, i) in candidatos]
    textos = [(d, i, t) for d, i, t in textos if t]
    if not textos:
        return candidatos
    notas = list(cross.rerank(consulta_txt, [t for _d, _i, t in textos]))
    juntos = [(d, (float(n), i)) for (d, i, _t), n in zip(textos, notas)]
    return sorted(juntos, key=lambda kv: -kv[1][0])


# ------------------------------------------------------------------ saida


def _ficha(p: dict, i: int) -> dict:
    """O que a sessao guarda de cada cartao: o bastante para `--abrir` sem indice."""
    return {"i": i, "caminho": p["caminho"], "ini": p["ini"], "n": p["n"],
            "titulo": p.get("titulo", ""), "capitulo": p.get("capitulo", ""),
            "paginas": p.get("paginas", "?")}


def _cartao(raiz, n, doc, pontos, p) -> str:
    texto = S.texto_da_passagem(raiz, p) or ""
    palavras = texto.split()[:PALAVRAS_CARTAO]
    trecho = " ".join(palavras) + ("..." if len(texto.split()) > PALAVRAS_CARTAO else "")
    cab = (f"{n}. {pontos:+.3f}  {p.get('titulo', doc)[:58]} "
           f"— {p.get('capitulo', '')[:44]} · p.{p.get('paginas', '?')}")
    return cab + "\n   " + trecho


def _imprimir(raiz, passagens, resultados, sessao_id, rodada, inicio=0, aviso=""):
    for n, (doc, (pontos, i)) in enumerate(resultados, inicio + 1):
        print(_cartao(raiz, n, doc, pontos, passagens[i]))
    if aviso:
        print(f"\n{aviso}")
    print(f"\nsessao {sessao_id} · rodada {rodada}")
    print(f"  abrir:      python consultar.py --sessao {sessao_id} --abrir <n>")
    print(f"  mais do doc: python consultar.py --sessao {sessao_id} --mais <n>")
    print(f"  nao serviu: python consultar.py --sessao {sessao_id} "
          f"--sim <n,n> --nao <n,n>")


# ------------------------------------------------------------ recursos
#
# Tudo que custa segundos fica em cache de processo: na CLI e pago uma vez
# por chamada, como sempre; no servidor.py e pago uma vez por dia. O indice
# e recarregado se o mtime do arquivo mudar (reindexacao), sem reiniciar.

_INDICE: dict = {}      # str(raiz) -> {"mtime", "meta", "alvo"}
_BM: dict = {}          # str(raiz) -> {"mtime", "indice"}
_MODELO = None
_CROSS = None


def _indice(raiz: Path):
    """(meta, alvo float32) do indice semantico, recarregado se mudou no disco."""
    p = raiz / S.ARQ_META
    mtime = p.stat().st_mtime if p.exists() else None
    c = _INDICE.get(str(raiz))
    if c is None or c["mtime"] != mtime:
        meta, vetores = S.carregar(raiz)
        if meta is None:
            return None, None
        c = {"mtime": mtime, "meta": meta, "alvo": vetores.astype(np.float32)}
        _INDICE[str(raiz)] = c
    return c["meta"], c["alvo"]


def _indice_bm(raiz: Path):
    """Indice BM25, relido so quando o json muda; `_mudou` (0,2 s) roda sempre."""
    p = raiz / bm.NOME_INDICE
    mtime = p.stat().st_mtime if p.exists() else None
    c = _BM.get(str(raiz))
    if c is None or c["mtime"] != mtime or bm._mudou(raiz, c["indice"]):
        indice = bm.carregar_indice(raiz)
        mtime = p.stat().st_mtime if p.exists() else None
        c = {"mtime": mtime, "indice": indice}
        _BM[str(raiz)] = c
    return c["indice"]


def _modelo():
    global _MODELO
    if _MODELO is None:
        _MODELO = S._modelo()
    return _MODELO


def _cross():
    global _CROSS
    if _CROSS is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        _CROSS = TextCrossEncoder(S.RERANKER)
    return _CROSS


def aquecer(raiz: Path) -> None:
    """Carrega tudo de uma vez (o servidor chama antes de abrir a porta)."""
    _indice(raiz)
    _indice_bm(raiz)
    _vetor_da_consulta("aquecer")
    _cross()


# ------------------------------------------------------------------ acoes


def _vetor_da_consulta(texto: str) -> np.ndarray:
    return S._normalizar(np.array(list(_modelo().embed([texto])),
                                  dtype=np.float32))[0]


def _vetor_das_consultas(textos: list) -> np.ndarray:
    """Soma normalizada dos vetores: PT e EN viram uma consulta so.

    Medido em 16/09: hit@6 121 -> 129/140 so com isto, sem custo de rede.
    """
    soma = np.sum([_vetor_da_consulta(t) for t in textos], axis=0)
    norma = np.linalg.norm(soma)
    return (soma / norma if norma else soma).astype(np.float32)


def rocchio(q: np.ndarray, vetores: np.ndarray,
            relevantes: list, nao: list) -> np.ndarray:
    novo = ALFA * q
    if relevantes:
        novo = novo + BETA * vetores[relevantes].mean(axis=0)
    if nao:
        novo = novo - GAMA * vetores[nao].mean(axis=0)
    norma = np.linalg.norm(novo)
    return novo / norma if norma else q


def _via_servidor(porta: int, argv: list):
    """Manda o argv ao servidor.py; None se nao ha servidor nessa porta."""
    import socket
    import urllib.error
    import urllib.request

    # porta fechada nesta maquina nao recusa: expira (medido 0,31 s com 0,3 s
    # de limite). 0,1 s basta para um servidor vivo no loopback e e o custo
    # fixo de cada chamada sem servidor.
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=0.1):
            pass
    except OSError:
        return None
    pedido = urllib.request.Request(
        f"http://127.0.0.1:{porta}/", method="POST",
        data=json.dumps({"argv": argv}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("consulta", nargs="*")
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO,
                    help="porta do servidor.py; se responde, ele atende")
    ap.add_argument("--local", action="store_true",
                    help="nao procura o servidor.py; carrega tudo aqui")
    ap.add_argument("--n", type=int, default=6, help="quantos cartoes")
    ap.add_argument("--tambem", help="a mesma pergunta em ingles: soma os "
                    "vetores e roda o BM25 nos dois idiomas")
    ap.add_argument("--categoria")
    ap.add_argument("--dominio")
    ap.add_argument("--sem-recorte", action="store_true",
                    help="busca no corpus inteiro, assumindo 29/53 contra 42/53")
    ap.add_argument("--categorias", action="store_true",
                    help="lista as categorias por dominio e sai")
    ap.add_argument("--sem-rerank", action="store_true",
                    help="pula o cross-encoder (~6 s mais rapido, pior)")
    ap.add_argument("--sem-bm25", action="store_true",
                    help="so o vetor, sem fundir com o BM25 (medido pior)")
    ap.add_argument("--sessao", help="continua uma consulta ja aberta")
    ap.add_argument("--abrir", type=int, help="janela inteira do resultado n")
    ap.add_argument("--mais", type=int,
                    help="outros capitulos do documento do resultado n")
    ap.add_argument("--janela", type=int, default=420)
    ap.add_argument("--sim", default="", help="resultados que servem: 2,4")
    ap.add_argument("--nao", default="", help="resultados que nao servem: 1")
    ap.add_argument("--estado", action="store_true", help="mostra a sessao")
    args = ap.parse_args(argv)

    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    if not args.local:
        resposta = _via_servidor(args.porta,
                                 list(argv if argv is not None else sys.argv[1:]))
        if resposta is not None:
            sys.stdout.write(resposta["saida"])
            sys.stderr.write(resposta["erro"])
            return resposta["codigo"]
        if not (args.categorias or args.abrir or args.estado):
            print(f"servidor.py nao esta na porta {args.porta}: esta chamada carrega "
                  "indice e modelos (8-19 s). Para subir: python servidor.py",
                  file=sys.stderr)

    raiz = args.raiz

    if args.categorias:
        print(_texto_das_categorias(raiz))
        return 0

    # Porteiro: roda antes de carregar o indice para errar rapido e barato.
    if not args.sessao:
        contagem = _contagem_por_categoria(raiz)
        if args.categoria and args.categoria not in contagem:
            # sem isto o filtro sai vazio e a busca imprime nada, sem erro
            print(f"categoria '{args.categoria}' nao existe na base.")
            print(_texto_das_categorias(raiz))
            return 2
        if args.dominio and args.dominio not in dom.carregar(raiz):
            conhecidos = ", ".join(sorted(dom.carregar(raiz)))
            print(f"dominio '{args.dominio}' nao existe. use um de: {conhecidos}")
            return 2
        if not (args.categoria or args.dominio or args.sem_recorte):
            print(EXIGE_RECORTE)
            print(_texto_das_categorias(raiz))
            return 2

    sessoes = _sessoes(raiz)

    def numeros(bruto):
        return [int(x) for x in bruto.replace(" ", "").split(",") if x]

    # ---------------------------------------- sessao: o que nao precisa de indice
    s = None
    if args.sessao:
        s = sessoes.get(args.sessao)
        if not s:
            print(f"sessao {args.sessao} nao existe (ou ja saiu do cache)")
            return 1
        if "indices" in s or any(not isinstance(m, dict) for m in s["mostrados"]):
            print(f"sessao {args.sessao} e de versao anterior: refaca a consulta")
            return 1
        mostrados = s["mostrados"]          # [ficha, ...]

        if args.estado:
            print(f"sessao {args.sessao} · rodada {s['rodada']}")
            print(f"  consulta: {s['consulta']}"
                  + (f"  |  {s['tambem']}" if s.get("tambem") else ""))
            print(f"  recorte: categoria={s.get('categoria')} "
                  f"dominio={s.get('dominio')}")
            print(f"  serviram:     {s['relevantes']}")
            print(f"  nao serviram: {s['nao']}")
            return 0

        if args.abrir:
            # so le o capitulo: nem json de 80 MB, nem npz, nem modelo
            if not 1 <= args.abrir <= len(mostrados):
                print(f"escolha entre 1 e {len(mostrados)}")
                return 1
            p = mostrados[args.abrir - 1]
            janela = S.janela_da_passagem(raiz, p, args.janela) or ""
            print(f"{p.get('titulo','')} — {p.get('capitulo','')} "
                  f"· p.{p.get('paginas','?')}")
            print(f"{p['caminho']}\n")
            print(textwrap.fill(janela, 96))
            return 0

    meta, alvo = _indice(raiz)
    if meta is None:
        print("indice semantico nao existe - rode: python semantico.py indexar")
        return 1
    aviso_indice = S.conferir(raiz, meta)
    if aviso_indice:
        print(aviso_indice, file=sys.stderr)
    passagens = meta["passagens"]

    # ------------------------------------------------- continuar uma sessao
    if s is not None:
        if args.mais:
            if not 1 <= args.mais <= len(mostrados):
                print(f"escolha entre 1 e {len(mostrados)}")
                return 1
            doc = _pasta(mostrados[args.mais - 1]["caminho"])
            q = np.asarray(s["q"], dtype=np.float32)
            ids = np.asarray([i for i, p in enumerate(passagens)
                              if _pasta(p["caminho"]) == doc], dtype=np.int64)
            vistos = {m["caminho"] for m in mostrados if _pasta(m["caminho"]) == doc}
            cands = _melhor_por_documento(alvo[ids] @ q, passagens, ids, args.n,
                                          chave=str, excluir=vistos)
            if not args.sem_rerank and cands:
                cands = _reranquear(raiz, passagens, cands, s["consulta"])
            inicio = len(mostrados)
            s["mostrados"] = mostrados + [_ficha(passagens[i], i)
                                          for _d, (_p, i) in cands]
            s["quando"] = time.time()
            _gravar_sessoes(raiz, sessoes)
            _imprimir(raiz, passagens, cands, args.sessao, s["rodada"], inicio)
            return 0

        # nova rodada: move a consulta e reranqueia
        sim = [mostrados[n - 1]["i"] for n in numeros(args.sim)
               if 1 <= n <= len(mostrados)]
        nao = [mostrados[n - 1]["i"] for n in numeros(args.nao)
               if 1 <= n <= len(mostrados)]
        if not sim and not nao:
            print("nada a fazer: passe --sim e/ou --nao, --abrir ou --mais")
            return 1
        s["relevantes"] = sorted(set(s["relevantes"]) | set(sim))
        s["nao"] = sorted(set(s["nao"]) | set(nao))
        q = rocchio(np.asarray(s["q"], dtype=np.float32), alvo,
                    s["relevantes"], s["nao"])
        s["q"] = q.tolist()
        s["rodada"] += 1
        # documento cujo cartao ja apareceu nao volta: a sessao ja o viu
        excluir = {_pasta(m["caminho"]) for m in mostrados}
    else:
        consulta_txt = " ".join(args.consulta).strip()
        if not consulta_txt:
            ap.print_help()
            return 1
        s = {"consulta": consulta_txt, "tambem": args.tambem or "",
             "categoria": args.categoria, "dominio": args.dominio,
             "rodada": 1, "relevantes": [], "nao": [], "mostrados": []}
        q = _vetor_das_consultas([consulta_txt] + ([args.tambem] if args.tambem else []))
        s["q"] = q.tolist()
        args.sessao = _id_de_sessao(consulta_txt)
        excluir = set()

    consultas = [s["consulta"]] + ([s["tambem"]] if s.get("tambem") else [])
    indice_bm = None if args.sem_bm25 else _indice_bm(raiz)
    cands, aviso = rodada(raiz, passagens, alvo, q, consultas, s.get("categoria"),
                          s.get("dominio"), excluir, args.n, indice_bm)

    if not args.sem_rerank and cands:
        cands = _reranquear(raiz, passagens, cands, s["consulta"])

    s["mostrados"] = s["mostrados"] + [_ficha(passagens[i], i)
                                       for _d, (_p, i) in cands]
    s["quando"] = time.time()
    sessoes[args.sessao] = s
    _gravar_sessoes(raiz, sessoes)

    _imprimir(raiz, passagens, cands, args.sessao, s["rodada"],
              len(s["mostrados"]) - len(cands), aviso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
