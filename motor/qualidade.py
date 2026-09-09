"""Idioma e utilidade de um trecho — deterministico, offline, sem dependencia.

Duas perguntas que a base precisava responder e nao respondia:

1. **Em que idioma esta este documento?** A base tem portugues, ingles, espanhol
   e frances misturados. Sem essa marca, quem consulta nao sabe em que idioma
   perguntar, e a busca lexica erra o alvo.
2. **Este capitulo vale alguma coisa?** Pagina de copyright, sumario, indice
   remissivo e pagina de venda ocupam lugar no indice, competem no ranking e
   custam tempo de embedding. Medido na base: sao ~1 em cada 8 capitulos.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

# ------------------------------------------------------------------- idioma

# Palavras funcionais sao a assinatura mais estavel de um idioma: aparecem em
# qualquer assunto e quase nao aparecem nos outros idiomas da lista.
MARCAS = {
    "pt": """de que nao para uma com os as dos das ele ela isso este esta muito
             quando entao voce nos seu sua pelo pela ate porque tambem ja mais
             sao esta estao fazer ser tem""",
    "es": """de que no para una con los las del ella eso este esta muy cuando
             entonces usted nosotros su por hasta porque tambien ya mas son
             estan hacer ser tiene pero""",
    "en": """the of and to in that is for with as was are this these from have
             has been will would there their which when what about into than""",
    "fr": """le la les des une pour avec dans que qui est sont ete plus cette
             ces vous nous leur mais comme sur par tout meme aussi ou donc""",
    "it": """il lo la gli che non per una con del della sono stato questo questa
             molto quando anche piu essere hanno come sul nella""",
    "de": """der die das und nicht fur mit von den dem ein eine ist sind war
             auch wenn dann sich uber aber nach durch werden"""
,
    "id": """yang dan untuk dengan tidak ini itu dari pada adalah akan saya kita
             mereka bisa juga karena atau dalam sebagai lebih sudah""",
}
MARCAS = {k: set(v.split()) for k, v in MARCAS.items()}

_PALAVRA = re.compile(r"[a-z]+")


def _plano(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return texto.encode("ascii", "ignore").decode("ascii")


def detectar_idioma(texto: str, amostra: int = 40000):
    """Devolve (codigo, confianca 0..1). 'xx' quando nao da para dizer."""
    palavras = _PALAVRA.findall(_plano(texto[:amostra]))
    if len(palavras) < 50:
        return "xx", 0.0
    contagem = Counter(palavras)
    placar = {
        idioma: sum(contagem[p] for p in marcas) for idioma, marcas in MARCAS.items()
    }
    total = sum(placar.values())
    if not total:
        return "xx", 0.0
    melhor = max(placar, key=placar.get)
    segundo = sorted(placar.values())[-2] if len(placar) > 1 else 0
    confianca = (placar[melhor] - segundo) / placar[melhor] if placar[melhor] else 0.0
    if placar[melhor] / len(palavras) < 0.04:   # nem parece texto corrido
        return "xx", 0.0
    return melhor, round(confianca, 2)


# ------------------------------------------------------ tipo do documento

# Uma faceta separada da categoria: "vendas" diz do que trata, `tipo` diz que
# genero de texto e. Importa na hora de citar (tese tem autor, instituicao e ano;
# manual de equipamento nao e fonte de argumento) e permite filtrar a busca por
# material revisado quando o assunto exige rigor.
_MARCAS_TIPO = (
    ("tese", (
        "bachelors thesis", "master's thesis", "masters thesis", "phd thesis",
        "doctoral dissertation", "submitted in partial fulfillment",
        "projeto de graduacao", "trabalho de conclusao de curso",
        "dissertacao apresentada", "tese apresentada", "orientador:",
        "universidade federal", "escola politecnica", "in partial fulfillment",
    )),
    ("paper", (
        "abstract—", "keywords:", "palavras-chave:", "doi:", "arxiv:",
        "we propose", "in this paper", "neste artigo", "related work",
    )),
    ("manual", (
        "manual do usuario", "manual de produto", "manual de instalacao",
        "user manual", "getting started manual", "guia de instalacao",
        "especificacoes tecnicas", "rev.", "revisao tecnica",
    )),
    ("apostila", (
        "apostila", "material do aluno", "caderno de exercicios",
        "curso de formacao", "modulo 1", "aula 1",
    )),
)


def detectar_tipo(titulo: str, amostra: str) -> str:
    """livro (padrao) | tese | paper | manual | apostila.

    Le so o comeco do documento: rosto, ficha e resumo, que e onde o genero se
    declara. Exige duas marcas para tese e paper — uma so ("orientador:" numa
    citacao, por exemplo) nao basta.
    """
    texto = _plano(titulo + "\n" + amostra[:12000])
    for tipo, marcas in _MARCAS_TIPO:
        achadas = sum(1 for m in marcas if _plano(m) in texto)
        if achadas >= (2 if tipo in ("tese", "paper") else 1):
            return tipo
    return "livro"


# ------------------------------------------------------- capitulo sem valor

_TITULOS_LIXO = re.compile(
    r"^\W*("
    r"copyright|creditos|cr[eé]ditos|about this ebook|sobre este|dedicat|dedicac|"
    r"acknowledg|agradecim|table of contents|contents|sumario|sum[áa]rio|indice|"
    r"[ií]ndice|index|bibliograf|references|refer[eê]ncias|colophon|"
    r"ficha catalografica|isbn|page de titre|title page|half title|"
    r"series editor foreword|foreword|epigraph|errata|notas de rodape|"
    r"advance praise|praise for|what people are saying|elogios|"
    r"sobre o autor|about the author|acerca del autor|nota do tradutor"
    # sem \b no fim: as entradas sao prefixos de proposito ("bibliograf" tem de
    # pegar "Bibliografia", "acknowledg" tem de pegar "Acknowledgements")
    r")",
    re.IGNORECASE,
)

# marcadores de PDF que nao e o livro: pagina de venda, capa de curso pirata
_MARCAS_VENDA = (
    "testbank", "test bank", "solutions manual", "instant download",
    "available formats", "how to access product", "add to cart",
    "digital instant download", "ebook pdf download",
)


def titulo_e_lixo(titulo: str) -> bool:
    return bool(_TITULOS_LIXO.match(titulo.strip()))


def avaliar(titulo: str, md: str):
    """Devolve (util: bool, motivo: str). Motivo vazio quando util."""
    if titulo_e_lixo(titulo):
        return False, "secao de apoio (copyright, sumario, indice, referencias)"

    corpo = md.strip()
    palavras = corpo.split()
    if len(palavras) < 120:
        return False, f"curto demais ({len(palavras)} palavras)"

    baixo = corpo.lower()
    achadas = [m for m in _MARCAS_VENDA if m in baixo]
    if achadas:
        return False, "pagina de venda, nao conteudo (" + ", ".join(achadas[:2]) + ")"

    # sumario com pontilhado ("Hierarquia e tudo . . . . . 54"): a regra por
    # linha nao pega, porque a extracao junta tudo num paragrafo so.
    #
    # Contar os pontilhados NAO basta, e isso custou caro: em 09/09/2026 a
    # contagem >= 12 jogou 23 dos 34 capitulos de Security Analysis (735 pag.,
    # 264 mil palavras) para fora da busca. O livro e cheio de tabela
    # financeira, e o OCR transforma o pontilhado de cada linha de tabela num
    # run de pontos -- dentro de prosa legitima sobre bonds e depreciacao.
    #
    # O que separa sumario de conteudo e a FRACAO do texto que os pontos comem,
    # nao quantos existem. Medido nos 27 capitulos que a regra antiga pegou:
    # sumario de verdade fica em 15,8% a 48,7%; capitulo de conteudo com tabela
    # nao passa de 5,5%. O corte em 10% cai no meio desse vao.
    pontilhados = re.findall(r"(?:\.\s*){4,}", corpo)
    if len(pontilhados) >= 12 and corpo:
        fatia = sum(len(p) for p in pontilhados) / len(corpo)
        if fatia >= 0.10:
            return False, f"sumario (pontilhado ocupa {fatia:.0%} do texto)"

    # indice remissivo e sumario disfarcados: muita linha curta terminando em numero
    linhas = [ln.strip() for ln in corpo.splitlines() if ln.strip()]
    if linhas:
        com_numero = sum(
            1 for ln in linhas if len(ln) < 90 and re.search(r"[\.\s]\d{1,4}$", ln)
        )
        if com_numero / len(linhas) > 0.45:
            return False, "parece sumario ou indice remissivo"

    # tabela de numeros (tabela de conversao, planilha impressa): a variedade de
    # tokens e alta, entao a regra de vocabulario degenerado nao pega, mas para
    # busca por conceito nao vale nada
    numericos = sum(1 for p in palavras if re.fullmatch(r"[\d.,:%/-]+", p))
    if numericos / len(palavras) > 0.5:
        return False, f"tabela de numeros ({numericos * 100 // len(palavras)}% do texto)"

    # texto degenerado: pouca variedade de palavra
    unicas = len({p.lower() for p in palavras})
    if unicas / len(palavras) < 0.08:
        return False, f"vocabulario degenerado ({unicas} palavras unicas)"

    return True, ""
