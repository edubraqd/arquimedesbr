# arquimedesbr

**Transforma a sua biblioteca de livros e papers em algo que um agente de código consegue de fato ler.**

Português · [English](README.md)

Um PDF é uma parede. O agente que abre um ou gasta a janela de contexto inteira em 400 páginas, ou não lê nada. O `arquimedesbr` converte os seus documentos em markdown fatiado por capítulo, indexa por termo e por significado, e entrega ao agente uma busca que devolve **as 400 palavras certas** — com título, capítulo e páginas, para que toda afirmação continue conferível.

Nenhum LLM no processamento. Nenhuma chamada de rede. Nenhuma conta de API. Tudo roda local.

```bash
python motor/consultar.py "como responder quando o cliente diz que está caro" --tambem "price objection" --categoria vendas
```

```
1. +0.712  Gap Selling — The problem identification chart · p.112-129
   the buyer's objection to price is almost never about price. It is about a gap they have not yet quantified...
2. +0.655  SPIN Selling — Handling objections · p.117-138
   ...

sessao a1b2 · rodada 1
  abrir:      python consultar.py --sessao a1b2 --abrir <n>
  mais do doc: python consultar.py --sessao a1b2 --mais <n>
  nao serviu: python consultar.py --sessao a1b2 --sim <n,n> --nao <n,n>
```

Seis cartões de ~25 palavras. O agente lê, abre o que quer (`--abrir 1`, ~420 palavras), ou diz quais não serviram e recebe outros seis — sem embutir de novo e sem gastar token. Menos de 1 s por rodada com o [servidor residente](#o-servidor-residente) no ar.

---

## Índice

- [Por que isso existe](#por-que-isso-existe)
- [Duas pastas, e por que são separadas](#duas-pastas-e-por-que-são-separadas)
- [Sobre os livros](#sobre-os-livros)
- [Instalação](#instalação)
- [Adicionar documento](#adicionar-documento)
- [Buscar](#buscar)
- [O que foi medido](#o-que-foi-medido)
- [Consultar barato: cartões primeiro, realimentação depois](#consultar-barato-cartões-primeiro-realimentação-depois)
- [Onde a busca erra, e contra quem](#onde-a-busca-erra-e-contra-quem)
- [Usar pelo Claude Code (a skill)](#usar-pelo-claude-code-a-skill)
- [Ajustar categorias e domínios](#ajustar-categorias-e-domínios)
- [Limites honestos](#limites-honestos)
- [Glossário PT ↔ EN](#glossário-pt--en)

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

159 testes. Usam só pasta temporária, não baixam modelo e não abrem socket além do loopback em porta livre que os testes do servidor residente usam.

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

O `processar.py` agora reindexa sozinho depois de mexer no markdown — incremental, atômico (o índice velho fica até o novo estar escrito), com backup. `--sem-indexar` pula e imprime o comando; `--seco` nunca indexa. As outras camadas derivadas continuam separadas:

```bash
python rotular.py
python grafear.py
```

O índice guarda o mtime de cada capítulo que embutiu. Se algum `.md` em `markdown/` for mais novo que isso, ou não estiver lá, `consultar.py` e `semantico.py` avisam `indice semantico desatualizado (N novos, M alterados)` na stderr e seguem — aviso, não recusa, porque busca em índice um pouco velho ainda é melhor que nenhuma. Índice de antes dessa conferência ganha o carimbo no próximo `indexar`.

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

Desde 16/09/2026 o `--revisar` também **separa a bibliografia do capítulo**. Paper e capítulo técnico terminam com páginas de referências, e cada entrada virava uma passagem competindo com a prosa: medido numa estante, 289 capítulos `util: sim` carregavam 538 mil palavras de referências. `fatiar.separar_referencias` acha o último título `References`/`Bibliography`, segue até o próximo título que não pareça entrada de bibliografia (sem ano, sem `et al.`, sem DOI, sem URL — porque 148 dos 289 tinham apêndice *depois* das referências, que volta para o corpo) e move o bloco para `<capitulo>.referencias.md` com `util: nao`. O capítulo mantém a citação; as referências param de poluir o índice. Nessa estante a passada separou 292.950 palavras em 261 blocos, e 13 capítulos que tinham sido descartados errado como "índice" voltaram.

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

**1. `consultar.py` — a porta.** Cartão primeiro, janela larga só do cartão escolhido. Escreva a pergunta nos dois idiomas quando a estante for assim: o motor embute as duas strings e roda o BM25 nas duas. Ver [Consultar barato](#consultar-barato-cartões-primeiro-realimentação-depois).

```bash
python consultar.py "como responder que está caro" --tambem "price objection" --categoria vendas
```

**2. Semântica com reranker — a forma larga**, quando você já sabe que quer ~420 palavras de vários resultados de uma vez.

```bash
python semantico.py "como responder que está caro" --rerank --passagens --categoria vendas
```

O `--rerank` custa ~6 s e vale: um cross-encoder lê a pergunta junto com cada trecho, em vez de comparar vetores calculados sem nunca ter visto a pergunta.

O `--passagens` é o truque *small-to-big*. A busca compara passagens de 60 palavras — medido, é o tamanho que o modelo separa melhor — mas devolve a **janela de ~420 palavras em volta** do achado, alinhada à fronteira de frase (`--janela N` muda). Normalmente basta para responder sem abrir o capítulo.

**3. BM25 sozinho quando o alvo é literal** — sigla, nome próprio, jargão (`FTP`, `useEffect`, `borrow checker`). O `consultar.py` já funde o BM25; o `buscar.py` é para quando você quer *só* o acerto lexical. Escreva a consulta **nos dois idiomas**:

```bash
python buscar.py "objecao de preco" --tambem "price objection" --n 6 --trechos
```

**4. Leia o `INDEX.md` do documento** antes do capítulo — ele tem o sumário com páginas e contagem de palavras.

**5. Leia só o capítulo apontado.** Nunca o livro inteiro.

**6. O grafo, quando a pergunta for de relação** — "o que conecta X e Y", "quem mais fala disso":

```bash
python grafear.py --ponte "preco"
python grafear.py
```

O grafo mede vocabulário compartilhado, não semântica — às vezes agrupa por idioma. Não conclua parentesco de tema só da vizinhança.

**Sobre fundir BM25 com os vetores.** Uma versão anterior deste LEIAME dizia *não use `--hibrido`*, porque a fusão tinha medido pior que semântico + reranker sozinho. Aquele veredito veio de **12 perguntas em 25 documentos** — abaixo do piso de ruído que este mesmo arquivo avisa. Remedido em 16/09/2026 com 140 perguntas e 178 documentos, fundir os 30 melhores documentos de cada ranking por rank recíproco e reranquear os 6 é o melhor modo, ou empata com o melhor, em hit@3 e hit@6 — então o `consultar.py` faz isso por padrão (`--sem-bm25` desliga). A tabela está na seção seguinte. O `--hibrido` do `semantico.py` nunca foi a mesma coisa — fundia por passagem, sem reranker — e continua não recomendado.

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
| **Híbrido por fusão de rankings** (`semantico.py --hibrido`) | 0,645 contra 0,713 do semântico + reranker sozinho — medido em 12 perguntas, que é ruído. **Revertido em 16/09/2026** para a fusão por documento que o `consultar.py` faz; ver [a tabela de 16/09](#desde-16092026-bm25-fundido-dois-idiomas-um-cartão-por-documento). |
| **Recuperar 1,3 milhão de palavras** (um bug real de extração) | 43 → 44/53. O conteúdo recuperado é real, mas o gabarito não pergunta por ele. Corrigir o acervo não moveu a métrica; direcionar melhor moveu. |

### O canário de extração

Todo PDF ingerido é conferido contra o próprio `get_text()` cru do PyMuPDF. Abaixo de 80% de cobertura sai aviso na hora e a razão fica no manifesto (`razao_extracao`).

Existe porque uma falha real passou meses sem ninguém ver: spans de espaço descartados colavam o texto de PDF em LaTeX, e 13 documentos entraram com 22% a 74% do conteúdo, sem erro nenhum na tela. Se você for construir algo assim, construa o canário primeiro.

### Regra de descarte precisa de proporção, não de contagem

O motor descarta capítulo que na verdade é sumário. A primeira regra contava os pontilhados (`. . . . . 54`) e cortava acima de 12.

Essa regra jogou fora 23 dos 34 capítulos de um *Security Analysis* escaneado de 735 páginas — cerca de 180 mil palavras de prosa real sobre bonds e depreciação. O livro é cheio de tabela financeira, e o OCR transforma o pontilhado de cada linha num run de pontos.

Medido nos 27 capítulos em que a regra já tinha disparado: sumário de verdade gasta **15,8% a 48,7%** dos caracteres em pontilhado; capítulo de conteúdo com tabela não passa de **5,5%**. O corte agora é essa fração, não a contagem.

A lição geral, que custou um dia: **contagem absoluta é limiar disfarçado sobre o tamanho do documento.** Toda regra do tipo "mais de N ocorrências" dispara em documento longo e passa batido em documento curto. Transforme em proporção e meça onde as duas populações de fato se separam.


## Consultar barato: cartões primeiro, realimentação depois

O `semantico.py --passagens` devolve uma janela de ~420 palavras por resultado. Bom para ler, caro para decidir: o agente gasta ~1.700 tokens só para descobrir que o segundo resultado era o que ele queria. O `consultar.py` inverte isso.

```bash
python motor/consultar.py "como responder que está caro" --categoria vendas
python motor/consultar.py --sessao a1b2 --abrir 2
python motor/consultar.py --sessao a1b2 --sim 2 --nao 1,3
```

| | palavras | por candidato |
|---|---|---|
| `semantico.py --passagens --n 3` | 723 | 241 |
| `consultar.py --n 6` | 279 | **46** |

Dobro de candidatos por 39% do texto, e **o alvo está entre esses 6 cartões em 51 das 53 perguntas.** O agente não precisa dele em primeiro lugar, precisa enxergá-lo — e a janela larga só é buscada para o cartão que ele escolher.

### A segunda rodada é Rocchio

```
q' = alfa*q + beta*média(relevantes) - gama*média(não relevantes)
```

`alfa` 1, `beta` 0,75, `gama` 0,15 — de *Introduction to Information Retrieval*, cap. 9, que por acaso está na biblioteca que este motor indexa. O livro é explícito sobre a assimetria ("positive feedback turns out to be much more valuable than negative feedback, and so most IR systems set gama < beta") e sobre a pré-condição: a consulta inicial precisa já estar perto do alvo.

**Essa pré-condição aqui é medida, não suposta**: nas 53 perguntas o documento certo nunca ficou fora do top-50. É por isso que realimentação rende onde prefixo de contexto, correção de hubness e mais candidatos para o reranker falharam — as três atacavam recuperação, que nunca foi o gargalo.

Rocchio é aritmética de vetores: sem rede, sem token, milissegundos. O vetor da consulta fica em cache na sessão, então a segunda rodada não re-embute a pergunta.

**Duas rodadas, nunca três.** Medido: a rodada 2 leva o hit@1 de 28 para 33 de 53; a rodada 3 não acrescenta nada. Se duas rodadas não acharam, provavelmente a base não cobre a pergunta.

### Desde 16/09/2026: BM25 fundido, dois idiomas, um cartão por documento

Medido em 140 perguntas, categoria escolhida por agente lendo só a pergunta, cross-encoder nos 6 finais (`avaliar_consultar.py --todas --estrato`), sobre o índice refeito no mesmo dia depois de o `--revisar` separar as bibliografias: 234 documentos, 27.740 capítulos, 247.955 passagens. Uma rodada anterior, na mesma manhã e em índice desatualizado, tinha ordenado os modos do mesmo jeito; estes são os números que a substituem.

| modo | hit@1 | hit@3 | hit@6 | hit@12 | MRR |
|---|---|---|---|---|---|
| denso, pergunta só em português (o `consultar.py` de antes) | 62 | 105 | 117 | 117 | 0,596 |
| denso, vetor = PT + EN, sem BM25 | 70 | 111 | 130 | 130 | 0,657 |
| **RRF de denso-30 ∪ BM25-30 → rerank 6, PT + EN (o padrão)** | 72 | **114** | **130** | 130 | 0,671 |
| o padrão mais a rodada 2 (Rocchio) | 72 | 114 | 130 | **133** | 0,673 |
| `semantico.py`, 50 passagens → rerank (o caminho largo) | **90** | 113 | 128 | 129 | **0,745** |

Por domínio do alvo, hit@1 / hit@3 / hit@6: o padrão faz 30/48/52 nas 56 perguntas comerciais, **40/59/69 nas 74 técnicas** e 2/6/8 nas 9 pessoais; o caminho largo faz 39/46/53, 45/59/66 e 5/7/8. O que a tabela diz, em ordem de tamanho: `--tambem` vale **+10 / +9 / +13**; fundir BM25 por cima disso vale +2 / +3 / 0, dentro do ruído; a rodada 2 é a única coisa acima de 130; e no hit@6 os seis cartões ganham do caminho largo (130 contra 128) — o caminho largo só ganha o hit@1, que importa só para quem abre o primeiro cartão sem ler os outros. A rodada anterior em índice velho tinha também um modo BM25 puro → rerank que ganhava o hit@1 (79); não foi repetido.

Quatro coisas mudaram no `consultar.py` por causa disso:

- **`--tambem "<a pergunta em inglês>"`.** O motor soma os dois embeddings e roda o BM25 nas duas strings. É o ganho mais barato da estante — +10 em hit@1 e +13 em hit@6 a custo zero, porque o agente que escreve a consulta já sabe os dois idiomas e 173 desses 234 documentos são em inglês. Só pule se a estante inteira for de um idioma.
- **Toda rodada funde os 30 melhores documentos por vetor com os 30 por BM25** por rank recíproco (`fundir_rrf`), e reranqueia os 6. BM25 ganhar o hit@1 num corpus de ~15 M tokens bate com o que *BM25 Wins at Scale* (arXiv 2607.26497) prevê; a fusão segura o hit@6 do lado denso.
- **A rodada 2 nunca repete documento já mostrado.** O dedup antigo era por passagem: a consulta andava, outro capítulo do mesmo livro virava a melhor passagem dele, e um livro que você acabou de julgar voltava como novidade. Cartão visto é cartão gasto.
- **`--mais <n>`** lista os outros capítulos do documento do cartão *n*, ranqueados pela consulta atual, numerados para poder abrir. Cobre o caso que o dedup esconderia: livro certo, capítulo errado.

Duas menores: categoria que esgota os candidatos é completada com o domínio dela, avisando; e `--abrir` / `--estado` não carregam mais índice nem modelo — a sessão guarda caminho e posição de cada cartão, o que também a encolheu de 5 MB para 12 KB.

### O servidor residente

Medido em 16/09/2026: cada chamada do `consultar.py` levava 8–19 s, dos quais **~0,4 s eram trabalho** (produto de matriz, BM25, RRF). O resto era carregar o JSON de 80 MB, o `.npz` de 175 MB, o modelo de embedding (3–9 s) e o cross-encoder de 1,1 GB (3 s) — a cada chamada, porque cada chamada é um processo novo.

```bash
python motor/servidor.py            # fica no ar; Ctrl+C para sair
python motor/servidor.py --porta 8766
```

Nada muda para quem chama. O `consultar.py` tenta a porta por 0,1 s antes de carregar qualquer coisa; se o servidor responde, manda o argv e imprime a resposta; senão roda local como sempre e diz na stderr como subir o servidor. `--local` força o caminho antigo; `CONSULTAR_PORTA` ou `--porta` mudam a porta. A rodada cai para menos de 1 s.

É `http.server` da stdlib, uma requisição por vez, só em `127.0.0.1`. Recarrega o índice semântico quando o mtime do arquivo muda e o BM25 quando o arquivo dele muda, então reindexar não pede reinício.

---

## Onde a busca erra, e contra quem

O `avaliar_dominio.py` diz **quanto** acerta. O `diagnosticar.py` diz **o que impede** de acertar — que é a pergunta que aponta o conserto.

```bash
python diagnosticar.py              # semântico puro
python diagnosticar.py --categoria  # com o recorte do alvo
python diagnosticar.py --n 10       # detalha 10 erros, nomeando quem venceu
```

Medido em 09/09/2026, 178 documentos, 53 perguntas:

| Família de erro | sem recorte | com `--categoria` |
|---|---|---|
| `alvo-invisivel` (alvo fora do top-50) | **0** | **0** |
| `distrator-de-outra-categoria` | 14 | 2 |
| `distrator-vizinho` (mesma categoria do alvo) | 4 | 8 |

**Zero alvo invisível muda a estratégia.** O documento certo está sempre entre os 50 primeiros: não falta recuperação, falta ranqueamento. Isso descarta, antes de gastar um dia em qualquer uma, chunk maior, mais candidatos e troca do modelo de embedding — as três atacam recuperação. E nomeia a causa real: uns poucos livros genéricos vencem perguntas de vendas, posicionamento e copy indistintamente.

**Régua de ruído: com 53 perguntas, ±3 acertos não significa nada.** Mudança que não passa disso não é mudança.

### Três ideias que esse diagnóstico sugeriu, e as três falharam

Ficam registradas porque as duas pareciam certas na entrada.

**Contexto na passagem** (`semantico.py indexar --contexto titulo`, que continua no código para o resultado seguir reproduzível). Um trecho de 60 palavras perde a identidade do livro, então prefixe título e capítulo antes de embutir — de graça, já que o frontmatter existe. Resultado: 35 → 29/53 com `--categoria`, MRR 0,768 → 0,708. Ele faz exatamente metade do que se esperava: o distrator de outra categoria cai de 2 para 0, porque o título ancora o livro. Só que, dentro da categoria, todo trecho passa a dividir um prefixo da mesma vizinhança semântica, e o que os separava se dilui. Como o fluxo recomendado já usa `--categoria`, a metade que ajuda é redundante e a metade que atrapalha é o que sobra.

**Mais candidatos para o reranker** (`--topo 100`, `--topo 200`). O reranker não recebe documentos, recebe as N passagens mais próximas por cosseno — então um alvo que está sempre no top-50 *de documentos* ainda poderia não chegar ao cross-encoder, se poucas passagens entupissem o topo da lista. Medido: com `--categoria`, topo 50 e topo 100 empatam em 42/53, e topo 200 cai para **37/53**, com MRR de 0,839 para 0,810. O alvo já estava chegando ao cross-encoder; candidato a mais só aumenta a chance de um trecho plausível-e-errado tirar a nota mais alta. O padrão continua 50.

**Correção de hubness** (CSLS, sem reindexar). Livro que é vizinho de tudo é a assinatura de hubness em alta dimensão, e a correção clássica desconta de cada trecho sua similaridade média com uma amostra do corpus. Com a semente 42 deu 18 → 24/53 e ia ser adotada. Com as sementes 7, 1234 e 99 deu 18, 17 e 17, e o MRR caiu de 0,514 para ~0,477. O ganho era da amostra, não do método. **Varra a semente antes de acreditar num resultado de recuperação.**


### Quanto vale o reranker, agora que o corpus dobrou

| Modo | 77 documentos (07/09) | 178 documentos (09/09) |
|---|---|---|
| semântico + `--categoria` | 37/53 · MRR 0,806 | 35/53 · MRR 0,768 |
| semântico + rerank + `--categoria` | 43/53 · MRR 0,869 | **42/53 · MRR 0,839** |

Cada documento novo também é um distrator novo, e a precisão caiu nas duas linhas. Mas **o reranker absorve o crescimento**: dobrar o corpus custou dois acertos sem ele e um com ele. Esse é o argumento mais forte a favor dos ~6 s por consulta — não o número absoluto, e sim degradar mais devagar conforme a estante cresce.


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

`vendas` · `marketing` · `copy-persuasao` · `posicionamento-negocio` · `ux-conversao` · `design-arte` · `engenharia-software` · `frontend` · `python` · `rust` · `ia-llm` · `agentes-llm` · `dados-ml` · `ciencia-cognitiva` · `financas-investimentos` · `idiomas` · `seguranca-llm` · `seguranca-ofensiva` · `treino-endurance` · `matematica` · `busca-recuperacao` · `mercado-setorial` · `geral`

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
| pool da fusão, cartões por rodada, pesos do Rocchio | `consultar.py` (`POOL`, `PALAVRAS_CARTAO`, `ALFA`/`BETA`/`GAMA`) |
| o que conta como bloco de bibliografia | `fatiar.py` (`separar_referencias`, `_MARCA_BIBLIO`) |
| porta do servidor | `servidor.py` / `CONSULTAR_PORTA` |
| onde fica a base | `raiz.py` |

---

## Limites honestos

- **Tabela vira sequência de números.** Fórmula matemática vira ruído. PDF de duas colunas pode embaralhar a ordem de leitura. Isso é limite estrutural, não bug a ser corrigido.
- **A classificação por categoria é casamento de palavra-chave, determinística. Erra.** Confie na busca, que varre o texto todo, e não na categoria.
- **O grafo mede vocabulário compartilhado**, então às vezes agrupa por idioma em vez de por tema.
- **A primeira indexação é lenta** — cerca de 40 minutos de CPU para ~90 mil passagens. Depois é incremental, e livro novo custa segundos.
- **Toda chamada de CLI paga 8–19 s de carga de modelo** se o `servidor.py` não estiver no ar. O trabalho em si é menos de meio segundo.
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
| `consultar` | consult (cards, then feedback) |
| `servidor` | resident server |
| `--sessao` / `--abrir N` / `--mais N` | session / open card N / more chapters of card N's document |
| `--sim` / `--nao` | relevant / not relevant (Rocchio) |
| `--sem-recorte` / `--sem-bm25` / `--sem-rerank` | no filter / no BM25 fusion / no reranker |
| `--local` / `--porta` | skip the server / server port |
| `--sem-indexar` | do not reindex after processing |
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
