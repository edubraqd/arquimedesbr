"""Guarda o caminho que deu certo, para a proxima pergunta parecida chegar antes.

O AI-Powered Search chama isso de *crowdsourced relevance* (cap. 4, pag. 95-122,
nesta base): o sinal mais barato e mais confiavel de relevancia nao vem do
modelo, vem de quem usou. Hoje a base joga esse sinal fora — cada consulta
comeca do zero, mesmo quando a mesma pergunta ja foi respondida bem ontem.

Aqui cada acerto vira uma trilha: `pergunta -> capitulo que resolveu`. Numa
consulta nova, perguntas antigas **parecidas** (cosseno dos embeddings) emprestam
seus capitulos, que sobem no ranking.

Duas escolhas deliberadas:

- **reforco, nunca filtro.** Trilha empurra o que ja funcionou, mas nao esconde o
  resto. Senao a base congela no que ja se sabe e nunca mostra material novo —
  e o efeito piora sozinho, porque o que nunca aparece nunca ganha trilha.
- **o peso satura.** Marcar dez vezes o mesmo capitulo nao vale dez vezes mais:
  o bonus cresce com o log da contagem. Sem isso, uma consulta repetida sequestra
  o ranking inteiro.

    python trilhas.py --marcar "pergunta" markdown/.../03-cap.md
    python trilhas.py --semear          # cria trilhas a partir do gabarito
    python trilhas.py --listar
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import semantico as S

from raiz import RAIZ_PADRAO  # noqa: E402
ARQ_TRILHAS = "trilhas.jsonl"
ARQ_VETORES = ".trilhas-vetores.npz"

SEMELHANCA_MINIMA = 0.55   # abaixo disso a pergunta antiga nao tem a ver
PESO = 0.10                # escala do bonus, na mesma unidade do cosseno


def caminho_trilhas(raiz: Path) -> Path:
    return raiz / ARQ_TRILHAS


def marcar(raiz: Path, pergunta: str, capitulo: str, util: bool = True) -> None:
    """Registra que este capitulo resolveu (ou nao) esta pergunta."""
    linha = {
        "pergunta": pergunta,
        "capitulo": str(capitulo).replace("\\", "/"),
        "util": bool(util),
        "quando": date.today().isoformat(),
    }
    with caminho_trilhas(raiz).open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    (raiz / ARQ_VETORES).unlink(missing_ok=True)      # cache invalidado


def carregar(raiz: Path) -> list:
    arquivo = caminho_trilhas(raiz)
    if not arquivo.exists():
        return []
    saida = []
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            try:
                saida.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    return saida


def _vetores(raiz: Path, perguntas: list) -> np.ndarray:
    """Embedding de cada pergunta ja registrada, em cache."""
    cache = raiz / ARQ_VETORES
    if cache.exists():
        dados = np.load(cache, allow_pickle=True)
        if len(dados["v"]) == len(perguntas):
            return dados["v"]
    if not perguntas:
        return np.zeros((0, 384), dtype=np.float32)
    v = S._normalizar(
        np.array(list(S._modelo().embed(perguntas)), dtype=np.float32)
    )
    np.savez_compressed(cache, v=v)
    return v


def bonus_por_passagem(raiz: Path, consulta: str, passagens: list,
                       peso: float = PESO) -> np.ndarray:
    """Bonus para passagens de capitulos que ja resolveram pergunta parecida."""
    registros = [t for t in carregar(raiz) if t.get("util")]
    if not registros:
        return np.zeros(len(passagens), dtype=np.float32)

    vetores = _vetores(raiz, [t["pergunta"] for t in registros])
    q = S._normalizar(
        np.array(list(S._modelo().embed([consulta])), dtype=np.float32)
    )[0]
    semelhanca = vetores @ q

    forca = defaultdict(float)
    for t, s in zip(registros, semelhanca):
        if s >= SEMELHANCA_MINIMA:
            forca[t["capitulo"]] += float(s)
    if not forca:
        return np.zeros(len(passagens), dtype=np.float32)

    # satura: dez marcacoes nao valem dez vezes uma
    peso_por_capitulo = {c: peso * math.log1p(f) for c, f in forca.items()}
    return np.array(
        [peso_por_capitulo.get(p.get("caminho", ""), 0.0) for p in passagens],
        dtype=np.float32,
    )


def semear(raiz: Path) -> int:
    """Trilhas iniciais a partir do gabarito — 53 pares pergunta->documento certos.

    O gabarito e exatamente isto: julgamento humano de qual documento responde
    qual pergunta. Comecar com ele evita a partida a frio, em que a trilha so
    serve depois de meses de uso.
    """
    from gabarito import GABARITO

    ja = {(t["pergunta"], t["capitulo"]) for t in carregar(raiz)}
    novas = 0
    for pergunta, marcas in GABARITO:
        for pasta in sorted((raiz / "markdown").glob("*/*")):
            if not pasta.is_dir() or not any(m in pasta.name for m in marcas):
                continue
            # o capitulo mais longo do documento certo e a aposta menos ruim
            # quando o gabarito so aponta o documento
            capitulos = [p for p in pasta.glob("*.md") if p.name != "INDEX.md"]
            if not capitulos:
                continue
            melhor = max(capitulos, key=lambda p: p.stat().st_size)
            rel = str(melhor.relative_to(raiz)).replace("\\", "/")
            if (pergunta, rel) in ja:
                continue
            marcar(raiz, pergunta, rel)
            novas += 1
    return novas


def listar(raiz: Path, n: int = 20) -> None:
    registros = carregar(raiz)
    if not registros:
        print("nenhuma trilha ainda - use --marcar ou --semear")
        return
    contagem = defaultdict(int)
    for t in registros:
        if t.get("util"):
            contagem[t["capitulo"]] += 1
    print(f"{len(registros)} trilhas, {len(contagem)} capitulos reforcados\n")
    for capitulo, quantas in sorted(contagem.items(), key=lambda kv: -kv[1])[:n]:
        print(f"  {quantas:3}x  {capitulo}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--marcar", nargs=2, metavar=("PERGUNTA", "CAPITULO"))
    ap.add_argument("--inutil", action="store_true", help="marca como nao resolveu")
    ap.add_argument("--semear", action="store_true")
    ap.add_argument("--listar", action="store_true")
    args = ap.parse_args()

    if args.marcar:
        marcar(args.raiz, args.marcar[0], args.marcar[1], util=not args.inutil)
        print("registrado")
    elif args.semear:
        print(f"{semear(args.raiz)} trilhas semeadas a partir do gabarito")
    else:
        listar(args.raiz)
    return 0


if __name__ == "__main__":
    sys.exit(main())
