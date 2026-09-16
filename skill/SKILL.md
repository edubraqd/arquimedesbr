---
name: arquimedesbr
description: Consults the user's personal library of books and papers, converted to per-chapter markdown with BM25 + semantic search (arquimedesbr). Use BEFORE writing sales copy, cold outreach, a proposal, pricing, positioning, landing-page or UX/CRO text, and before deciding software architecture, React, Rust, LLM/AI, ML/statistics or training/nutrition questions. Also whenever the user asks "what do the books say", "check the library", "back this up with a source", "do we have material on X" (pt-BR: "o que os livros dizem", "consulta a base", "embasa isso", "tem material sobre X"). Also for adding a new document to the library.
---

# arquimedesbr — the personal library

A shelf of books and papers already converted into agent-readable markdown. It
lives **outside** any repository, on a local disk, and works for **any project**.

The root is `$ARQUIMEDES_RAIZ`, or `~/Arquimedes` if that is unset. Every command
below also accepts `--raiz <path>`. In the examples, replace `<motor>` with the
path to this repo's `motor/` directory.

```
<root>/
  MAPA.md             <- one card per document: language, size, distinctive concepts
  INDEX.md            <- catalog: categories, documents, link to each table of contents
  nao-processado/     <- inbox (drop PDF/DOCX/TXT here)
  processado/         <- original, after successful conversion
  falhas/             <- yielded no text (scanned without OCR, corrupted)
  markdown/<category>/<document>/INDEX.md + NN-chapter.md
  manifesto.json      <- state by sha256: title, category, pages, words
  GRAFO.md            <- communities and bridges between documents
  graphify-out/       <- knowledge graph, when built
```

## Don't know where to start? `MAPA.md`

One page with a card per document — language, size, and **the concepts only that
document carries** (TF-IDF against the rest of the library, not a model-written
summary). Use it to choose where to look before looking.

Every chapter carries, in its frontmatter:

| Field | For |
|---|---|
| `assunto` | what it is about — filled in for chapters the PDF only named "Trecho 4" |
| `termos` | concepts that distinguish this chapter **from its siblings in the same book** |
| `idioma` | which language to ask in |
| `util` | `nao` = support chapter, already excluded from search |

Maintaining those fields:

```bash
python <motor>/rotular.py --seco   # show the labels it would assign
python <motor>/rotular.py          # write them and rebuild MAPA.md
```

## Consult order — do not skip a step

### 0. Cut the corpus before choosing the method

This decides more than the method does.

| Filter | When |
|---|---|
| `--categoria <cat>` | the question has an obvious address. **This is what pays.** objection and closing → `vendas`; price and business model → `posicionamento-negocio`; headline and sales letter → `copy-persuasao`; landing page and forms → `ux-conversao` |
| `--dominio comercial` | copy, price, proposal, positioning, UX — when you cannot pin the category |
| `--dominio tecnico` | architecture, stack, model, metric |
| `--dominio pessoal` | whatever the user put there |

Measured 2026-09-07 with the 53 questions in `gabarito.py` against the full
index, at document level (`avaliar_dominio.py`), on a 77-document library:

| Method | hit@1 | hit@3 | MRR |
|---|---|---|---|
| BM25 bilingual | 8/53 | 39/53 | 0.456 |
| BM25 + `--dominio` | 16/53 | 42/53 | 0.547 |
| BM25 + `--categoria` | 32/53 | 47/53 | 0.746 |
| semantic | 20/53 | 34/53 | 0.543 |
| semantic + `--dominio` | 21/53 | 36/53 | 0.567 |
| semantic + `--categoria` | 37/53 | 46/53 | 0.806 |
| semantic + rerank | 29/53 | 41/53 | 0.669 |
| semantic + rerank + `--dominio` | 32/53 | 43/53 | 0.710 |
| **semantic + rerank + `--categoria`** | **43/53** | **48/53** | **0.869** |

**`--dominio` barely helps semantic search**: 20 → 21 without the reranker,
29 → 32 with. The embedding already separates domains on its own. What carries
is `--categoria`: 29 → 43 with the reranker, and on its own it is worth more
than the reranker itself (37/53 without rerank versus 29/53 with rerank and no
filter).

In BM25 it is the opposite: `--dominio` doubles hit@1 (8 → 16), because lexical
search collides terms across domains easily.

**Always ask for `--passagens`.** Search compares 60-word passages — the size the
model separates best — but returns the **~420-word window around** the hit,
aligned to sentence boundaries (`--janela N` changes it). That usually answers
the question without opening the chapter:

```bash
python <motor>/semantico.py "how to answer that it is too expensive" --rerank --categoria posicionamento-negocio --passagens
```

**Pass `--categoria` yourself.** Guessing the category from the question's
embedding was measured and does not pay (29 → 30/53): the centroid gets it right
first try only 52% of the time. You, with the conversation's context, do much
better — and that is where the single biggest gain in this search comes from.

The numbers are a **ceiling**: they use the target's category, so they measure
the gain of choosing correctly. Getting the domain wrong is hard; getting the
category wrong is easy — when torn between two categories, use `--dominio`
instead of guessing.

The map lives in `motor/dominio.py` and can be remapped without editing code via
a `dominio.json` at the root of the library. A category that exists in the
library and belongs to no domain is included in **all** of them — so a new
document never silently disappears.

### 1. Cheap first: cards, then open only what you need

`consultar.py` is the token-lean path and should be the first call. It returns
6 cards of ~25 words each (~280 words total) instead of the ~720 words that
three `--passagens` results cost. Measured on the 53-question ground truth:
**the target is among those 6 cards in 51 of 53 questions.** You do not need it
ranked first — you need to see it, and you almost always do.

```bash
python <motor>/consultar.py "how to answer that it is too expensive" --tambem "price objection" --categoria vendas
```

**Always pass `--tambem` with the question in the other language** (English if
you wrote it in Portuguese, and vice versa). The engine sums the two embeddings
and runs BM25 on both strings. Measured on 140 questions it is worth +10 on
hit@1 and +13 on hit@6 (62 → 72, 117 → 130) for no cost at all: you already
know both languages, and most shelves are mostly English. Each round then fuses
the 30 best documents by vector with the 30 best by BM25 (reciprocal rank) and
reranks the final 6 with the cross-encoder; the fusion itself is worth +2 / +3
/ 0 on top of `--tambem`, inside the noise. `--sem-bm25` turns it off; there is
no reason to.

**Read all six cards before choosing.** Card 1 is right in about half the
questions; the six together in nine out of ten. Opening the first without
reading the rest throws away the difference.

Then act on what you see — three exits, and only three:

```bash
python <motor>/consultar.py --sessao <id> --abrir 2        # full window, that card only
python <motor>/consultar.py --sessao <id> --mais 2         # other chapters of card 2's document
python <motor>/consultar.py --sessao <id> --sim 2 --nao 1,3  # none of these: spin again
```

`--mais` is for "right book, wrong chapter": it lists the document's other
chapters ranked by the current query, numbered, and any of them can be
`--abrir`-ed. Round 2 never repeats a document already shown — a card seen is a
card spent — so `--mais` is the only way back into a book you have judged.

The second form moves the query with Rocchio (`alpha` 1, `beta` 0.75,
`gamma` 0.15, from *Introduction to Information Retrieval* ch. 9, which is in
the library). It costs no tokens and no network — the query vector is cached in
the session, so the question is not re-embedded.

**Two rounds, never three.** Measured: round 2 adds 5 hits out of 53; round 3
adds zero. If two rounds have not found it, the library probably does not cover
the question — say so instead of spinning. Or you picked the wrong shelf: try
the other `--categoria` before giving up. A category that runs dry is completed
with its domain automatically, with a warning.

**The resident server.** Without it every call pays 8–19 s to load the index
and the two models; the work itself is under half a second. Start it once and
leave it:

```bash
python <motor>/servidor.py
```

`consultar.py` finds it on its own (port 8766, `CONSULTAR_PORTA` to change) and
falls back to running locally when it is not there, saying so on stderr. If you
see that notice repeatedly in a session, start the server.

Use `semantico.py --passagens` below when you already know you want the wide
window for several results at once. For the normal "find the right chapter"
job, `consultar.py` costs about a fifth per candidate.

### 2. Semantic search with the reranker — the wide form

Best measured result. **Never open a whole book to look for something.**

```bash
python <motor>/semantico.py "how to answer that it is too expensive" --rerank --passagens --categoria vendas
```

`--rerank` costs ~6 s per query and is worth it: 20 → 29 first-try hits with no
filter, 37 → 43 with `--categoria`. A cross-encoder reads the question together
with each passage, instead of comparing vectors computed without ever seeing the
question.

**Reranker and corpus cut are not alternatives** — they add up. If only one is
possible, the cut pays more.

To re-measure after changing the corpus or the ranking:

```bash
python <motor>/avaliar_dominio.py --seco   # ~40s, no reranker
python <motor>/avaliar_dominio.py          # ~30min, everything
```

`semantico.py --hibrido` (passage-level fusion, no reranker) is still not
recommended. The document-level fusion `consultar.py` does by default is a
different thing and measures better — see step 1.

### 3. BM25 when the target is literal

Acronym, proper noun, jargon (`FTP`, `EBT`, `useEffect`, `wa.me`). Write the
query **in both languages**: it does not change hit@1 (8/53 either way) but
triples hit@3 (13 → 39) and doubles MRR (0.220 → 0.455), because more than half
of a typical library is in English. Monolingual sometimes hits, but rarely ranks
the target near the top.

```bash
python <motor>/buscar.py "objecao de preco" --tambem "price objection" --n 6 --trechos
```

### 4. Read the document's `INDEX.md` before the chapter

It has the table of contents with page numbers, word counts, and which chapters
were marked out of search. The frontmatter gives `idioma`, `util`, `assunto` and
`termos` — read those before opening the full chapter.

### 5. Read only the chapter that was pointed at

Each file has frontmatter with `titulo`, `autor`, `capitulo`, `paginas`,
`palavras`. A chapter fits in ~8k words on purpose; a whole book does not fit in
context and should not be read.

### 6. The graph, when the question is about relations

"What connects X and Y", "who else talks about this", "which book approaches this
theme from another side".

Free layer, always available — `<root>/GRAFO.md` (communities, strongest links)
and `grafo.json`:

```bash
python <motor>/grafear.py --ponte "pricing"
python <motor>/grafear.py            # rebuild after adding a document
```

It measures shared vocabulary, not semantics — which is why it sometimes groups
by language. Do not conclude thematic kinship from adjacency alone.

Semantic layer: if `<root>/graphify-out/graph.json` exists,

```bash
graphify query "how value pricing connects to sales diagnosis"
graphify path "SPIN Selling" "Gap Selling"
```

If it does not exist, **do not build it unprompted**: it is millions of words of
document, all passing through an LLM. Offer to run it per category
(`graphify <root>/markdown/vendas`) or with `GEMINI_API_KEY` set.

## How to cite

When you use the library, cite **title + chapter + pages** (all in the
frontmatter). Without a citation the user cannot check you. Do not attribute to a
book what it did not say: **if the search found nothing, say the library does not
cover the topic** rather than filling in with general knowledge dressed up as a
source.

## Categories

Defaults, editable in `motor/catalogar.py`:

`vendas` · `marketing` · `copy-persuasao` · `posicionamento-negocio` ·
`ux-conversao` · `design-arte` · `engenharia-software` · `frontend` · `python` ·
`rust` · `ia-llm` · `agentes-llm` · `dados-ml` · `ciencia-cognitiva` ·
`treino-endurance` · `matematica` · `busca-recuperacao` · `mercado-setorial` ·
`geral`

The live list and real counts are in `<root>/INDEX.md` — read them from there,
not from here, when the exact number matters.

## Adding a new document

```bash
cp "path/to/file.pdf" "$ARQUIMEDES_RAIZ/nao-processado/"
cd <motor> && python processar.py
```

Useful variants:

```bash
python processar.py --seco        # only show what it would do
python processar.py --status      # what is in the library, what failed
python processar.py --so-indice   # regenerate INDEX.md without reprocessing
```

Formats: `.pdf`, `.docx`, `.txt`, `.md`. Duplicates are detected by sha256 — the
same file never enters twice. After adding a document, update the two derived
layers:

```bash
python <motor>/semantico.py indexar   # incremental, only what changed
python <motor>/rotular.py             # subject/terms + MAPA.md
python <motor>/grafear.py
```

A wrong category (classification is keyword-based, so it errs) is fixed without
reprocessing the PDF:

```bash
python <motor>/processar.py --mover <document-folder> --para <category>
```

A document that does not belong (a language the user does not read, a PDF that
is not the book, poor quality material) leaves like this — the markdown is
deleted, the PDF goes to `removidos/`, and the manifest keeps it from coming back:

```bash
python <motor>/processar.py --remover <folder> --motivo "why it left"
```

**Never remove on your own initiative.** Suggest it, and wait for the user.

Scanned PDFs enter by themselves when Tesseract is installed: OCR fires on any
page with no text, at roughly 0.5 s per page.

## Maintenance

A new rule (language detection, discarding support chapters) applies without
reopening a PDF:

```bash
python <motor>/processar.py --revisar --seco   # what would change
python <motor>/processar.py --revisar
cd <motor> && python -m unittest test_motor    # 159 tests
```

`--revisar` also cuts the bibliography out of every chapter that ends with one
(`References`/`Bibliography` up to the next heading that is not an entry) into
`<chapter>.referencias.md`, marked `util: nao`. Reference entries used to
compete with prose as passages.

`processar.py` reindexes on its own after writing markdown (incremental,
atomic, with backup); `--sem-indexar` skips it. If a chapter on disk is newer
than the index, searches print `indice semantico desatualizado` on stderr and
carry on — run `python <motor>/semantico.py indexar` when you see it.

The semantic index is keyed by a hash of the body, so a frontmatter-only
`--revisar` does **not** force re-embedding anything.

## Honest limits

- Several PDFs in a library are **excerpts**, not the complete book. `INDEX.md`
  shows the real page count; check it before claiming a book "does not cover" a
  topic.
- Category classification is deterministic keyword matching. It errs. Use the
  search, which scans the whole text, not the category.
- Tables become sequences of numbers, formulas become noise, and two-column PDFs
  can scramble reading order. Structural, not a bug.
- The library is an **external reference**. It knows nothing about the user's
  projects; do not treat what is in it as a decision taken in any project.
