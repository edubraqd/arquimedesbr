"""Classificacao, frontmatter e indices da base.

Tudo deterministico: nenhuma categoria e inventada por LLM, o que mantem o
indice estavel entre execucoes.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import qualidade
from fatiar import slug

# categoria -> (rotulo legivel, termos de busca)
CATEGORIAS = {
    "vendas": (
        "Vendas e prospeccao",
        ["spin selling", "gap selling", "prospecting", "prospeccao", "predictable revenue",
         "never split", "negotiation", "negociacao", "negotiating", "counterpart",
         "cold call", "objection", "objecao", "pipeline", "quota", "sdr", "closing",
         "vendedor", "discovery call", "outbound"],
    ),
    "copy-persuasao": (
        "Copywriting e persuasao",
        ["copywriter", "copywriting", "persuasion", "persuasao", "cialdini", "influence",
         "storybrand", "story brand", "headline", "manipulation", "evil by design",
         "landing copy", "call to action", "swipe"],
    ),
    "posicionamento-negocio": (
        "Posicionamento, precificacao e modelo de negocio",
        ["positioning", "posicionamento", "obviously awesome", "expertise", "pricing",
         "precificacao", "billable hour", "subscription", "automatic customer",
         "luxury strategy", "personal brand", "marca pessoal", "mom test", "blueprint",
         "niche", "nicho", "proposal", "retainer", "alchemy", "sutherland",
         "grand slam offer", "oferta irresistivel", "value equation",
         "hormozi", "montar a oferta", "equacao de valor"],
    ),
    "marketing": (
        "Marketing, conteudo e marca",
        ["marketing de conteudo", "content marketing", "biblia do marketing",
         "inbound", "branding", "midia social", "social media", "seo",
         "audiencia", "funil de marketing", "campanha", "neuromarketing",
         "canal de aquisicao", "acquisition channel", "bullseye framework",
         "traction", "viral marketing", "search engine marketing", "afiliado",
         "growth", "aquisicao de clientes",
         "neurovendas", "publicidade", "anuncio", "engajamento", "instagram", "tiktok", "influenciador",
         "rede social", "midia paga"],
    ),
    "ux-conversao": (
        "UX, usabilidade e conversao",
        ["usability", "usabilidade", "dont make me think", "don't make me think",
         "conversion rate", "cro", "wireframe", "a/b test", "landing page",
         "making websites win", "heatmap", "funnel", "funil",
         "gamification", "gamificacao", "gameful", "game mechanics",
         "leaderboard", "badges", "engagement loop", "player type"],
    ),
    "engenharia-software": (
        "Engenharia de software",
        ["software engineering", "refactoring", "clean code", "unit test", "tdd",
         "continuous delivery", "code that fits", "checklist", "complexity",
         "arquitetura de software", "legacy code", "pull request",
         "pragmatic programmer", "programador pragmatico", "dry principle",
         "domain driven", "hexagonal", "code review"],
    ),
    "frontend": (
        "Frontend e React",
        ["react", "jsx", "usestate", "useeffect", "component", "hooks", "typescript",
         "css", "javascript", "next.js", "vite"],
    ),
    "python": (
        "Python",
        # termos especificos de proposito: "python" solto aparece em livro de ML
        # e de dados, e roubaria documento que nao e sobre a linguagem
        ["pense em python", "python para todos", "web scraping", "beautifulsoup",
         "linguagem python", "python 3", "pandas", "jupyter", "pip install",
         "list comprehension", "fluent python", "architecture patterns with python",
         "dunder", "asyncio", "decorador", "generador"],
    ),
    "rust": (
        "Rust",
        # termos que so existem em Rust. Palavra solta trai: "ownership" e o
        # Core Drive 4 do Actionable Gamification, e "cargo" e portugues comum —
        # cada uma mandou um livro errado para ca
        ["rust", "cargo build", "cargo run", "crates.io", "borrow checker",
         "actix", "tokio", "rustc", "linguagem de programacao rust",
         "impl trait", "lifetime", "unsafe rust", "match arm"],
    ),
    "ia-llm": (
        "IA aplicada e LLM",
        ["large language model", "llm", "prompt", "gpt", "transformer", "embedding",
         "rag", "fine-tuning", "chatbot", "artificial intelligence", "inteligencia artificial",
         "ai engineering", "agent", "token"],
    ),
    "agentes-llm": (
        "Agentes LLM, harness e ferramentas",
        # separado de ia-llm de proposito: os termos genericos de LLM ("llm",
        # "prompt", "token") aparecem em todo livro de IA e nao distinguem nada.
        # O que distingue este material e a camada em volta do modelo — harness,
        # loop, ferramenta, skill, memoria persistente — que e justamente onde
        # os documentos pos-2026 vivem e os livros de 2023 nao chegam.
        ["agent harness", "harness", "agentic", "coding agent", "tool calling",
         "tool call", "tool use", "model context protocol", "mcp server", "mcp",
         "claude code", "cursor", "skill library", "agent skill", "skills",
         "multi-agent", "agent loop", "long-horizon", "autonomous agent",
         "trajectory", "scaffold", "persistent memory", "agent memory",
         "terminal agent", "plugin marketplace", "self-improving agent",
         "context engineering", "tool response", "agente autonomo"],
    ),
    "seguranca-ofensiva": (
        "Seguranca ofensiva e engenharia reversa",
        # separado de seguranca-llm: aquela categoria carrega termos genericos
        # ("seguranca", "vulnerability", "malicious") que puxariam livro de
        # exploit para dentro dela e furariam a estreiteza que a faz render.
        # Aqui so entra o que nao existe fora de seguranca de binario e rede.
        ["buffer overflow", "shellcode", "fuzzing", "fuzzer", "engenharia reversa",
         "reverse engineering", "exploit development", "desenvolvimento de exploit",
         "penetration testing", "teste de invasao", "pentest", "metasploit",
         "disassembly", "disassembler", "rootkit", "gray hat", "grey hat",
         "ethical hacking", "hacking com python", "privilege escalation",
         "escalonamento de privilegio", "heap spray", "ida pro", "nmap",
         "wireshark", "packet sniffer", "sql injection", "cross-site scripting",
         "hacking with python", "python hacking", "ethical hacker", "kali linux",
         "brute force", "keylogger", "port scanner"],
    ),
    "seguranca-llm": (
        "Seguranca de LLM e agentes",
        # separado de ia-llm porque o balde generico de IA passou de 30
        # documentos e deixou de filtrar. Medido em 07/09: `--categoria` e a
        # maior alavanca da busca, e ela so vale enquanto a categoria e estreita.
        ["prompt injection", "injecao de prompt", "jailbreak", "adversarial",
         "exfiltration", "exfiltracao", "threat model", "attack surface",
         "superficie de ataque", "red team", "guardrail", "sandbox escape",
         "data poisoning", "model extraction", "trust attack", "seguranca",
         "vulnerability", "vulnerabilidade", "malicious"],
    ),
    "busca-recuperacao": (
        "Busca e recuperacao de informacao",
        # o assunto do proprio motor desta base: sai de dados-ml para nao ficar
        # diluido entre bandit, big data e previsao
        ["information retrieval", "recuperacao de informacao", "bm25",
         "inverted index", "indice invertido", "relevance ranking", "ranking",
         "query expansion", "reranking", "rerank", "cross-encoder",
         "learning to rank", "ndcg", "precision recall", "search engine",
         "motor de busca", "vector search", "busca semantica", "tf-idf",
         "hybrid search", "embeddings retrieval"],
    ),
    "dados-ml": (
        "Dados, ML e estatistica",
        ["machine learning", "data science", "forecasting", "regression", "big data",
         "data mining", "bandit", "clustering", "time series", "serie temporal",
         "probability", "modelo preditivo", "feature", "dataset"],
    ),
    "financas-investimentos": (
        "Financas e investimentos",
        # "value investing" e a marca do nicho; "acoes"/"bolsa" sozinhos traem
        # (acao tambem e acao de codigo), entao vem sempre com par financeiro
        ["value investing", "margin of safety", "security analysis", "graham",
         "warren buffett", "charlie munger", "berkshire", "intrinsic value",
         "valor intrinseco", "bolsa de valores", "mercado financeiro", "renda fixa",
         "acionista", "dividendo", "dividend", "portfolio de investimento",
         "carteira de acoes", "balanco patrimonial", "demonstracao financeira",
         "fluxo de caixa descontado", "price-earnings", "investidor", "investing",
         "hedge fund", "wall street", "tesouro direto", "cdb", "juros compostos"],
    ),
    "ciencia-cognitiva": (
        "Ciencia cognitiva e comportamento",
        ["neuroscience", "neurociencia", "cognitive", "social brain", "dunbar",
         "behaviour", "comportamento", "empathy", "psychology", "habito", "habit", "hipnose", "hypnosis",
         "smartphone use", "screen time", "attention span", "kahneman", "vies cognitivo"],
    ),
    "treino-endurance": (
        "Treino e nutricao esportiva",
        ["training bible", "power meter", "cycling", "ciclismo", "vo2", "ftp",
         "endurance", "nutrition", "diet", "dieta", "watts", "periodizacao", "interval"],
    ),
    "design-arte": (
        "Design, arte e geracao visual",
        ["principles of art", "aesthetic", "estetica", "generative art",
         "generative algorithm", "arte generativa", "composicao visual",
         "parametric design", "grasshopper", "sculpture", "painting",
         "teoria da arte", "expression", "craft", "universal principles of design",
         "principles of design", "tipografia", "typeface", "grid system", "design system"],
    ),
    "matematica": (
        "Matematica",
        ["mathematics", "matematica", "calculus", "algebra", "trigonometry", "theorem",
         "integral", "derivative"],
    ),
    "idiomas": (
        "Idiomas e material didatico de lingua",
        # existe para nao poluir `ux-conversao`: guia de professor de ingles
        # casava "exercise"/"unit"/"activity" e caia la, dentro da categoria que
        # a operacao usa para msg1 e landing. `geral` seria o outro destino, mas
        # de la o `--categoria` nao alcanca.
        ["teacher's guide", "teachers guide", "guia do professor", "student's book",
         "workbook", "grammar exercise", "vocabulary unit", "esl", "efl",
         "language course", "curso de idiomas", "livro do aluno", "phrasal verb",
         "gramatica inglesa", "espanhol comercial", "manual de estilo"],
    ),
    "mercado-setorial": (
        "Estudos de mercado e setor",
        ["market overview", "wine", "vinho", "fintech", "catalogue", "industry report",
         "consumer market", "china"],
    ),
}

CATEGORIA_PADRAO = "geral"
ROTULOS = {k: v[0] for k, v in CATEGORIAS.items()}
ROTULOS[CATEGORIA_PADRAO] = "Geral"

_LIXO_NOME = re.compile(
    r"\b(true[- ]?pdf|pdf|ebook|e[- ]book|download|z[- ]?library|libgen|sk[- ]1lib|"
    r"compressed|compactado|pdfcoffee|com|later|final|scan(ned)?|part\d?|v\d+)\b",
    re.IGNORECASE,
)


def titulo_de(caminho: Path, doc) -> str:
    bruto = (doc.titulo or "").strip()
    if len(bruto) < 4 or bruto.lower().endswith((".pdf", ".indd", ".doc")) or "microsoft word" in bruto.lower():
        bruto = ""
    if not bruto:
        bruto = caminho.stem
        bruto = re.sub(r"^\d{6,}[-_]", "", bruto)      # id do scribd
        bruto = bruto.replace("_", " ").replace("-", " ")
        bruto = _LIXO_NOME.sub(" ", bruto)
        bruto = re.sub(r"\s+", " ", bruto).strip(" -")
    return bruto or caminho.stem


# Termo curto casa dentro de outra palavra e manda documento para a categoria
# errada. Medido em 09/09/2026: "cro" (ux-conversao) acertava 8 vezes na ficha
# tecnica de um guia de professor, e "rust" casa dentro de "trust" -- palavra
# que aparece o tempo todo em livro de vendas. Termo curto de uma palavra so
# passa a exigir fronteira; frase de duas palavras nao precisa, ja e especifica.
_LIMITE_CURTO = 4
_regex_curto: dict = {}


def _ocorrencias(termo: str, texto: str) -> int:
    if len(termo) > _LIMITE_CURTO or " " in termo:
        return texto.count(termo)
    rx = _regex_curto.get(termo)
    if rx is None:
        rx = _regex_curto[termo] = re.compile(
            rf"(?<![a-z0-9]){re.escape(termo)}(?![a-z0-9])")
    return len(rx.findall(texto))


def classificar(caminho: Path, titulo: str, amostra: str) -> str:
    nome = (caminho.stem + " " + titulo).lower().replace("-", " ")
    corpo = amostra.lower()
    placar = {}
    for categoria, (_rotulo, termos) in CATEGORIAS.items():
        pontos = 0
        for termo in termos:
            if _ocorrencias(termo, nome):
                pontos += 6
            pontos += min(_ocorrencias(termo, corpo), 8)
        if pontos:
            placar[categoria] = pontos
    if not placar:
        return CATEGORIA_PADRAO
    melhor = max(placar, key=placar.get)
    return melhor if placar[melhor] >= 4 else CATEGORIA_PADRAO


def amostra_do_doc(doc, paginas: int = 40, limite: int = 60000) -> str:
    pedacos = []
    tamanho = 0
    for p in doc.paginas[:paginas]:
        pedacos.append(p.md)
        tamanho += len(p.md)
        if tamanho > limite:
            break
    return "\n".join(pedacos)


# ----------------------------------------------------------------- escrita


def _num(n: int) -> str:
    """1234567 -> '1.234.567'. Formatar so o numero: aplicar replace na linha
    inteira comia a virgula dos rotulos ('Posicionamento, precificacao')."""
    return f"{n:,}".replace(",", ".")


def _yaml(valor) -> str:
    if isinstance(valor, (int, float)):
        return str(valor)
    texto = str(valor).replace('"', "'")
    return '"' + texto + '"'


def frontmatter(campos: dict) -> str:
    linhas = ["---"]
    for chave, valor in campos.items():
        linhas.append(f"{chave}: {_yaml(valor)}")
    linhas.append("---")
    return "\n".join(linhas) + "\n"


def escrever_livro(raiz_md: Path, categoria: str, pasta: str, meta: dict,
                   capitulos: list) -> Path:
    destino = raiz_md / categoria / pasta
    destino.mkdir(parents=True, exist_ok=True)
    for antigo in destino.glob("*.md"):
        antigo.unlink()

    arquivos = []
    for cap in capitulos:
        nome = f"{cap.ordem:02d}-{slug(cap.titulo, 50)}.md"
        util, motivo = qualidade.avaliar(cap.titulo, cap.md)
        campos = dict(meta)
        campos.update(
            {
                "capitulo": cap.titulo,
                "capitulo_n": f"{cap.ordem}/{len(capitulos)}",
                "paginas": f"{cap.pagina_inicial}-{cap.pagina_final}",
                "palavras": cap.palavras,
                "util": "sim" if util else "nao",
            }
        )
        if motivo:
            campos["motivo_descarte"] = motivo
        corpo = frontmatter(campos) + "\n# " + cap.titulo + "\n\n" + cap.md + "\n"
        (destino / nome).write_text(corpo, encoding="utf-8")
        arquivos.append((nome, cap, util, motivo))

    linhas = [
        frontmatter({**meta, "tipo": "indice-do-documento",
                     "capitulos": len(capitulos)}),
        f"\n# {meta['titulo']}\n",
    ]
    if meta.get("autor"):
        linhas.append(f"**Autor:** {meta['autor']}  ")
    linhas.append(
        f"**Categoria:** {ROTULOS.get(categoria, categoria)} · "
        f"**{meta.get('total_paginas', '?')} paginas** · "
        f"**{_num(meta.get('total_palavras', 0))} palavras** · "
        f"extrator `{meta.get('extrator', '?')}`\n"
    )
    descartados = [c for _, c, u, _ in arquivos if not u]
    if descartados:
        linhas.append(
            f"_{len(descartados)} de {len(arquivos)} capitulos marcados "
            f"`util: nao` (apoio, sumario ou indice): ficam fora da busca._\n"
        )
    linhas.append("| # | Capitulo | Paginas | Palavras | Arquivo |")
    linhas.append("|---|---|---|---|---|")
    for nome, cap, util, motivo in arquivos:
        titulo = cap.titulo.replace("|", "/")
        marca = "" if util else f" _(fora da busca: {motivo})_"
        linhas.append(
            f"| {cap.ordem} | {titulo}{marca} | {cap.pagina_inicial}-{cap.pagina_final} "
            f"| {cap.palavras} | [{nome}]({nome}) |"
        )
    (destino / "INDEX.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return destino


# ------------------------------------------------------------------ indices


def gerar_indice(raiz: Path, manifesto: dict) -> None:
    raiz_md = raiz / "markdown"
    ok = [v for v in manifesto.values() if v.get("status") == "ok"]
    falhos = [v for v in manifesto.values() if v.get("status") == "falha"]

    por_categoria = {}
    for item in ok:
        por_categoria.setdefault(item["categoria"], []).append(item)

    total_palavras = sum(i.get("palavras", 0) for i in ok)
    idiomas = {}
    for i in ok:
        idiomas[i.get("idioma", "xx")] = idiomas.get(i.get("idioma", "xx"), 0) + 1
    resumo_idioma = ", ".join(
        f"{n} em `{c}`" for c, n in sorted(idiomas.items(), key=lambda kv: -kv[1])
    )

    linhas = [
        "# Base de conhecimento",
        "",
        f"_Gerado por `motor/processar.py` em {date.today().isoformat()}._",
        "",
        f"**{len(ok)} documentos** · **{len(por_categoria)} categorias** · "
        f"**{_num(total_palavras)} palavras** em markdown.",
        "",
        f"Idioma dos documentos: {resumo_idioma}. Isso importa na hora de "
        "perguntar: a busca lexica (`buscar.py`) so casa palavra, entao para "
        "material em outro idioma use `semantico.py --hibrido`.",
        "",
        "Cada documento e uma pasta em `markdown/<categoria>/<documento>/` com um "
        "`INDEX.md` (sumario com paginas e contagem de palavras) e um arquivo por "
        "capitulo. Leia o `INDEX.md` do documento antes de abrir capitulo.",
        "",
        "Busca antes de abrir arquivo. O padrao e o hibrido (sentido + termo exato):",
        "",
        "```bash",
        'python semantico.py "objecao de preco" --hibrido --passagens',
        'python buscar.py "useEffect"   # sigla, nome proprio',
        "```",
        "",
        "## Categorias",
        "",
        "| Categoria | Documentos | Palavras |",
        "|---|---|---|",
    ]
    for categoria in sorted(por_categoria, key=lambda c: -len(por_categoria[c])):
        itens = por_categoria[categoria]
        palavras = sum(i.get("palavras", 0) for i in itens)
        linhas.append(
            f"| [{ROTULOS.get(categoria, categoria)}](markdown/{categoria}/) "
            f"| {len(itens)} | {_num(palavras)} |"
        )
    linhas.append("")

    for categoria in sorted(por_categoria):
        itens = sorted(por_categoria[categoria], key=lambda i: i["titulo"].lower())
        linhas.append(f"## {ROTULOS.get(categoria, categoria)}")
        linhas.append("")
        linhas.append("| Documento | Idioma | Autor | Cap. | Palavras | Indice |")
        linhas.append("|---|---|---|---|---|---|")
        for i in itens:
            caminho = f"markdown/{categoria}/{i['pasta']}/INDEX.md"
            uteis, total = i.get("capitulos_uteis"), i.get("capitulos", "?")
            caps = f"{uteis}/{total}" if uteis is not None and uteis != total else str(total)
            linhas.append(
                f"| {i['titulo']} | {i.get('idioma', 'xx')} | {i.get('autor', '') or '-'} "
                f"| {caps} | {_num(i.get('palavras', 0))} | [abrir]({caminho}) |"
            )
        linhas.append("")

        cat_dir = raiz_md / categoria
        if cat_dir.exists():
            sub = [f"# {ROTULOS.get(categoria, categoria)}", "",
                   "| Documento | Palavras | Indice |", "|---|---|---|"]
            for i in itens:
                sub.append(
                    f"| {i['titulo']} | {_num(i.get('palavras', 0))} "
                    f"| [{i['pasta']}]({i['pasta']}/INDEX.md) |"
                )
            (cat_dir / "INDEX.md").write_text("\n".join(sub) + "\n", encoding="utf-8")

    if falhos:
        linhas.append("## Falhas")
        linhas.append("")
        linhas.append("| Arquivo | Motivo |")
        linhas.append("|---|---|")
        for i in sorted(falhos, key=lambda x: x["arquivo"]):
            linhas.append(f"| {i['arquivo']} | {i.get('erro', '?')} |")
        linhas.append("")

    (raiz / "INDEX.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")


def carregar_manifesto(caminho: Path) -> dict:
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return {}


def salvar_manifesto(caminho: Path, manifesto: dict) -> None:
    caminho.write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False), encoding="utf-8"
    )
