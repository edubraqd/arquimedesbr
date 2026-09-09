# arquimedesbr

**Transforma a sua biblioteca de livros e papers em algo que um agente de código consegue de fato ler.**

Português · [English](README.md)

Um PDF é uma parede. O agente que abre um ou gasta a janela de contexto inteira em 400 páginas, ou não lê nada. O `arquimedesbr` converte os seus documentos em markdown fatiado por capítulo, indexa por termo e por significado, e entrega ao agente uma busca que devolve **as 400 palavras certas** — com título, capítulo e páginas, para que toda afirmação continue conferível.

Nenhum LLM no processamento. Nenhuma chamada de rede. Nenhuma conta de API. Tudo roda local.

```bash
python motor/semantico.py "como responder quando o cliente diz que está caro" --rerank --passagens --categoria vendas
```

```
1. 0,71  Gap Selling / 07-the-problem-identification-chart.md  (p. 112-129)
   "...the buyer's objection to price is almost never about price. It is about
    a gap they have not yet quantified..."
```

---

## Índice

- [Por que isso existe](#por-que-isso-existe)
- [Duas pastas, e por que são separadas](#duas-pastas-e-por-que-são-separadas)
- [Sobre os livros](#sobre-os-livros)
- [Instalação](#instalação)
- [Adicionar documento](#adicionar-documento)
- [Buscar](#buscar)
- [O que foi medido](#o-que-foi-medido)
- [Usar pelo Claude Code (a skill)](#usar-pelo-claude-code-a-skill)
- [Ajustar categorias e domínios](#ajustar-categorias-e-domínios)
- [Limites honestos](#limites-honestos)
- [Glossário PT ↔ EN](#glossario-pt--en)

---

## Por que isso existe

Tutorial de RAG costuma partir do princípio de que você quer um chatbot em cima de um corpus. Não é isso. Isto é uma **estante de referência para um agente que está fazendo outra coisa** — escrevendo copy, escolhendo uma arquitetura, precificando uma proposta — e precisa conferir o que um livro específico diz antes de se comprometer.

Três decisões de projeto saem daí:

1. **Capítulo, não documento.** Capítulo cabe em contexto (alvo de ~8 mil palavras). Livro não cabe. A unidade de leitura é o capítulo; a unidade de *busca* é uma passagem de 60 palavras dentro dele.
2. **Citação é obrigatória.** Todo arquivo de capítulo carrega `titulo`, `autor`, `capitulo` e `paginas` no frontmatter. Se o agente não consegue citar, ele deve dizer que a base não cobre o tema — e não preencher o buraco com conhecimento geral disfarçado de fonte.
3. **Custo recorrente zero.** A extração é PyMuPDF. A classificação é por palavra-chave. Os embeddings são um MiniLM local via `fastembed`. Nada sai da máquina.

---

## Duas pastas, e por que são separadas

É a parte que todo mundo erra na primeira rodada, então vem antes da instalação.

```
arquimedesbr/          <- ESTE REPOSITÓRIO. o motor. só código. vai para o GitHub.
  motor/*.py
  skill/SKILL.md
  README.md

~/Arquimedes/          <- SUA BASE (a "raiz"). seus arquivos. NUNCA vai para o GitHub.
  nao-processado/      <- fila de entrada: jogue PDF / DOCX / TXT / MD aqui
  processado/          <- o original, depois da conversão bem sucedida
  falhas/              <- não deu texto (escaneado sem OCR, corrompido)
  removidos/           <- documento que você tirou de propósito; não volta
  markdown/
    <categoria>/
      <documento>/
        INDEX.md       <- sumário com páginas
        01-capitulo.md <- frontmatter + texto
        02-capitulo.md
  manifesto.json       <- estado por sha256 de cada arquivo original
  INDEX.md             <- catálogo da base inteira
  MAPA.md              <- um cartão por documento: idioma, tamanho, conceitos próprios
  GRAFO.md             <- comunidades e pontes entre documentos
  .indice-busca.json   <- índice BM25
  .indice-semantico.*  <- vetores
```

**O motor é público. A base é sua e fica no seu disco.** São diretórios separados de propósito: os seus livros são material protegido por direito autoral que você adquiriu, e o markdown gerado é derivado deles. Publicar o motor, tudo bem. Publicar o seu `markdown/`, não.

A raiz é resolvida nesta ordem:

1. `--raiz /caminho/da/base` em qualquer comando;
2. a variável de ambiente `ARQUIMEDES_RAIZ`;
3. `~/Arquimedes`.

Então dá para manter a base num HD externo, num NAS, onde for — o motor não presume nada.

---

## Sobre os livros

**Este repositório não distribui livro nenhum, nem trecho, nem índice.** É código que processa arquivos que você já tem.

O que entra:

| Formato | Observação |
|---|---|
| `.pdf` | caminho principal. PDF escaneado passa por OCR se o Tesseract estiver instalado |
| `.epub` | só stdlib. Uma "página" por documento do spine, então o corte cai em fronteira de capítulo de verdade |
| `.docx` | precisa de `python-docx` |
| `.txt`, `.md` | entram direto, e mesmo assim são fatiados e catalogados |

O que faz sentido colocar: livro que você comprou, paper do arXiv ou de revista aberta, suas anotações, manual, documentação interna, qualquer coisa que você tem direito de ler. O que não: material que você não adquiriu. A ferramenta não tem opinião sobre isso e não tem como conferir — esse julgamento é seu, e a licença isenta de garantia por um motivo.

Duas observações práticas, aprendidas na marra:

- **Muito PDF que circula por aí é trecho, não o livro inteiro.** O `INDEX.md` gerado mostra a contagem real de páginas. Confira antes de concluir que um livro "não trata" de um tema — pode simplesmente não estar tudo ali.
- **Duplicata é pega por sha256**, então o mesmo arquivo com outro nome nunca entra duas vezes. Uma *edição* diferente do mesmo livro entra duas vezes, porque de fato é outro arquivo.

---

## Instalação

Precisa de **Python 3.10+**.

```bash
git clone https://github.com/edubraqd/arquimedesbr.git
cd arquimedesbr
pip install -r requirements.txt
python instalar.py
```

O `instalar.py` é opcional e não faz nada esperto — cria `~/Arquimedes/{nao-processado,processado,falhas,removidos,markdown}` e copia `skill/SKILL.md` para `~/.claude/skills/arquimedesbr/`. Rode com `--raiz` para pôr a base em outro lugar, ou pule e crie as pastas na mão.

Defina a raiz uma vez, para não repetir `--raiz`:

```bash
export ARQUIMEDES_RAIZ="$HOME/Arquimedes"
```

```powershell
$env:ARQUIMEDES_RAIZ = "$HOME\Arquimedes"
```

### Opcional: OCR para PDF escaneado

Instale o binário do Tesseract (`winget install tesseract-ocr.tesseract`, `brew install tesseract`, `apt install tesseract-ocr`) mais `pytesseract` e `pillow`. Idiomas extras podem ficar em `motor/tessdata/` — o motor aponta o `TESSDATA_PREFIX` para essa pasta quando ela existe, o que evita precisar de admin para escrever dentro da instalação do sistema. Custa ~0,5 s por página com 8 threads.

Sem Tesseract tudo continua funcionando; o PDF escaneado apenas cai em `falhas/`.

### Conferir

```bash
python -m unittest discover -s motor -p "test_*.py"
```

85 testes. Não tocam disco nem rede.

---

## Adicionar documento

```bash
cp ~/Downloads/livro.pdf "$ARQUIMEDES_RAIZ/nao-processado/"
```

```bash
cd motor
python processar.py
```

Variantes úteis:

```bash
python processar.py --seco
python processar.py --status
python processar.py --limite 3
python processar.py --so-indice
```

`--seco` mostra os capítulos que cortaria e não escreve nada. `--status` diz o que já tem na base e o que falhou. `--so-indice` regenera o `INDEX.md` a partir do manifesto, sem reprocessar nada.

O fluxo, numa tela:

```
nao-processado/arquivo.pdf
   |
   v  extrair.py    PyMuPDF lê fonte e posição -> título vira "##".
   |                Remove cabeçalho/rodapé repetido, número de página solto,
   |                hifenização de quebra de linha e ligaduras. Página sem
   |                texto útil cai no OCR.
   |
   v  fatiar.py     Corta por capítulo usando o sumário (bookmarks) do PDF. Sem
   |                sumário, detecta o início de capítulo pelo TAMANHO DA FONTE
   |                e só aceita se a detecção cobrir o livro inteiro; senão,
   |                corta por PÁGINA até o alvo de tamanho — assim cada trecho
   |                guarda a faixa real de páginas e a citação continua conferível.
   |                Alvo 8k palavras, mínimo 400 (gruda), máximo 12k (divide).
   |
   v  qualidade.py  Detecta idioma (perfil de palavras funcionais: pt/en/es/fr/
   |                it/de/id) e marca capítulo sem valor: copyright, sumário,
   |                índice remissivo, página de venda, texto degenerado.
   |
   v  catalogar.py  Classifica em categoria por palavra-chave (o nome do arquivo
   |                pesa mais que o corpo), escreve frontmatter e três níveis
   |                de INDEX.md.
   |
   v  rotular.py    Dá nome a capítulo que o PDF só chamou de "Trecho 4", usando
                    título interno ou TF-IDF contra os irmãos do mesmo livro.
                    Escreve `assunto` e `termos`, refaz o MAPA.md.
```

Depois de incluir documento, atualize as camadas derivadas:

```bash
python semantico.py indexar
python rotular.py
python grafear.py
```

O índice semântico é **chaveado por hash do corpo do capítulo, não por mtime**. Isso importa: corrigir categoria ou gravar o campo de idioma reescreve o frontmatter de centenas de arquivos. Por mtime, cada uma dessas revisões mandaria reembutir a base inteira (~40 min de CPU) sem uma palavra de texto ter mudado.

### Curadoria

Classificação por palavra-chave erra. Corrija sem reprocessar o PDF:

```bash
python processar.py --mover <pasta-do-documento> --para <categoria>
python processar.py --remover <pasta-do-documento> --motivo "por que saiu"
python processar.py --revisar --seco
python processar.py --revisar
```

`--remover` apaga o markdown, manda o original para `removidos/` e registra no manifesto para que ele não volte na próxima rodada. `--revisar` aplica regra nova (idioma, descarte de capítulo) na base inteira em segundos, sem reabrir um PDF sequer.

---

## Buscar

**Recorte o corpus antes de escolher o método.** Isso decide mais que o método.

| Recorte | Quando |
|---|---|
| `--categoria <cat>` | a pergunta tem endereço óbvio. **É o que rende.** |
| `--dominio comercial` | copy, preço, proposta, posicionamento, UX |
| `--dominio tecnico` | arquitetura, stack, modelo, métrica |
| `--dominio pessoal` | o que você puser lá |

Depois, nesta ordem:

**1. Semântica com reranker — é o padrão.**

```bash
python semantico.py "como responder que está caro" --rerank --passagens --categoria vendas
```

O `--rerank` custa ~6 s e vale: um cross-encoder lê a pergunta junto com cada trecho, em vez de comparar vetores calculados sem nunca ter visto a pergunta.

O `--passagens` é o truque *small-to-big*. A busca compara passagens de 60 palavras — medido, é o tamanho que o modelo separa melhor — mas devolve a **janela de ~420 palavras em volta** do achado, alinhada à fronteira de frase (`--janela N` muda). Normalmente basta para responder sem abrir o capítulo.

**2. BM25 quando o alvo é literal** — sigla, nome próprio, jargão (`FTP`, `useEffect`, `borrow checker`). Aí escreva a consulta **nos dois idiomas**:

```bash
python buscar.py "objecao de preco" --tambem "price objection" --n 6 --trechos
```

**3. Leia o `INDEX.md` do documento** antes do capítulo — ele tem o sumário com páginas e contagem de palavras.

**4. Leia só o capítulo apontado.** Nunca o livro inteiro.

**5. O grafo, quando a pergunta for de relação** — "o que conecta X e Y", "quem mais fala disso":

```bash
python grafear.py --ponte "preco"
python grafear.py
```

O grafo mede vocabulário compartilhado, não semântica — às vezes agrupa por idioma. Não conclua parentesco de tema só da vizinhança.

**Não use `--hibrido`.** Fundir os dois rankings mede pior que qualquer um sozinho: a fusão dá peso igual a método forte e a método fraco.

---

## O que foi medido

Os números abaixo saem do `avaliar_dominio.py` contra um gabarito de 53 perguntas (`gabarito.py`), medido no nível de documento, sobre uma base real de 77 documentos / 818 capítulos, em 07/09/2026.

| Método | hit@1 | hit@3 | MRR |
|---|---|---|---|
| BM25 bilíngue | 8/53 | 39/53 | 0,456 |
| BM25 + `--dominio` | 16/53 | 42/53 | 0,547 |
| BM25 + `--categoria` | 32/53 | 47/53 | 0,746 |
| semântico | 20/53 | 34/53 | 0,543 |
| semântico + `--dominio` | 21/53 | 36/53 | 0,567 |
| semântico + `--categoria` | 37/53 | 46/53 | 0,806 |
| semântico + rerank | 29/53 | 41/53 | 0,669 |
| semântico + rerank + `--dominio` | 32/53 | 43/53 | 0,710 |
| **semântico + rerank + `--categoria`** | **43/53** | **48/53** | **0,869** |

Três leituras que importam:

1. **`--categoria` carrega mais que o reranker.** Sozinho ele dá 37/53; o reranker sozinho dá 29/53. Juntos, 43/53. Eles somam — não são alternativa um do outro.
2. **`--dominio` quase não rende na busca semântica** (20 → 21 sem reranker, 29 → 32 com). O embedding já separa domínio sozinho. No BM25 é o contrário — dobra o acerto de primeira (8 → 16), porque busca lexical colide termo entre domínios com facilidade.
3. **Consulte nos dois idiomas no BM25.** O hit@1 não muda (8/53 nos dois), mas o hit@3 triplica (13 → 39) e o MRR dobra. Monolíngue às vezes acerta, mas raramente coloca o alvo perto do topo.

Duas ressalvas, ditas com todas as letras:

- Os números usam a categoria **do alvo**, então são **teto**: medem o ganho disponível para quem escolhe o recorte certo. Errar domínio é difícil; errar categoria é fácil. Na dúvida entre duas categorias, use `--dominio` em vez de chutar.
- Foram medidos em **uma base específica com um conjunto específico de perguntas.** A sua vai ser diferente. Escreva o seu próprio `gabarito.py` e rode o `avaliar_dominio.py` de novo — é para isso que o avaliador vem junto.

### O que foi medido e NÃO funcionou

Guardado aqui para ninguém gastar um dia redescobrindo.

| Ideia | Resultado medido |
|---|---|
| **Prever a categoria automaticamente** (`prever_categoria.py`) | 29 → 30/53. A categoria certa é o primeiro palpite em só 52% dos casos, e filtrar por um palpite errado derruba o hit@3 (38 → 35). Deixe um humano — ou o agente, que tem o contexto da conversa — passar `--categoria`. |
| **e5-large no lugar do MiniLM** | MRR pior, e 127 min de indexação contra 13 |
| **Híbrido por fusão de rankings** (`--hibrido`) | 0,645 contra 0,713 do semântico + reranker sozinho |
| **Recuperar 1,3 milhão de palavras** (um bug real de extração) | 43 → 44/53. O conteúdo recuperado é real, mas o gabarito não pergunta por ele. Corrigir o acervo não moveu a métrica; direcionar melhor moveu. |

### O canário de extração

Todo PDF ingerido é conferido contra o próprio `get_text()` cru do PyMuPDF. Abaixo de 80% de cobertura sai aviso na hora e a razão fica no manifesto (`razao_extracao`).

Existe porque uma falha real passou meses sem ninguém ver: spans de espaço descartados colavam o texto de PDF em LaTeX, e 13 documentos entraram com 22% a 74% do conteúdo, sem erro nenhum na tela. Se você for construir algo assim, construa o canário primeiro.

### Regra de descarte precisa de proporção, não de contagem

O motor descarta capítulo que na verdade é sumário. A primeira regra contava os pontilhados (`. . . . . 54`) e cortava acima de 12.

Essa regra jogou fora 23 dos 34 capítulos de um *Security Analysis* escaneado de 735 páginas — cerca de 180 mil palavras de prosa real sobre bonds e depreciação. O livro é cheio de tabela financeira, e o OCR transforma o pontilhado de cada linha num run de pontos.

Medido nos 27 capítulos em que a regra já tinha disparado: sumário de verdade gasta **15,8% a 48,7%** dos caracteres em pontilhado; capítulo de conteúdo com tabela não passa de **5,5%**. O corte agora é essa fração, não a contagem.

A lição geral, que custou um dia: **contagem absoluta é limiar disfarçado sobre o tamanho do documento.** Toda regra do tipo "mais de N ocorrências" dispara em documento longo e passa batido em documento curto. Transforme em proporção e meça onde as duas populações de fato se separam.


---

## Usar pelo Claude Code (a skill)

O `skill/SKILL.md` instala como skill do Claude Code chamada **arquimedesbr**. Uma vez em `~/.claude/skills/arquimedesbr/SKILL.md`, o Claude consulta a base por conta própria antes de escrever copy, precificar ou escolher arquitetura — e cita título + capítulo + páginas.

```bash
mkdir -p ~/.claude/skills/arquimedesbr && cp skill/SKILL.md ~/.claude/skills/arquimedesbr/
```

Depois, em qualquer projeto: `/arquimedesbr`, ou simplesmente "o que os livros dizem sobre objeção de preço?".

O corpo da skill ensina ao agente a ordem de consulta acima, os limites honestos e — o mais importante — **dizer que a base não cobre o tema, em vez de responder com conhecimento geral dando a entender que tem fonte**. Essa instrução é a diferença entre uma estante útil e um mentiroso convicto.

Funciona com qualquer agente que leia um prompt de sistema, não só o Claude Code. O arquivo é markdown puro; cole onde o seu agente aceita instrução.

---

## Ajustar categorias e domínios

As categorias padrão ficam em `motor/catalogar.py` (`ROTULOS`) e refletem a estante de uma pessoa:

`vendas` · `marketing` · `copy-persuasao` · `posicionamento-negocio` · `ux-conversao` · `design-arte` · `engenharia-software` · `frontend` · `python` · `rust` · `ia-llm` · `agentes-llm` · `dados-ml` · `ciencia-cognitiva` · `financas-investimentos` · `seguranca-llm` · `seguranca-ofensiva` · `treino-endurance` · `matematica` · `busca-recuperacao` · `mercado-setorial` · `geral`

Troque pelas suas. Cada entrada é um rótulo mais as palavras-chave que o selecionam; o nome do arquivo pesa mais que o corpo.

Domínios agrupam categorias e podem ser remanejados **sem editar código**, por um `dominio.json` na raiz da sua base:

```json
{
  "comercial": ["vendas", "copy-persuasao", "posicionamento-negocio"],
  "tecnico": ["python", "rust", "ia-llm"],
  "pessoal": ["treino-endurance", "financas-investimentos"]
}
```

Categoria que existe na base e não está em domínio nenhum entra em **todos** — para documento novo nunca sumir calado.

### Onde mexer

| Quero mudar | Arquivo |
|---|---|
| tamanho da passagem, sobreposição, modelo | `semantico.py` (`PASSAGEM_PALAVRAS`, `AVANCO`, `MODELO`) |
| tamanho de capítulo, regra de corte | `fatiar.py` (`ALVO_PALAVRAS`, `MAX_PALAVRAS`) |
| categorias e palavras-chave | `catalogar.py` (`ROTULOS`) |
| detecção de título/rodapé, limpeza | `extrair.py` |
| o que conta como capítulo sem valor | `qualidade.py` |
| ranking da busca | `buscar.py` (`bm25`, `_PARADAS`) |
| onde fica a base | `raiz.py` |

---

## Limites honestos

- **Tabela vira sequência de números.** Fórmula matemática vira ruído. PDF de duas colunas pode embaralhar a ordem de leitura. Isso é limite estrutural, não bug a ser corrigido.
- **A classificação por categoria é casamento de palavra-chave, determinística. Erra.** Confie na busca, que varre o texto todo, e não na categoria.
- **O grafo mede vocabulário compartilhado**, então às vezes agrupa por idioma em vez de por tema.
- **A primeira indexação é lenta** — cerca de 40 minutos de CPU para ~90 mil passagens. Depois é incremental, e livro novo custa segundos.
- **Tudo isso foi feito para a estante de uma pessoa e depois generalizado.** Onde um padrão parecer arbitrário, ele provavelmente codifica uma medição num corpus que não é o seu. Meça de novo.

---

## Glossário PT ↔ EN

O código e os parâmetros estão em português. Não foram renomeados porque renomear um sistema que funciona é como sistemas que funcionam quebram. A tradução:

| Português | English |
|---|---|
| `motor` | engine |
| `raiz` / `--raiz` | root |
| `processar` | process / ingest |
| `buscar` | search (BM25) |
| `semantico` | semantic search |
| `fatiar` | slice |
| `extrair` | extract |
| `catalogar` | catalog |
| `rotular` | label |
| `grafear` | build graph |
| `--seco` | dry run |
| `--categoria` | category filter |
| `--dominio` | domain filter |
| `--passagens` | return surrounding window |
| `--janela N` | window size in words |
| `--trechos` | show snippets |
| `--tambem` | also query this (second language) |
| `--n N` | number of results |
| `--reindexar` / `--refazer` | rebuild index |
| `--revisar` | re-apply rules without reprocessing |
| `--mover` / `--para` | move document / to category |
| `--remover` / `--motivo` | remove document / reason |
| `--limite N` | only the first N |
| `--status` | status report |
| `nao-processado` | inbox |
| `processado` | done |
| `falhas` | failures |
| `removidos` | removed |
| `capitulo` / `paginas` / `titulo` / `autor` | chapter / pages / title / author |
| `assunto` / `termos` / `idioma` / `util` | subject / terms / language / useful |

---

## Referência

O padrão *small-to-big* — buscar em passagem pequena, entregar a janela em volta — está descrito em *Building LLMs for Production*, capítulo "Advanced RAG Techniques", p. 220–229.

Feito com [Claude Code](https://claude.com/claude-code). Contribuição é bem-vinda, principalmente medição em bases que não se parecem em nada com a que isto foi ajustado.

Licença MIT. Veja [LICENSE](LICENSE).
