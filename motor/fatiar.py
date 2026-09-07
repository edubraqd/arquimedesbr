"""Fatiamento do documento em capitulos legiveis por agente.

Prioridade: sumario (bookmarks) do proprio PDF > titulos detectados no texto >
corte por tamanho. Capitulo curto demais gruda no anterior; capitulo longo
demais vira "parte 1/2/3", sempre cortando em fronteira de paragrafo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ALVO_PALAVRAS = 8000       # tamanho de conforto por arquivo
MAX_PALAVRAS = 12000       # acima disso o capitulo e dividido em partes
MIN_PALAVRAS = 400         # abaixo disso gruda no capitulo anterior

_PADRAO_CAPITULO = re.compile(
    r"^#{2,3}\s+("
    r"(cap[ií]tulo|chapter|cap[ií]tulo|parte|part|se[cç][aã]o|section|lesson|li[cç][aã]o|"
    r"ap[eê]ndice|appendix|introdu[cç][aã]o|introduction|conclus[aã]o|conclusion|"
    r"pr[oó]logo|prologue|ep[ií]logo|epilogue)\b"
    r"|\d{1,2}[\.\):]\s+\S"
    r")",
    re.IGNORECASE,
)


@dataclass
class Capitulo:
    ordem: int
    titulo: str
    md: str
    pagina_inicial: int
    pagina_final: int

    @property
    def palavras(self) -> int:
        return len(self.md.split())


def slug(texto: str, limite: int = 60) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = texto.encode("ascii", "ignore").decode("ascii").lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return (texto[:limite].rstrip("-")) or "sem-titulo"


# --------------------------------------------------------------- pelo sumario


PAGINAS_IDEAIS = 22  # tamanho de capitulo que costuma virar um arquivo legivel


def _nivel_util(toc: list, total_paginas: int) -> int | None:
    """Escolhe o nivel do sumario cujo corte chega mais perto de um capitulo.

    Nivel 1 sozinho e ruim em livro dividido em "partes": tres entradas para
    700 paginas. O criterio e a media de paginas por corte, nao a profundidade.
    """
    por_nivel = {}
    for nivel, _titulo, pagina in toc:
        if pagina and pagina > 0:
            por_nivel.setdefault(nivel, []).append(pagina)
    candidatos = []
    for nivel, paginas in por_nivel.items():
        n = len(set(paginas))
        if n < 3 or n > 300:
            continue
        media = total_paginas / n
        if media < 2:
            continue
        candidatos.append((abs(media - PAGINAS_IDEAIS), nivel))
    if not candidatos:
        return None
    return min(candidatos)[1]


def _cortes_do_toc(toc: list, total_paginas: int):
    nivel = _nivel_util(toc, total_paginas)
    if nivel is None:
        return None
    cortes = []
    for lvl, titulo, pagina in toc:
        if lvl != nivel or not pagina or pagina < 1:
            continue
        titulo = re.sub(r"\s+", " ", titulo).strip()
        if not titulo:
            continue
        if cortes and pagina <= cortes[-1][0]:
            # dois titulos na mesma pagina: um so corte, titulo composto
            if titulo not in cortes[-1][1]:
                cortes[-1] = (cortes[-1][0], cortes[-1][1] + " / " + titulo)
            continue
        cortes.append((min(pagina, total_paginas), titulo))
    return cortes or None


# ------------------------------------------------------------- pelos titulos


def _cortes_do_texto(paginas):
    cortes = []
    for p in paginas:
        for linha in p.md.split("\n"):
            if _PADRAO_CAPITULO.match(linha.strip()):
                titulo = linha.lstrip("#").strip()
                if cortes and cortes[-1][0] == p.numero:
                    continue
                cortes.append((p.numero, titulo))
                break
    return cortes if len(cortes) >= 3 else None


# ----------------------------------------------------------------- montagem


def _juntar(paginas, ini: int, fim: int) -> str:
    pedacos = [p.md.strip() for p in paginas if ini <= p.numero <= fim and p.md.strip()]
    return "\n\n".join(pedacos)


def _dividir_por_tamanho(md: str, alvo: int) -> list:
    paragrafos = [p for p in md.split("\n\n") if p.strip()]
    partes, atual, contador = [], [], 0
    for par in paragrafos:
        n = len(par.split())
        if contador and contador + n > alvo:
            partes.append("\n\n".join(atual))
            atual, contador = [], 0
        atual.append(par)
        contador += n
    if atual:
        partes.append("\n\n".join(atual))
    return partes or [md]


def fatiar(doc) -> list:
    paginas = doc.paginas
    if not paginas:
        return []
    total_paginas = paginas[-1].numero

    cortes = _cortes_do_toc(doc.toc, total_paginas) if doc.toc else None
    if not cortes and getattr(doc, "aberturas", None):
        # PDF sem sumario: usa os inicios de capitulo achados pelo tamanho da fonte
        achados = sorted(doc.aberturas.items())
        if len(achados) >= 3:
            cortes = [(pagina, titulo) for pagina, titulo in achados]
    if not cortes:
        cortes = _cortes_do_texto(paginas)

    brutos = []
    if cortes:
        if cortes[0][0] > 1:
            cortes.insert(0, (1, "Abertura"))
        for i, (pagina, titulo) in enumerate(cortes):
            fim = cortes[i + 1][0] - 1 if i + 1 < len(cortes) else total_paginas
            if fim < pagina:
                fim = pagina
            md = _juntar(paginas, pagina, fim)
            if md.strip():
                brutos.append({"titulo": titulo, "md": md, "ini": pagina, "fim": fim})
    else:
        # Sem sumario, cortar por pagina e nao pelo texto ja juntado: assim cada
        # trecho guarda a faixa real de paginas. Antes todos saiam como "1-121",
        # o que torna a citacao inutil.
        atual, contador, i = [], 0, 1
        for pagina in paginas:
            if not pagina.md.strip():
                continue
            if contador and contador + pagina.palavras > ALVO_PALAVRAS:
                brutos.append({
                    "titulo": f"Trecho {i}", "md": "\n\n".join(p.md for p in atual),
                    "ini": atual[0].numero, "fim": atual[-1].numero,
                })
                atual, contador, i = [], 0, i + 1
            atual.append(pagina)
            contador += pagina.palavras
        if atual:
            brutos.append({
                "titulo": f"Trecho {i}", "md": "\n\n".join(p.md for p in atual),
                "ini": atual[0].numero, "fim": atual[-1].numero,
            })

    # capitulo curto demais gruda no anterior
    compactados = []
    for b in brutos:
        if compactados and len(b["md"].split()) < MIN_PALAVRAS:
            ant = compactados[-1]
            ant["md"] = ant["md"] + "\n\n## " + b["titulo"] + "\n\n" + b["md"]
            ant["fim"] = b["fim"]
        else:
            compactados.append(b)

    # capitulo longo demais vira partes
    capitulos = []
    ordem = 1
    for b in compactados:
        if len(b["md"].split()) > MAX_PALAVRAS:
            partes = _dividir_por_tamanho(b["md"], ALVO_PALAVRAS)
            for i, parte in enumerate(partes, 1):
                capitulos.append(
                    Capitulo(
                        ordem=ordem,
                        titulo=f"{b['titulo']} (parte {i}/{len(partes)})",
                        md=parte,
                        pagina_inicial=b["ini"],
                        pagina_final=b["fim"],
                    )
                )
                ordem += 1
        else:
            capitulos.append(
                Capitulo(
                    ordem=ordem,
                    titulo=b["titulo"],
                    md=b["md"],
                    pagina_inicial=b["ini"],
                    pagina_final=b["fim"],
                )
            )
            ordem += 1
    return capitulos
