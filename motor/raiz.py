"""Onde fica a base / Where the library lives.

A raiz e a pasta que guarda `nao-processado/`, `markdown/`, `manifesto.json` e
os indices. Ela NAO vive dentro deste repositorio: o repositorio e o motor, a
raiz e o acervo de quem usa.

Ordem de resolucao:

1. `--raiz <caminho>` na linha de comando (todos os scripts aceitam);
2. variavel de ambiente `ARQUIMEDES_RAIZ`;
3. `~/Arquimedes`.

---

The root is the folder holding `nao-processado/`, `markdown/`, `manifesto.json`
and the indexes. It does NOT live inside this repository: the repo is the
engine, the root is the user's own library.

Resolution order:

1. `--raiz <path>` on the command line (every script accepts it);
2. `ARQUIMEDES_RAIZ` environment variable;
3. `~/Arquimedes`.
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV = "ARQUIMEDES_RAIZ"


def raiz_padrao() -> Path:
    bruto = os.environ.get(_ENV, "").strip()
    if bruto:
        return Path(bruto).expanduser()
    return Path.home() / "Arquimedes"


RAIZ_PADRAO = raiz_padrao()
