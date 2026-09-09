"""Assunto deixa de ser um so: cada documento passa a ter os assuntos que tem.

O problema que isto resolve foi medido tres vezes hoje. A pasta e uma so — o
disco exige — e a classificacao por palavra-chave era obrigada a escolher.
Resultado: Actionable Gamification foi parar em `rust` (por causa de
"ownership"), Apaixone-se pelo Problema idem (por causa de "cargo"), e a
predicao automatica de categoria acerta so 52% de primeira porque `vendas`,
`marketing`, `copy-persuasao` e `posicionamento-negocio` se sobrepoem.

Nenhum desses e erro de calibragem: um livro sobre engajamento **e** UX e
psicologia e marketing ao mesmo tempo. Forcar um vencedor joga fora informacao
verdadeira.

Aqui a pasta continua sendo uma (o assunto dominante, para o disco), e o
frontmatter ganha `assuntos` com todos que passam do corte. A busca filtra e
reforca por qualquer um deles.

    python facetas.py --seco        # mostra o que atribuiria
    python facetas.py               # grava `assuntos` no frontmatter
    python facetas.py --resumo      # quantos documentos por assunto
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import catalogar
from buscar import _frontmatter, ler_capitulo
from semantico import _corpo

from raiz import RAIZ_PADRAO  # noqa: E402

# Fracao do placar do vencedor que um assunto precisa alcancar para tambem valer.
# 0,45 foi escolhido para pegar o segundo assunto forte sem arrastar ruido: com
# 0,3 quase todo livro de negocio virava "vendas" tambem.
CORTE = 0.45
MAX_ASSUNTOS = 3


def placar(caminho: Path, titulo: str, amostra: str) -> dict:
    """Mesma contagem do `catalogar.classificar`, mas guardando todos os pontos."""
    nome = (caminho.stem + " " + titulo).lower().replace("-", " ")
    corpo = amostra.lower()
    saida = {}
    for categoria, (_rotulo, termos) in catalogar.CATEGORIAS.items():
        pontos = 0
        for termo in termos:
            if termo in nome:
                pontos += 6
            pontos += min(corpo.count(termo), 8)
        if pontos:
            saida[categoria] = pontos
    return saida


def assuntos_de(placar_: dict, dominante: str | None = None) -> list:
    """Todos os assuntos que chegam perto do vencedor, o dominante em primeiro."""
    if not placar_:
        return [dominante] if dominante else []
    teto = max(placar_.values())
    escolhidos = [c for c, p in sorted(placar_.items(), key=lambda kv: -kv[1])
                  if p >= teto * CORTE][:MAX_ASSUNTOS]
    if dominante and dominante in escolhidos:
        escolhidos.remove(dominante)
        escolhidos.insert(0, dominante)
    elif dominante:
        escolhidos.insert(0, dominante)
    return escolhidos[:MAX_ASSUNTOS]


def _amostra_do_documento(pasta: Path, limite: int = 60000) -> str:
    pedacos, total = [], 0
    for md in sorted(pasta.glob("*.md")):
        if md.name == "INDEX.md":
            continue
        bruto = ler_capitulo(md)
        if bruto is None:
            continue
        if _frontmatter(bruto).get("util") == "nao":
            continue
        corpo = _corpo(bruto)
        pedacos.append(corpo[:12000])
        total += len(corpo)
        if total > limite:
            break
    return "\n".join(pedacos)


def _pesos_por_raridade(placares: dict) -> dict:
    """Categoria que pontua em quase todo documento nao distingue nada.

    Medido: `ia-llm` entrava como segundo assunto em Mindset, Rapido e Devagar,
    StoryBrand e Pragmatic Programmer, porque seus termos ("agent", "token",
    "prompt") aparecem em qualquer texto. E o mesmo IDF que o `rotular.py` usa
    para os conceitos: quanto mais espalhada a categoria, menos vale o ponto.
    """
    import math

    n = max(len(placares), 1)
    aparicoes = Counter()
    for placar_ in placares.values():
        aparicoes.update(placar_.keys())
    return {
        categoria: math.log(n / quantas) + 1.0
        for categoria, quantas in aparicoes.items()
    }


def aplicar(raiz: Path, seco: bool = False) -> int:
    import processar

    pastas, dados = [], {}
    for pasta in sorted((raiz / "markdown").glob("*/*")):
        if not pasta.is_dir():
            continue
        capitulos = [p for p in sorted(pasta.glob("*.md")) if p.name != "INDEX.md"]
        if not capitulos:
            continue
        campos = _frontmatter(capitulos[0].read_text(encoding="utf-8",
                                                     errors="replace"))
        bruto = placar(Path(campos.get("fonte", pasta.name)),
                       campos.get("titulo", pasta.name),
                       _amostra_do_documento(pasta))
        pastas.append(pasta)
        dados[pasta] = (campos, capitulos, bruto)

    peso = _pesos_por_raridade({k: v[2] for k, v in dados.items()})

    mudou = 0
    contagem = Counter()
    for pasta in pastas:
        campos, capitulos, bruto = dados[pasta]
        ajustado = {c: p * peso.get(c, 1.0) for c, p in bruto.items()}
        dominante = campos.get("categoria", pasta.parent.name)
        lista = assuntos_de(ajustado, dominante)
        contagem.update(lista)
        extras = [a for a in lista if a != dominante]
        if seco:
            if extras:
                print(f"  {campos.get('titulo', pasta.name)[:52]:52} "
                      f"{dominante} + {extras}")
            continue
        texto = ", ".join(lista)
        for md in capitulos:
            atual = _frontmatter(md.read_text(encoding="utf-8", errors="replace"))
            if atual.get("assuntos") == texto:
                continue
            processar._reescrever_frontmatter(md, {"assuntos": texto})
            mudou += 1
    print()
    print(f"{mudou} arquivos atualizados" + (" (seco)" if seco else ""))
    if contagem:
        print("documentos por assunto:")
        for assunto, n in contagem.most_common():
            print(f"  {n:3}  {assunto}")
    return mudou


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--seco", action="store_true")
    args = ap.parse_args()
    aplicar(args.raiz, seco=args.seco)
    return 0


if __name__ == "__main__":
    sys.exit(main())
