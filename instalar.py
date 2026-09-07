#!/usr/bin/env python3
"""Instalador do arquimedesbr / arquimedesbr installer.

Nao faz nada esperto: cria as pastas da base e copia a skill.
Does nothing clever: creates the library folders and copies the skill.

    python instalar.py
    python instalar.py --raiz /mnt/hd/MinhaBase
    python instalar.py --sem-skill
    python instalar.py --seco
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent

PASTAS = (
    "nao-processado",
    "processado",
    "falhas",
    "removidos",
    "markdown",
)

LEIA_ME_DA_FILA = """Jogue aqui os PDF / DOCX / TXT / MD que quer na base,
depois rode:

    cd {motor}
    python processar.py

---

Drop the PDF / DOCX / TXT / MD files you want in the library here, then run:

    cd {motor}
    python processar.py
"""


def resolver_raiz(argumento: str | None) -> Path:
    if argumento:
        return Path(argumento).expanduser().resolve()
    do_ambiente = os.environ.get("ARQUIMEDES_RAIZ", "").strip()
    if do_ambiente:
        return Path(do_ambiente).expanduser().resolve()
    return (Path.home() / "Arquimedes").resolve()


def pasta_de_skills() -> Path:
    return Path.home() / ".claude" / "skills" / "arquimedesbr"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", help="onde a base vai morar / where the library lives")
    ap.add_argument("--sem-skill", action="store_true",
                    help="nao instalar a skill do Claude Code / skip the skill")
    ap.add_argument("--seco", action="store_true",
                    help="so mostra o que faria / dry run")
    args = ap.parse_args()

    raiz = resolver_raiz(args.raiz)
    seco = "[seco] " if args.seco else ""

    print(f"raiz / root: {raiz}")
    for nome in PASTAS:
        alvo = raiz / nome
        if alvo.exists():
            print(f"  ja existe / exists   {nome}/")
            continue
        print(f"  {seco}criando / creating  {nome}/")
        if not args.seco:
            alvo.mkdir(parents=True, exist_ok=True)

    # fora da fila: qualquer arquivo dentro de nao-processado/ seria ingerido.
    aviso = raiz / "COMO-USAR.txt"
    if not args.seco and aviso.parent.exists() and not aviso.exists():
        aviso.write_text(LEIA_ME_DA_FILA.format(motor=AQUI / "motor"), encoding="utf-8")

    if not args.sem_skill:
        destino = pasta_de_skills()
        origem = AQUI / "skill" / "SKILL.md"
        print(f"\nskill: {destino / 'SKILL.md'}")
        if not origem.exists():
            print("  !! skill/SKILL.md nao encontrado / not found")
        elif args.seco:
            print(f"  {seco}copiaria / would copy")
        else:
            destino.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, destino / "SKILL.md")
            print("  copiada / copied")

    print("\nProximo passo / next step:")
    if not os.environ.get("ARQUIMEDES_RAIZ"):
        print(f'  export ARQUIMEDES_RAIZ="{raiz}"        # bash/zsh')
        print(f'  $env:ARQUIMEDES_RAIZ = "{raiz}"        # PowerShell')
    print(f"  pip install -r {AQUI / 'requirements.txt'}")
    print(f"  copie um PDF para {raiz / 'nao-processado'} / copy a PDF there")
    print(f"  cd {AQUI / 'motor'} && python processar.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
