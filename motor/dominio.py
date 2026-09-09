"""Perfis de dominio: recorta o corpus antes da busca.

O corpus tem duas metades que competem no mesmo ranking: "estrutura de abertura
de mensagem **fria**" trazia o *cold start problem* de um livro de sistemas de
busca e um capitulo de prompt engineering de um livro de LLM. Recortar antes de
ranquear tira esse tipo de vizinho de perto.

Medido em 07/09/2026 com as 53 perguntas do `gabarito.py` contra o indice
inteiro, no nivel de documento (`avaliar_dominio.py`):

| Metodo                          | hit@1 | hit@3 |   MRR |
|---------------------------------|-------|-------|-------|
| BM25 bilingue                   |  8/53 | 39/53 | 0,456 |
| BM25 + `--dominio`              | 16/53 | 42/53 | 0,547 |
| BM25 + `--categoria`            | 32/53 | 47/53 | 0,746 |
| semantico                       | 20/53 | 34/53 | 0,543 |
| semantico + `--dominio`         | 21/53 | 36/53 | 0,567 |
| semantico + `--categoria`       | 37/53 | 46/53 | 0,806 |
| semantico + rerank              | 29/53 | 41/53 | 0,669 |
| semantico + rerank + `--dominio`   | 32/53 | 43/53 | 0,710 |
| semantico + rerank + `--categoria` | 43/53 | 48/53 | 0,869 |

Duas leituras que importam, e a segunda incomoda:

1. `--dominio` rende muito no BM25 (8 -> 16 acertos de primeira): busca lexical
   colide termo entre dominios com facilidade.
2. **No semantico ele quase nao rende** — 20 -> 21 sem reranker, 29 -> 32 com.
   O embedding ja separa dominio sozinho; o que sobra de ruido vem de dentro do
   dominio, e para esse o remedio e `--categoria` (29 -> 43).

Por isso `comercial` e `tecnico` existem separados em vez de a base ter sido
podada: python, rust e ML nao servem para escrever copy, mas servem para mexer
no codigo dos proprios projetos. O que estava errado era misturar os dois na
mesma consulta, nao ter os dois na base.

Os numeros acima usam o dominio e a categoria **do alvo**, entao sao teto: medem
o ganho de quem escolhe o recorte certo. Errar dominio e dificil; errar
categoria e facil, e nao esta medido aqui.

Sem `--dominio` nada muda: a busca continua varrendo tudo.
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
        "dados-ml",
        "matematica",
        "busca-recuperacao",
    ),
    "pessoal": (
        "treino-endurance",
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
