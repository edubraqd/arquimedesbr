"""Perfis de dominio: recorta o corpus antes da busca.

O corpus tem duas metades que competem no mesmo ranking: "estrutura de abertura
de mensagem **fria**" trazia o *cold start problem* de um livro de sistemas de
busca e um capitulo de prompt engineering de um livro de LLM. Recortar antes de
ranquear tira esse tipo de vizinho de perto.

Remedido em 10/09/2026 com o gabarito novo de **140 perguntas** contra o indice
inteiro -- 178 documentos, 210.526 passagens (`avaliar_dominio.py`; log em
`log-avaliacao-140q.txt`). Nao compare com as versoes anteriores deste
docstring: o gabarito tinha 53 perguntas e cresceu na mesma data.

| Metodo                          |    hit@1 |    hit@3 |   MRR | tempo |
|---------------------------------|----------|----------|-------|-------|
| BM25 bilingue                   |   19/140 |  112/140 | 0,480 |   2 s |
| BM25 + `--dominio`              |   50/140 |  116/140 | 0,605 |   3 s |
| BM25 + `--categoria`            |   97/140 |  129/140 | 0,816 |   3 s |
| semantico                       |   47/140 |   86/140 | 0,501 |  49 s |
| semantico + `--dominio`         |   51/140 |   88/140 | 0,531 |  24 s |
| semantico + `--categoria`       |   82/140 |  115/140 | 0,719 |   6 s |
| semantico + rerank              |   73/140 |  102/140 | 0,643 | 759 s |
| semantico + rerank + `--dominio`   | 77/140 |  108/140 | 0,679 |1324 s |
| semantico + rerank + `--categoria` |100/140 |  121/140 | 0,807 | ~570 s|

Tres leituras que importam, e a ultima muda o uso:

1. `--dominio` rende muito no BM25 (19 -> 50 acertos de primeira): busca lexical
   colide termo entre dominios com facilidade.
2. **No semantico ele quase nao rende** -- 47 -> 51 sem reranker, 73 -> 77 com.
   O embedding ja separa dominio sozinho; o que sobra de ruido vem de dentro do
   dominio, e para esse o remedio e `--categoria` (73 -> 100).
3. **A media acima soma dois comportamentos opostos.** Fatiado por dominio do
   alvo (`avaliar_por_estrato.py`, hit@1/hit@3):

   | corte                  | BM25+cat |  sem+cat | rerank+cat |
   |------------------------|----------|----------|------------|
   | comercial (56 livros)  |  33 / 50 |  37 / 48 |  **44 / 49** |
   | tecnico (74 papers)    |**58 / 69**| 41 / 59 |    50 / 64 |
   | pessoal (9)            |   6 / 9  |   4 / 7  |     6 / 8  |

   No livro o reranker paga; **no paper o BM25 bate o caminho caro, em 3 s
   contra ~570**. O `--dominio` deixou de ser so um filtro de ruido: ele agora
   diz **qual motor usar**.

Diluicao: de 77 para 102 documentos nada mudou; de 102 para 178 (+75%), medido
com o gabarito antigo de 53, o topo caiu de 44 para 42 no hit@1 e de 48 para 45
no hit@3 -- 9 das 9 linhas cairam ou empataram. Parte era artefato de pergunta
parada contra corpus crescendo; o gabarito de 140 corrige isso.
"""
from __future__ import annotations

import json
from pathlib import Path

# Cada categoria aparece em exatamente um dominio. `catalogar.ROTULOS` manda no
# nome das categorias; se uma nova entrar la e nao aqui, `validar()` acusa.
DOMINIOS: dict[str, tuple[str, ...]] = {
    # Escrever copy, preco, proposta, posicionamento, texto de UX.
    "comercial": (
        "vendas",
        "copy-persuasao",
        "posicionamento-negocio",
        "marketing",
        "ux-conversao",
        "ciencia-cognitiva",
        "mercado-setorial",
        "design-arte",
    ),
    # Decidir arquitetura, stack, modelo, metrica.
    "tecnico": (
        "python",
        "rust",
        "frontend",
        "engenharia-software",
        "ia-llm",
        "agentes-llm",
        "seguranca-llm",
        # entrou em 09/09/2026 com Gray Hat Hacking e Gray Hat Python
        "seguranca-ofensiva",
        "dados-ml",
        "matematica",
        "busca-recuperacao",
        # entrou em 13/09/2026 com os papers de ASR/Whisper
        "audio-fala",
    ),
    "pessoal": (
        "treino-endurance",
        # material de idioma: nao e comercial nem tecnico
        "idiomas",
        # entrou em 09/09/2026 com a leva de value investing (Graham, Klarman,
        # Munger). Nao e "comercial": nada disso serve para vender site nem PDV.
        "financas-investimentos",
    ),
}

NOME_CONFIG = "dominio.json"


def carregar(raiz: Path) -> dict[str, tuple[str, ...]]:
    """Le `dominio.json` se existir; senao devolve o mapa embutido.

    O arquivo serve para remanejar categoria sem editar codigo. Formato:
    `{"comercial": ["vendas", ...], "tecnico": [...]}` — substitui o dominio
    inteiro, nao faz merge, para nao existir estado meio-sobrescrito.

    Armadilha: tirar uma categoria do unico dominio que a continha **nao** a
    exclui da busca. Ela vira categoria sem dominio, e a regra de `categorias()`
    de nao sumir com documento a devolve para todos. Para separar de verdade,
    mova-a para outro dominio em vez de so apagar da lista.
    """
    config = raiz / NOME_CONFIG
    if not config.exists():
        return dict(DOMINIOS)
    bruto = json.loads(config.read_text(encoding="utf-8"))
    mapa = dict(DOMINIOS)
    for nome, categorias in bruto.items():
        mapa[nome] = tuple(categorias)
    return mapa


def categorias(raiz: Path, nome: str | None) -> set[str] | None:
    """Categorias permitidas para um dominio. `None` = sem restricao.

    Categoria que existe na base e nao esta em dominio nenhum (`geral`, ou uma
    criada depois deste arquivo) entra em **todos** os dominios. Some-la seria
    a pior falha possivel aqui: documento que voce acabou de adicionar e nao
    acha mais, sem erro nenhum na tela. `validar()` lista essas categorias para
    que sejam classificadas; ate la elas custam ruido, nao sumico.
    """
    if not nome:
        return None
    mapa = carregar(raiz)
    if nome not in mapa:
        conhecidos = ", ".join(sorted(mapa))
        raise SystemExit(f"dominio '{nome}' nao existe. use um de: {conhecidos}")
    mapeadas = {c for cats in mapa.values() for c in cats}
    existentes = {d.name for d in (raiz / "markdown").iterdir() if d.is_dir()}
    return set(mapa[nome]) | (existentes - mapeadas)


def de_categoria(raiz: Path, categoria: str) -> str | None:
    """Dominio ao qual a categoria pertence, ou None se nao mapeada."""
    for nome, cats in carregar(raiz).items():
        if categoria in cats:
            return nome
    return None


def validar(raiz: Path, todas: set[str]) -> list[str]:
    """Categorias que existem na base e nao caem em dominio nenhum."""
    mapeadas = {c for cats in carregar(raiz).values() for c in cats}
    return sorted(todas - mapeadas)


def adicionar_argumento(ap) -> None:
    """Registra `--dominio` num ArgumentParser, com a mesma ajuda nos dois CLIs."""
    ap.add_argument(
        "--dominio",
        choices=sorted(DOMINIOS),
        help="recorta o corpus antes de ranquear; corta ruido de fora do dominio, "
             "nao de dentro (para esse, --categoria)",
    )
