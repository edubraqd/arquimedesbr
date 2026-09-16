#!/usr/bin/env python3
"""Traz o motor da base local para este repositorio.

Existem duas copias do motor: a que roda na base do autor (com o caminho da
base cravado) e a publicada aqui (com a raiz vindo de `raiz.py`). Corrigir uma
nao propaga para a outra. Este script faz a passagem, sempre no mesmo sentido:

    base local  ->  repositorio

e reaplica as tres generalizacoes que a copia publicada precisa:

1. `RAIZ_PADRAO = Path(r"D:\\BaseConhecimento")` vira `from raiz import ...`;
2. caminhos absolutos citados em texto de ajuda viram `<raiz>`;
3. `gabarito.py` ganha o aviso de que e um gabarito de exemplo, amarrado a uma
   estante especifica, e `dominio.py` perde a referencia a um projeto privado.

Uso:

    python sincronizar.py --de D:/BaseConhecimento/motor
    python sincronizar.py --de D:/BaseConhecimento/motor --seco
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DESTINO = AQUI / "motor"

# raiz.py e daqui, nao da base: nunca deve ser sobrescrito nem esperado la
SO_DO_REPO = {"raiz.py", "__init__.py"}

CABECALHO_GABARITO = '''"""Gabarito de avaliacao da busca: pergunta -> documentos que deveriam responder.

ESTE E UM GABARITO DE EXEMPLO. As perguntas abaixo apontam para os livros de
UMA base especifica -- a que gerou os numeros do README. Se os seus livros forem
outros, os alvos nao existem e o avaliador vai medir zero.

Para medir a SUA base: troque `PERGUNTAS` por perguntas suas, cada uma com os
pedacos do nome da pasta do documento que deveria responder. Depois rode
`avaliar_dominio.py`. E para isso que o avaliador vem junto.

---

THIS IS AN EXAMPLE GROUND TRUTH. The questions below point at the books of ONE
specific library -- the one that produced the README numbers. With a different
shelf the targets do not exist and the evaluator will score zero.

To measure YOUR library: replace `PERGUNTAS` with your own questions, each with
the fragments of the target document folder name. Then run `avaliar_dominio.py`.
'''

TROCAS_TEXTO = [
    ('RAIZ_PADRAO = Path(r"D:\\BaseConhecimento")',
     "from raiz import RAIZ_PADRAO  # noqa: E402"),
    ('RAIZ = Path(r"D:\\BaseConhecimento")',
     "from raiz import RAIZ_PADRAO as RAIZ  # noqa: E402"),
    ("D:/BaseConhecimento/motor/", ""),
    ("D:/BaseConhecimento", "<raiz>"),
    ("D:\\BaseConhecimento", "<raiz>"),
]

# trechos que citam projeto privado do autor e nao dizem nada a quem le de fora
TROCAS_PRIVADAS = [
    ("no motor do Motor 2mil. O que estava errado era misturar os dois na mesma\n"
     "consulta, nao ter os dois na base.",
     "no codigo dos proprios projetos. O que estava errado era misturar os dois na\n"
     "mesma consulta, nao ter os dois na base."),
    ("- a pergunta e escrita como o Eduardo perguntaria, em portugues, sem usar o\n"
     "  vocabulario exato do livro (senao vira teste de casamento de string);",
     "- a pergunta e escrita como o dono da base perguntaria, em linguagem natural,\n"
     "  sem usar o vocabulario exato do livro (senao vira teste de casamento de string);"),
]

ABERTURA_GABARITO = ('"""Gabarito de avaliacao da busca: '
                     'pergunta -> documentos que deveriam responder.\n')


def generalizar(nome: str, texto: str) -> tuple[str, list[str]]:
    aplicadas = []
    for velho, novo in TROCAS_TEXTO + TROCAS_PRIVADAS:
        if velho in texto:
            texto = texto.replace(velho, novo)
            aplicadas.append(velho.splitlines()[0][:48])
    if nome == "gabarito.py" and ABERTURA_GABARITO in texto:
        texto = texto.replace(ABERTURA_GABARITO, CABECALHO_GABARITO, 1)
        aplicadas.append("aviso de gabarito de exemplo")
    return texto, aplicadas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--de", type=Path, required=True,
                    help="pasta motor/ da base local")
    ap.add_argument("--seco", action="store_true", help="so mostra o que faria")
    args = ap.parse_args()

    origem = args.de.expanduser().resolve()
    if not origem.is_dir():
        print(f"erro: {origem} nao existe")
        return 1

    mudados, iguais, sobras = [], 0, []
    for f in sorted(origem.glob("*.py")):
        if ".bak" in f.name or f.name in SO_DO_REPO:
            continue
        texto, aplicadas = generalizar(f.name, f.read_text(encoding="utf-8"))
        alvo = DESTINO / f.name
        atual = alvo.read_text(encoding="utf-8") if alvo.exists() else None
        if atual == texto:
            iguais += 1
            continue
        mudados.append((f.name, "novo" if atual is None else "atualizado", aplicadas))
        if not args.seco:
            alvo.write_text(texto, encoding="utf-8")

    # o recorte de categoria por agente das 140 perguntas do gabarito de exemplo:
    # sem ele o avaliar_consultar.py para. Nao e livro, pode vir.
    for nome in ("categorias_agente.json",):
        f = origem / nome
        if f.exists():
            alvo = DESTINO / nome
            if not alvo.exists() or alvo.read_bytes() != f.read_bytes():
                mudados.append((nome, "novo" if not alvo.exists() else "atualizado", []))
                if not args.seco:
                    shutil.copyfile(f, alvo)
            else:
                iguais += 1

    for f in sorted(DESTINO.glob("*.py")):
        if f.name in SO_DO_REPO:
            continue
        if not (origem / f.name).exists():
            sobras.append(f.name)

    for nome, estado, aplicadas in mudados:
        print(f"  {estado:<11} {nome}")
        for a in aplicadas:
            print(f"                 generalizado: {a}")
    print(f"\n{len(mudados)} arquivo(s) mudado(s), {iguais} ja igual(is)")
    if sobras:
        print("\nno repositorio e nao na base (confira se ainda fazem sentido):")
        for nome in sobras:
            print(f"  {nome}")
    if args.seco:
        print("\n(seco: nada escrito)")
    else:
        print("\nConfira antes de subir:")
        print(f"  cd {DESTINO} && python -m unittest test_motor")
        print(f"  cd {AQUI} && git diff --stat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
