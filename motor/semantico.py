"""Busca semantica multilingue na base — offline, sem custo por consulta.

Resolve o furo do `buscar.py`: BM25 casa palavra, entao pergunta em portugues
nao acha capitulo em ingles. Aqui a comparacao e de sentido, num espaco vetorial
compartilhado entre idiomas (medido: "objecao de preco" x "price objection" =
0,77; x "borrow checker do Rust" = 0,15).

Modelo: paraphrase-multilingual-MiniLM-L12-v2 via fastembed (ONNX, ~220 MB,
roda em CPU). Baixa uma vez e fica em cache.

    python semantico.py indexar                 # incremental: so o que mudou
    python semantico.py indexar --refazer       # reconstroi tudo
    python semantico.py "como responder que esta caro"
    python semantico.py "value pricing" --rerank --passagens
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import textwrap
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from buscar import _frontmatter  # noqa: E402

import dominio as dom

from raiz import RAIZ_PADRAO  # noqa: E402
MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
ARQ_VETORES = ".indice-semantico.npz"
ARQ_META = ".indice-semantico.json"
ARQ_TRAVA = ".indice-semantico.lock"


class IndiceEmUso(RuntimeError):
    pass


@contextlib.contextmanager
def travar(raiz: Path):
    """Uma indexacao por vez.

    Em 09/09/2026 duas rodadas de `indexar` correram juntas e a segunda leu o
    .npz no meio da escrita da primeira: `BadZipFile`, indice de 151 MB
    inutilizado e 40 min de CPU para refazer. O_EXCL e a checagem barata que
    evita repetir isso.
    """
    trava = raiz / ARQ_TRAVA
    try:
        fd = os.open(trava, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise IndiceEmUso(
            f"ja existe uma indexacao em andamento ({trava}).\n"
            f"    Se nenhuma estiver rodando, apague o arquivo e tente de novo."
        ) from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        with contextlib.suppress(OSError):
            trava.unlink()


def escrever_atomico(destino: Path, escreve) -> None:
    """Escreve num temporario e so entao troca pelo destino.

    `np.savez_compressed` direto no destino deixa arquivo pela metade quando a
    rodada morre no meio -- e o que sobra nao e recuperavel, so refazivel.
    """
    # o ".parcial" vai ANTES da extensao: `np.savez_compressed` acrescenta
    # ".npz" sozinho quando o nome nao termina nisso, e um temporario
    # "...npz.parcial" viraria "...npz.parcial.npz" -- o os.replace trocaria
    # um arquivo que nunca foi escrito
    temporario = destino.with_name(destino.stem + ".parcial" + destino.suffix)
    try:
        escreve(temporario)
        os.replace(temporario, destino)
    except BaseException:
        with contextlib.suppress(OSError):
            temporario.unlink()
        raise

# Passagem curta, e nao "o maior que couber na janela". Medido nesta base com a
# consulta "objecao de preco cliente acha caro" contra dois capitulos-alvo
# (Gap Selling 13, Pricing Creativity 8) e dois distratores:
#
#   200 palavras -> distrator (Don't Make Me Think) 0,659 vence os dois alvos
#    90 palavras -> alvos em 1o e 2o, distrator cai para 0,509
#    50 palavras -> Gap Selling 1o com 0,641, distrator 0,516
#
# O modelo e `paraphrase`, treinado em frases curtas: passagem longa vira uma
# media de assuntos e perde o que a distingue. Custo em tokens e quase o mesmo,
# porque o texto total nao muda - o que cresce e a contagem de passagens.
PASSAGEM_PALAVRAS = 60
AVANCO = 50               # 10 palavras de sobreposicao
LOTE = 1024


def _corpo(texto: str) -> str:
    if texto.startswith("---"):
        fim = texto.find("\n---", 3)
        if fim != -1:
            return texto[fim + 4:]
    return texto


def _passagens(corpo: str):
    """Fatia em janelas deslizantes de palavras. Devolve (ini, n, texto)."""
    palavras = corpo.split()
    saida = []
    i = 0
    while i < len(palavras):
        pedaco = palavras[i:i + PASSAGEM_PALAVRAS]
        if len(pedaco) < 25 and saida:      # sobra pequena entra na anterior
            break
        saida.append((i, len(pedaco), " ".join(pedaco)))
        if i + PASSAGEM_PALAVRAS >= len(palavras):
            break
        i += AVANCO
    return saida


def _arquivos(raiz: Path):
    return [
        p for p in sorted((raiz / "markdown").rglob("*.md"))
        if p.name != "INDEX.md"
    ]


def _modelo():
    import os

    from fastembed import TextEmbedding

    return TextEmbedding(MODELO, threads=os.cpu_count() or 4)


def _normalizar(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return v / n


CAMPOS_META = ("titulo", "capitulo", "categoria", "idioma", "paginas")


def _meta_da_passagem(campos: dict, caminho: Path) -> dict:
    """Metadado que a busca mostra. Sai sempre do frontmatter atual."""
    return {
        "titulo": campos.get("titulo", caminho.parent.name),
        "capitulo": campos.get("capitulo", caminho.stem),
        "categoria": campos.get("categoria", caminho.parent.parent.name),
        "idioma": campos.get("idioma", "xx"),
        "paginas": campos.get("paginas", ""),
    }


def _assinatura_meta(campos: dict) -> str:
    """Hash so dos campos que a busca exibe ou filtra, mais `util`."""
    bruto = "\x00".join(str(campos.get(c, "")) for c in CAMPOS_META)
    bruto += "\x00" + str(campos.get("util", ""))
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:12]


def indexar(raiz: Path, refazer: bool = False) -> dict:
    meta_path, vet_path = raiz / ARQ_META, raiz / ARQ_VETORES
    antigo = {}
    vetores_antigos = None
    if not refazer and meta_path.exists() and vet_path.exists():
        try:
            antigo = json.loads(meta_path.read_text(encoding="utf-8"))
            vetores_antigos = np.load(vet_path)["v"]
        except Exception as e:
            # indice truncado ou de versao anterior: dizer o que fazer vale mais
            # que um traceback de zipfile no meio de uma rodada de 40 min
            raise RuntimeError(
                f"indice ilegivel ({e.__class__.__name__}: {e}).\n"
                f"    Reconstrua do zero: python semantico.py indexar --refazer"
            ) from e

    hashes_antigos = antigo.get("hashes", {})
    passagens_antigas = antigo.get("passagens", [])

    # A chave e o hash do CORPO, nao o mtime: mudar categoria, idioma ou `util`
    # reescreve o frontmatter de centenas de arquivos, e por mtime isso mandaria
    # reembutir a base inteira (~40 min de CPU) sem uma palavra de texto ter
    # mudado. Por hash do corpo, essa revisao custa zero embedding.
    arquivos = _arquivos(raiz)
    atuais, corpos, campos_por_arq, metas = {}, {}, {}, {}
    for p in arquivos:
        rel = str(p.relative_to(raiz)).replace("\\", "/")
        bruto = p.read_text(encoding="utf-8", errors="replace")
        corpo = _corpo(bruto)
        campos = _frontmatter(bruto)
        atuais[rel] = hashlib.sha1(corpo.encode("utf-8")).hexdigest()[:16]
        corpos[rel] = (bruto, corpo)
        campos_por_arq[rel] = campos
        metas[rel] = _assinatura_meta(campos)
    mudaram = [c for c, h in atuais.items() if hashes_antigos.get(c) != h]
    sumiram = [c for c in hashes_antigos if c not in atuais]

    # Metadado muda sem o corpo mudar: corrigir um titulo, trocar o idioma,
    # marcar `util: nao`. O hash do corpo nao ve nada disso — e de proposito,
    # para nao reembutir a base inteira — mas as passagens mantidas vinham
    # copiadas do indice antigo, com o metadado velho junto. Medido em 07/09:
    # dois titulos corrigidos a mao continuaram errados na busca depois de
    # `indexar`, que respondeu "nada mudou". Aqui a mudanca e detectada e o
    # metadado das mantidas e reescrito do frontmatter, sem custar embedding.
    metas_antigas = antigo.get("metas", {})
    meta_mudou = [c for c, h in metas.items() if metas_antigas.get(c) != h]

    if not mudaram and not sumiram and not meta_mudou and vetores_antigos is not None:
        print(f"nada mudou - {len(passagens_antigas)} passagens no indice")
        return antigo

    if not mudaram and not sumiram:
        print(f"{len(meta_mudou)} arquivo(s) com metadado novo, nenhum corpo alterado")

    print(f"{len(mudaram)} arquivo(s) novo(s)/alterado(s), {len(sumiram)} sumido(s)")

    # o que sobrevive do indice anterior
    guardar = [
        (i, p) for i, p in enumerate(passagens_antigas)
        if p["caminho"] in atuais and p["caminho"] not in mudaram
    ]
    # o vetor e reaproveitado, o metadado e relido: sao coisas separadas.
    # Passagem que virou `util: nao` sai agora, senao ficaria no indice ate
    # alguem mexer no texto dela.
    guardar = [(i, p) for i, p in guardar
               if campos_por_arq[p["caminho"]].get("util") != "nao"]
    mantidas = [
        {**p, **_meta_da_passagem(campos_por_arq[p["caminho"]], raiz / p["caminho"])}
        for _i, p in guardar
    ]
    vetores_mantidos = (
        vetores_antigos[[i for i, _ in guardar]]
        if vetores_antigos is not None and guardar
        else np.zeros((0, 384), dtype=np.float16)
    )

    novas, textos = [], []
    for caminho in mudaram:
        p = raiz / caminho
        bruto, corpo = corpos[caminho]
        campos = _frontmatter(bruto)
        if campos.get("util") == "nao":
            continue    # nao gasta embedding em copyright, sumario ou indice
        for ini, n, texto in _passagens(corpo):
            novas.append({"caminho": caminho, "ini": ini, "n": n,
                          **_meta_da_passagem(campos, p)})
            textos.append(texto)

    if textos:
        print(f"{len(textos)} passagens para embutir")
        modelo = _modelo()
        inicio = time.time()
        vetores = []
        for i in range(0, len(textos), LOTE):
            vetores.extend(modelo.embed(textos[i:i + LOTE], batch_size=64))
            feitos = min(i + LOTE, len(textos))
            decorrido = time.time() - inicio
            print(
                f"  {feitos}/{len(textos)}  {feitos / max(decorrido, 0.01):.0f}/s",
                flush=True,
            )
        novos_vetores = _normalizar(np.array(vetores, dtype=np.float32)).astype(np.float16)
    else:
        novos_vetores = np.zeros((0, 384), dtype=np.float16)

    todos = np.vstack([vetores_mantidos, novos_vetores]) if len(mantidas) else novos_vetores
    passagens = mantidas + novas

    meta = {"modelo": MODELO, "hashes": atuais, "metas": metas,
            "passagens": passagens}
    # vetores primeiro: se a troca do meta falhar, o .npz novo ainda casa com o
    # meta velho pelos hashes, e a rodada seguinte reconstroi so a diferenca
    escrever_atomico(vet_path, lambda p: np.savez_compressed(p, v=todos))
    escrever_atomico(meta_path, lambda p: p.write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"))
    print(f"indice: {len(passagens)} passagens, {todos.nbytes / 1e6:.1f} MB")
    return meta


def carregar(raiz: Path):
    meta_path, vet_path = raiz / ARQ_META, raiz / ARQ_VETORES
    if not meta_path.exists() or not vet_path.exists():
        return None, None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return meta, np.load(vet_path)["v"]


def texto_da_passagem(raiz: Path, p: dict) -> str:
    """Trecho de uma passagem. Devolve "" se o arquivo saiu de baixo do indice.

    `processar.py --mover` e `--remover` mudam o caminho no disco sem tocar no
    indice. Medido em 07/09: 4 documentos movidos deixaram 9.185 passagens
    (8,7%) orfas e o `--rerank` morria com FileNotFoundError em 7 de 8
    consultas. Aqui a passagem orfa so e descartada, com aviso na stderr
    dizendo o que rodar - resultado faltando e melhor que consulta morta, mas
    silencio seria pior que os dois.
    """
    try:
        bruto = (raiz / p["caminho"]).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        print(f"indice desatualizado em {p['caminho']} - "
              f"rode: python semantico.py indexar", file=sys.stderr)
        return ""
    return " ".join(_corpo(bruto).split()[p["ini"]: p["ini"] + p["n"]])


JANELA_PADRAO = 420


def janela_da_passagem(raiz: Path, p: dict, palavras: int = JANELA_PADRAO) -> str:
    """Small-to-big: acha pelo trecho pequeno, entrega o trecho grande.

    A passagem de 60 palavras e o tamanho que o modelo compara melhor (medido:
    passagem de 200 deixava o distrator ganhar dos dois alvos). Mas 60 palavras
    entregam um pedaco de frase, sem o que vem antes nem depois — quem le fica
    sem contexto e precisa abrir o capitulo inteiro.

    Entao a busca continua sendo feita no pequeno e a entrega passa a ser a
    janela em volta. Tecnica descrita em "Building LLMs for Production", cap.
    "Advanced RAG Techniques" (pag. 220-229), que esta nesta base.

    A janela e alinhada a fronteira de frase para nao comecar no meio de uma.
    """
    try:
        bruto = (raiz / p["caminho"]).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    tokens = _corpo(bruto).split()
    if not tokens:
        return ""

    meio = p["ini"] + p["n"] // 2
    ini = max(0, meio - palavras // 2)
    fim = min(len(tokens), ini + palavras)
    ini = max(0, fim - palavras)          # janela cheia mesmo colada no fim
    trecho = " ".join(tokens[ini:fim])

    # comeca depois do primeiro ponto final e termina no ultimo, para nao cortar
    # frase ao meio; se nao houver ponto, fica como esta
    if ini > 0:
        corte = trecho.find(". ")
        if 0 <= corte < len(trecho) // 3:
            trecho = trecho[corte + 2:]
    if fim < len(tokens):
        corte = trecho.rfind(". ")
        if corte > len(trecho) * 2 // 3:
            trecho = trecho[: corte + 1]
    return ("... " if ini > 0 else "") + trecho + (" ..." if fim < len(tokens) else "")


def procurar(raiz: Path, consulta: str, n: int = 10, categoria: str | None = None,
             permitidas: set | None = None):
    """Top-n capitulos por melhor passagem. Devolve (pontos, passagem)."""
    meta, vetores = carregar(raiz)
    if meta is None:
        return None
    q = _normalizar(np.array(list(_modelo().embed([consulta])), dtype=np.float32))[0]
    pontos = vetores.astype(np.float32) @ q

    melhor = {}
    for i, p in enumerate(meta["passagens"]):
        if categoria and p["categoria"] != categoria:
            continue
        if permitidas is not None and p["categoria"] not in permitidas:
            continue
        chave = p["caminho"]
        if chave not in melhor or pontos[i] > melhor[chave][0]:
            melhor[chave] = (float(pontos[i]), p)
    ordenado = sorted(melhor.values(), key=lambda x: -x[0])
    return ordenado[:n]


RERANKER = "jinaai/jina-reranker-v2-base-multilingual"


def reranquear(raiz: Path, consulta: str, n: int = 10,
               categoria: str | None = None, topo: int = 50,
               permitidas: set | None = None):
    """Retrieval traz candidatos; o cross-encoder le pergunta e passagem juntas.

    Medido em 07/09 com 53 perguntas contra o corpus inteiro: acerto em primeiro
    lugar sobe de 25 para 33, MRR de 0,618 para 0,714. Custa ~6 s por consulta,
    porque sao `topo` inferencias de um modelo de 1,1 GB — nao da para aplicar ao
    indice todo, so a uma lista curta.
    """
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    meta, vetores = carregar(raiz)
    if meta is None:
        return None
    q = _normalizar(np.array(list(_modelo().embed([consulta])), dtype=np.float32))[0]
    pontos = vetores.astype(np.float32) @ q

    indices = np.argsort(-pontos)
    if categoria:
        indices = [i for i in indices if meta["passagens"][i]["categoria"] == categoria]
    if permitidas is not None:
        indices = [i for i in indices
                   if meta["passagens"][i]["categoria"] in permitidas]
    escolhidos = list(indices[:topo])

    # Passagem orfa vem vazia e nao tem o que reranquear: sai antes do
    # cross-encoder, senao ocuparia uma das `topo` vagas com texto vazio.
    pares = [(i, texto_da_passagem(raiz, meta["passagens"][i])) for i in escolhidos]
    pares = [(i, t) for i, t in pares if t]
    if not pares:
        return []
    escolhidos = [i for i, _ in pares]
    trechos = [t for _, t in pares]
    notas = list(TextCrossEncoder(RERANKER).rerank(consulta, trechos))

    melhor = {}
    for indice, nota in zip(escolhidos, notas):
        p = meta["passagens"][indice]
        if p["caminho"] not in melhor or nota > melhor[p["caminho"]][0]:
            melhor[p["caminho"]] = (float(nota), p)
    return sorted(melhor.values(), key=lambda x: -x[0])[:n]


def hibrido(raiz: Path, consulta: str, n: int = 10, categoria: str | None = None,
            permitidas: set | None = None):
    """Fusao por rank reciproco: semantico acha sentido, BM25 ancora termo exato.

    Nome proprio, sigla e jargao (FTP, EBT, useEffect) o BM25 acerta melhor;
    pergunta em outro idioma so o semantico acha. RRF junta sem calibrar escala.
    """
    import buscar as bm

    K = 60
    sem = procurar(raiz, consulta, n=200, categoria=categoria,
                   permitidas=permitidas) or []
    indice = bm.carregar_indice(raiz)
    lex = bm.bm25(indice, consulta)
    if categoria:
        lex = [r for r in lex if r[2]["categoria"] == categoria]
    if permitidas is not None:
        lex = [r for r in lex if r[2]["categoria"] in permitidas]

    placar, ficha = {}, {}
    for posicao, (_pontos, p) in enumerate(sem):
        placar[p["caminho"]] = placar.get(p["caminho"], 0) + 1 / (K + posicao + 1)
        ficha[p["caminho"]] = p
    for posicao, (_pontos, _t, d) in enumerate(lex[:200]):
        c = d["caminho"]
        placar[c] = placar.get(c, 0) + 1 / (K + posicao + 1)
        ficha.setdefault(c, d)
    ordenado = sorted(placar.items(), key=lambda kv: -kv[1])[:n]
    return [(pontos, ficha[c]) for c, pontos in ordenado]


def main() -> int:
    ap = argparse.ArgumentParser(description="Busca semantica multilingue")
    ap.add_argument("consulta", nargs="*", help='pergunta, ou "indexar"')
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--categoria")
    dom.adicionar_argumento(ap)
    ap.add_argument("--passagens", action="store_true",
                    help="mostra a janela de texto em volta do achado")
    ap.add_argument("--janela", type=int, default=JANELA_PADRAO,
                    help="palavras entregues por resultado (small-to-big)")
    ap.add_argument("--hibrido", action="store_true", help="funde com o BM25")
    ap.add_argument("--rerank", action="store_true",
                    help="reordena os melhores com cross-encoder (+6s, bem melhor)")
    ap.add_argument("--topo", type=int, default=50)
    ap.add_argument("--refazer", action="store_true")
    args = ap.parse_args()

    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    if not args.consulta:
        ap.print_help()
        return 1
    if args.consulta[0] == "indexar":
        try:
            with travar(args.raiz):
                indexar(args.raiz, refazer=args.refazer)
        except IndiceEmUso as e:
            print(f"erro: {e}")
            return 1
        return 0

    consulta = " ".join(args.consulta)
    if carregar(args.raiz)[0] is None:
        print("indice semantico nao existe - rode: python semantico.py indexar")
        return 1

    permitidas = dom.categorias(args.raiz, args.dominio)
    recorte = f" · dominio {args.dominio}" if args.dominio else ""
    if args.rerank:
        achados = reranquear(args.raiz, consulta, n=args.n,
                             categoria=args.categoria, topo=args.topo,
                             permitidas=permitidas)
        modo_busca = f"semantico + reranker top-{args.topo}{recorte}"
    elif args.hibrido:
        achados = hibrido(args.raiz, consulta, n=args.n, categoria=args.categoria,
                          permitidas=permitidas)
        modo_busca = f"hibrido (mede pior que o semantico puro){recorte}"
    else:
        achados = procurar(args.raiz, consulta, n=args.n, categoria=args.categoria,
                           permitidas=permitidas)
        modo_busca = f"semantico{recorte}"
    if not achados:
        print(f'nada para "{consulta}"')
        return 1

    print(f'{modo_busca} — "{consulta}":')
    print()
    for pontos, p in achados:
        print(f"{pontos:6.3f}  {p['titulo']} — {p.get('capitulo', '?')}")
        print(f"        {p['categoria']} [{p.get('idioma','xx')}] "
              f"· pag {p.get('paginas') or '?'} · {p['caminho']}")
        if args.passagens and "ini" in p:
            # small-to-big: a busca achou pelas 60 palavras, mas o que sai e a
            # janela em volta - contexto suficiente para nao precisar abrir o
            # capitulo inteiro
            trecho = janela_da_passagem(args.raiz, p, args.janela)
            for linha in textwrap.wrap(trecho, 92)[:14]:
                print(f"        {linha}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
