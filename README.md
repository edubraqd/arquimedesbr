# arquimedesbr

**Turn your own library of books and papers into something a coding agent can actually read.**

[Português](LEIAME.md) · English

A PDF is a wall. An agent that opens one either blows its context window on 400 pages or reads nothing. `arquimedesbr` converts your documents into markdown sliced by chapter, indexes them lexically and semantically, and gives the agent a search that returns the *right 400 words* — with title, chapter and page numbers, so every claim stays checkable.

No LLM in the pipeline. No network calls. No API bill. Everything runs locally.

```bash
python motor/consultar.py "how do I answer when the client says it is too expensive" --tambem "price objection" --categoria vendas
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

Six cards of ~25 words. The agent reads them, opens the one it wants (`--abrir 1`, ~420 words), or tells the engine which ones did not serve and gets six others — with no new embedding and no tokens spent. Under 1 s per round with the [resident server](#the-resident-server) up.

---

## Table of contents

- [Why this exists](#why-this-exists)
- [Two folders, and why they are separate](#two-folders-and-why-they-are-separate)
- [About the books](#about-the-books)
- [Install](#install)
- [Adding documents](#adding-documents)
- [Searching](#searching)
- [What was measured](#what-was-measured)
- [Consulting cheaply: cards first, then feedback](#consulting-cheaply-cards-first-then-feedback)
- [Where the search fails, and to what](#where-the-search-fails-and-to-what)
- [Using it from Claude Code (the skill)](#using-it-from-claude-code-the-skill)
- [Customizing categories and domains](#customizing-categories-and-domains)
- [Honest limits](#honest-limits)

---

## Why this exists

RAG tutorials usually assume you want a chatbot over a corpus. This is not that. This is a **reference shelf for an agent that is doing something else** — writing copy, choosing an architecture, pricing a proposal — and needs to check what a specific book says before it commits.

Three design choices follow from that:

1. **Chapters, not documents.** A chapter fits in context (~8k words target). A book does not. The unit of reading is the chapter; the unit of *searching* is a 60-word passage inside it.
2. **Citations are mandatory.** Every chapter file carries `titulo`, `autor`, `capitulo`, `paginas` in its frontmatter. If the agent cannot cite it, the agent should say the library does not cover it — not fill the gap with general knowledge dressed up as a source.
3. **Zero recurring cost.** Extraction is PyMuPDF. Classification is keywords. Embeddings are a local MiniLM via `fastembed`. Nothing phones home.

---

## Two folders, and why they are separate

This is the part people get wrong on the first run, so it comes before install.

```
arquimedesbr/          <- THIS REPO. the engine. code only. goes on GitHub.
  motor/*.py
  skill/SKILL.md
  README.md

~/Arquimedes/          <- YOUR LIBRARY (the "root"). your files. NEVER on GitHub.
  nao-processado/      <- inbox: drop PDF / DOCX / TXT / MD here
  processado/          <- original file, after successful conversion
  falhas/              <- yielded no text (scanned with no OCR, corrupted)
  removidos/           <- documents you removed on purpose; will not come back
  markdown/
    <category>/
      <document>/
        INDEX.md       <- table of contents with page numbers
        01-chapter.md  <- frontmatter + text
        02-chapter.md
  manifesto.json       <- state keyed by sha256 of each original file
  INDEX.md             <- catalog of the whole library
  MAPA.md              <- one card per document: language, size, distinctive concepts
  GRAFO.md             <- communities and bridges between documents
  .indice-busca.json   <- BM25 index
  .indice-semantico.*  <- vectors
```

**The engine is public. The library is yours and stays on your disk.** They are separate directories on purpose: your books are copyrighted material you acquired, and the conversion output is a derivative of them. Publishing the engine is fine. Publishing your `markdown/` is not.

The root is resolved in this order:

1. `--raiz /path/to/library` on any command;
2. the `ARQUIMEDES_RAIZ` environment variable;
3. `~/Arquimedes`.

So you can keep the library on an external drive, a NAS, wherever — the engine never assumes.

---

## About the books

**This repository ships no books, no excerpts, and no indexes.** It is code that processes files you already own.

What goes in:

| Format | Notes |
|---|---|
| `.pdf` | main path. Scanned PDFs go through OCR if Tesseract is installed |
| `.epub` | stdlib only. One "page" per spine document, so slicing lands on real chapter boundaries |
| `.docx` | needs `python-docx` |
| `.txt`, `.md` | passed through, still sliced and catalogued |

What you should feed it: books you bought, papers from arXiv or an open journal, your own notes, manuals, internal documentation, anything you have the right to read. What you should not: material you did not acquire. The tool has no opinion on this and no way to check — that judgment is yours, and the license disclaims warranty for a reason.

Two practical notes learned the hard way:

- **Many PDFs floating around are excerpts, not the full book.** The generated `INDEX.md` shows the real page count. Check it before concluding that a book "does not cover" a topic — it may simply not be all there.
- **Duplicates are caught by sha256**, so the same file under a different name never enters twice. A different *edition* of the same book will enter twice, because it is in fact a different file.

---

## Install

Requires **Python 3.10+**.

```bash
git clone https://github.com/edubraqd/arquimedesbr.git
cd arquimedesbr
pip install -r requirements.txt
python instalar.py
```

`instalar.py` is optional and does nothing clever — it creates `~/Arquimedes/{nao-processado,processado,falhas,removidos,markdown}` and copies `skill/SKILL.md` into `~/.claude/skills/arquimedesbr/`. Run it with `--raiz` to put the library somewhere else, or skip it and `mkdir` yourself.

Set the root once so you do not repeat `--raiz`:

```bash
export ARQUIMEDES_RAIZ="$HOME/Arquimedes"
```

```powershell
$env:ARQUIMEDES_RAIZ = "$HOME\Arquimedes"
```

### Optional: OCR for scanned PDFs

Install the Tesseract binary (`winget install tesseract-ocr.tesseract`, `brew install tesseract`, `apt install tesseract-ocr`) plus `pytesseract` and `pillow`. Extra language files can live in `motor/tessdata/` — the engine points `TESSDATA_PREFIX` at that folder when it exists, which avoids needing admin rights to write into the system install. Cost is roughly 0.5 s per page with 8 threads.

Without Tesseract everything still works; a scanned PDF simply lands in `falhas/`.

### Verify

```bash
python -m unittest discover -s motor -p "test_*.py"
```

159 tests. They use temporary folders only, download no model, and open no socket except the loopback one the resident-server tests bind on a free port.

---

## Adding documents

```bash
cp ~/Downloads/some-book.pdf "$ARQUIMEDES_RAIZ/nao-processado/"
```

```bash
cd motor
python processar.py
```

Useful variants:

```bash
python processar.py --seco
python processar.py --status
python processar.py --limite 3
python processar.py --so-indice
```

`--seco` is a dry run that shows the chapters it would cut and writes nothing. `--status` reports what is in the library and what failed. `--so-indice` rebuilds `INDEX.md` from the manifest without reprocessing anything.

The pipeline, in one screen:

```
nao-processado/file.pdf
   |
   v  extrair.py    PyMuPDF reads font size and position -> headings become "##".
   |                Strips repeated headers/footers, orphan page numbers,
   |                line-break hyphenation and ligatures. Empty page -> OCR.
   |
   v  fatiar.py     Slices by chapter using the PDF bookmarks. No bookmarks ->
   |                detects chapter starts by FONT SIZE, and only accepts the
   |                detection if it covers the whole book; otherwise slices by
   |                page up to a size target, so each slice still records a real
   |                page range and citations stay checkable.
   |                Target 8k words, min 400 (merges), max 12k (splits).
   |
   v  qualidade.py  Detects language (function-word profile: pt/en/es/fr/it/de/id)
   |                and flags worthless chapters: copyright pages, tables of
   |                contents, indexes, back-matter sales pages, degenerate text.
   |
   v  catalogar.py  Assigns a category by keyword (filename weighs more than
   |                body), writes frontmatter and three levels of INDEX.md.
   |
   v  rotular.py    Names chapters the PDF only called "Trecho 4", using the
                    internal heading or TF-IDF against its siblings in the same
                    book. Writes `assunto` and `termos`, rebuilds MAPA.md.
```

`processar.py` now reindexes on its own after touching the markdown — incremental, atomic (the old index stays until the new one is written), with a backup. `--sem-indexar` skips it and prints the command instead; `--seco` never indexes. The other derived layers are still separate:

```bash
python rotular.py
python grafear.py
```

The index records the mtime of every chapter it embedded. If any `.md` under `markdown/` is newer than that, or is missing from it, `consultar.py` and `semantico.py` print `indice semantico desatualizado (N novos, M alterados)` on stderr and carry on — a warning, not a refusal, because a search on a slightly stale index is still better than none. An index built before this check gets its stamp on the next `indexar`.

The semantic index is **keyed by a hash of the chapter body, not mtime**. That matters: fixing a category or writing a language field rewrites the frontmatter of hundreds of files. Keyed by mtime, each such fix would re-embed the whole library (~40 min of CPU) without a single word of text having changed.

### Curation

Keyword classification gets things wrong. Fix it without reprocessing the PDF:

```bash
python processar.py --mover <document-folder> --para <category>
python processar.py --remover <document-folder> --motivo "why it left"
python processar.py --revisar --seco
python processar.py --revisar
```

`--remover` deletes the markdown, moves the original to `removidos/`, and records it in the manifest so it does not come back on the next run. `--revisar` applies new rules (language detection, chapter discards) across the whole library in seconds, without reopening a single PDF.

Since 2026-09-16 `--revisar` also **cuts the bibliography out of each chapter**. A paper or a technical chapter ends with pages of references, and every entry became a passage competing with the prose: measured on one shelf, 289 `util: sim` chapters carried 538k words of references. `fatiar.separar_referencias` finds the last `References`/`Bibliography` heading, keeps going until the next heading that does not look like a bibliography entry (no year, no `et al.`, no DOI, no URL — because 148 of the 289 had an appendix *after* the references that belongs back in the body), and moves the block to `<chapter>.referencias.md` with `util: nao`. The chapter keeps its citation; the references stop polluting the index. On that shelf the pass separated 292,950 words in 261 blocks and 13 chapters that had been wrongly discarded as "index" came back.

---

## Searching

**Cut the corpus before you choose the method.** This decides more than the method does.

| Filter | When |
|---|---|
| `--categoria <cat>` | the question has an obvious address. **This is what pays.** |
| `--dominio comercial` | copy, pricing, proposals, positioning, UX |
| `--dominio tecnico` | architecture, stack, models, metrics |
| `--dominio pessoal` | whatever you put there |

Then, in order:

**1. `consultar.py` — the door.** Cards first, the wide window only for the card you pick. Write the question in both languages when the shelf is: the engine embeds both strings and runs BM25 in both. See [Consulting cheaply](#consulting-cheaply-cards-first-then-feedback).

```bash
python consultar.py "how to answer that it is too expensive" --tambem "price objection" --categoria vendas
```

**2. Semantic + reranker — the wide form**, when you already know you want ~420 words for several results at once.

```bash
python semantico.py "how to answer that it is too expensive" --rerank --passagens --categoria vendas
```

`--rerank` costs ~6 s and is worth it: a cross-encoder reads the question together with each passage, instead of comparing vectors computed without ever seeing the question.

`--passagens` is the small-to-big trick. Search compares 60-word passages — measured to be the size the model separates best — but returns the **~420-word window around the hit**, aligned to sentence boundaries (`--janela N` changes it). You usually get the answer without opening the chapter at all.

**3. BM25 alone when the target is literal** — an acronym, a proper noun, jargon (`FTP`, `useEffect`, `borrow checker`). `consultar.py` already fuses BM25 in; `buscar.py` is for when you want *only* the lexical hits. Query in **both languages**:

```bash
python buscar.py "objecao de preco" --tambem "price objection" --n 6 --trechos
```

**4. Read the document's `INDEX.md`** before the chapter — it has the table of contents with page numbers and word counts.

**5. Read only the chapter the search pointed at.** Never the whole book.

**6. The graph, for questions about relations** — "what connects X and Y", "who else talks about this":

```bash
python grafear.py --ponte "pricing"
python grafear.py
```

The graph measures shared vocabulary, not semantics — it will sometimes cluster by language. Do not read kinship into mere adjacency.

**On fusing BM25 with the vectors.** An earlier version of this README said *do not use `--hibrido`*, because fusion had measured worse than semantic+rerank alone. That verdict came from **12 questions over 25 documents** — below the noise floor this same README warns about. Re-measured on 2026-09-16 with 140 questions and 178 documents, fusing the top-30 documents of each ranking by reciprocal rank and reranking the top 6 is the best or tied-best mode on hit@3 and hit@6, so `consultar.py` does it by default (`--sem-bm25` turns it off). The table is in the next section. The `--hibrido` flag of `semantico.py` was never the same thing — it fused at passage level, with no reranker — and it is still not recommended.

---

## What was measured

Numbers below come from `avaliar_dominio.py` against a 53-question ground truth (`gabarito.py`), scored at document level, over a real library of 77 documents / 818 chapters, on 2026-09-07.

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

Three readings that matter:

1. **`--categoria` carries more than the reranker does.** Alone it scores 37/53; the reranker alone scores 29/53. Together, 43/53. They add up — they are not alternatives.
2. **`--dominio` barely helps semantic search** (20 to 21 without rerank, 29 to 32 with). The embedding already separates domains. In BM25 it is the opposite — it doubles hit@1 (8 to 16), because lexical search collides terms across domains easily.
3. **Query in both languages for BM25.** hit@1 does not move (8/53 either way) but hit@3 triples (13 to 39) and MRR doubles. Monolingual sometimes hits, rarely ranks the target near the top.

Two caveats, stated plainly:

- These numbers use the *target's* category, so they are a **ceiling**: they measure the gain available to someone who picks the filter correctly. Getting the domain wrong is hard; getting the category wrong is easy. When torn between two categories, use `--dominio` instead of guessing.
- They were measured on **one specific library with one specific set of questions.** Yours will differ. Write your own `gabarito.py` and re-run `avaliar_dominio.py` — that is the point of shipping the evaluator.

### What was measured and did *not* work

Kept here so nobody spends a day rediscovering it.

| Idea | Measured result |
|---|---|
| **Auto-predicting the category** (`prever_categoria.py`) | 29 to 30/53. The right category is the top guess only 52% of the time, and filtering on a wrong guess drops hit@3 (38 to 35). Let a human — or the agent, which has conversation context — pass `--categoria`. |
| **e5-large instead of MiniLM** | worse MRR, and 127 min to index versus 13 |
| **Hybrid rank fusion** (`semantico.py --hibrido`) | 0.645 versus 0.713 for semantic+rerank alone — measured on 12 questions, which is noise. **Reversed on 2026-09-16** for the document-level fusion `consultar.py` does; see [the 16/09 table](#since-2026-09-16-bm25-fused-both-languages-one-card-per-document). |
| **Recovering 1.3M lost words** (a real extraction bug) | 43 to 44/53. The recovered content is real, but the ground truth does not ask about it. Fixing the corpus did not move the metric; better targeting did. |

### The extraction canary

Every ingested PDF is checked against PyMuPDF's own raw `get_text()`. Below 80% coverage it warns immediately and records the ratio in the manifest (`razao_extracao`).

It exists because a real failure went unnoticed for months: discarded whitespace spans were gluing together text from LaTeX PDFs, and 13 documents entered with 22–74% of their content and no error on screen. If you are building something like this, build the canary first.

### Discard heuristics need a ratio, not a count

The pipeline drops chapters that are really tables of contents. The first rule counted runs of leader dots (`. . . . . 54`) and discarded above 12.

That rule threw away 23 of the 34 chapters of a 735-page scanned copy of *Security Analysis* — roughly 180,000 words of real prose about bonds and depreciation. The book is full of financial tables, and OCR turns each table's leader dots into a run.

Measured across the 27 chapters the rule had ever fired on: a genuine table of contents spends **15.8%–48.7%** of its characters on dotted runs; a content chapter with tables never passes **5.5%**. The threshold is now that fraction, not the count.

The general lesson, which cost a day: **an absolute count is a threshold on document length in disguise.** Any rule of the form "more than N occurrences" will fire on long documents and miss short ones. Make it a ratio and measure where the two populations actually separate.


## Consulting cheaply: cards first, then feedback

`semantico.py --passagens` returns a ~420-word window per result. Good to read, expensive to decide with: the agent spends roughly 1,700 tokens only to discover that the second result was the one it wanted. `consultar.py` inverts that.

```bash
python motor/consultar.py "how to answer that it is too expensive" --categoria vendas
python motor/consultar.py --sessao a1b2 --abrir 2
python motor/consultar.py --sessao a1b2 --sim 2 --nao 1,3
```

| | words | per candidate |
|---|---|---|
| `semantico.py --passagens --n 3` | 723 | 241 |
| `consultar.py --n 6` | 279 | **46** |

Twice the candidates for 39% of the text, and **the target is among those 6 cards in 51 of 53 questions.** The agent does not need it ranked first, it needs to see it — and the wide window is fetched only for the card it picks.

### The second round is Rocchio

```
q' = alpha*q + beta*mean(relevant) - gamma*mean(non-relevant)
```

`alpha` 1, `beta` 0.75, `gamma` 0.15 — from *Introduction to Information Retrieval*, ch. 9, which happens to sit in the library this engine indexes. The book is explicit about the asymmetry ("positive feedback turns out to be much more valuable than negative feedback, and so most IR systems set gamma < beta") and about the precondition: the initial query must already be close to the target.

**That precondition is measured here, not assumed**: across 53 questions the right document never fell outside the top 50. This is why relevance feedback pays where contextual prefixes, hubness correction and more reranker candidates all failed — those three attacked retrieval, which was never the bottleneck.

Rocchio is vector arithmetic: no network, no tokens, milliseconds. The query vector is cached in the session, so a second round does not re-embed the question.

**Two rounds, never three.** Measured: round 2 lifts hit@1 from 28 to 33 of 53; round 3 adds nothing. If two rounds have not found it, the library probably does not cover the question.

### Since 2026-09-16: BM25 fused, both languages, one card per document

Measured on 140 questions, category chosen by an agent reading only the question, cross-encoder on the final 6 (`avaliar_consultar.py`). The index was slightly stale when this ran, so **compare rows with each other, not with other tables in this file**:

| mode | hit@1 | hit@3 | hit@6 | MRR |
|---|---|---|---|---|
| dense, query in Portuguese only (the old `consultar.py`) | 67 | 107 | 121 | 0.625 |
| dense, vector = PT + EN | 72 | 109 | **129** | 0.660 |
| BM25 bilingual → rerank | **79** | 112 | 126 | **0.695** |
| RRF of dense-30 ∪ BM25-30 → rerank 6 | 74 | **114** | 127 | 0.674 |
| RRF with PT + EN (**the default now**) | 74 | 112 | **129** | 0.674 |

Four things changed in `consultar.py` because of it:

- **`--tambem "<the question in English>"`.** The engine sums the two embeddings and runs BM25 on both strings. It is the cheapest gain on the shelf — +8 on hit@6 for zero cost, because the agent writing the query already knows both languages and 135 of these 178 documents are in English. Skip it only if your whole shelf is in one language.
- **Every round fuses the top-30 documents by vector with the top-30 by BM25** through reciprocal rank (`fundir_rrf`), then reranks the 6. That BM25 wins hit@1 outright on a ~15M-token corpus matches what *BM25 Wins at Scale* (arXiv 2607.26497) predicts; the fusion keeps the dense side's hit@6.
- **Round 2 never repeats a document already shown.** The old dedup was per passage: after the query moved, another chapter of the same book became its best passage and a book you had just judged came back as news. A card seen is a card spent.
- **`--mais <n>`** lists the other chapters of the document on card *n*, ranked by the current query, numbered so they can be opened. It covers the case the dedup would otherwise hide: the right book, wrong chapter.

Two smaller ones: a category that runs out of candidates is completed with its domain, with a warning; and `--abrir` / `--estado` no longer load the index or the model — the session file keeps the path and offset of each card, which also shrank it from 5 MB to 12 KB.

### The resident server

Measured on 2026-09-16: each `consultar.py` call took 8–19 s, of which **~0.4 s was work** (matrix product, BM25, RRF). The rest was loading the 80 MB JSON, the 175 MB `.npz`, the embedding model (3–9 s) and the 1.1 GB cross-encoder (3 s) — every call, because every call is a new process.

```bash
python motor/servidor.py            # stays up; Ctrl+C to stop
python motor/servidor.py --porta 8766
```

Nothing changes for the caller. `consultar.py` probes the port for 0.1 s before loading anything; if the server answers it sends its argv and prints the reply, otherwise it runs locally as before and says on stderr how to start the server. `--local` forces the old path; `CONSULTAR_PORTA` or `--porta` change the port. Rounds drop to under 1 s.

It is stdlib `http.server`, one request at a time, bound to `127.0.0.1` only. It reloads the semantic index when the file's mtime changes and the BM25 index when its file changes, so a reindex does not need a restart.

---

## Where the search fails, and to what

`avaliar_dominio.py` says **how much** it gets right. `diagnosticar.py` says **what stops it** — which is the question that tells you what to fix.

```bash
python diagnosticar.py              # semantic only
python diagnosticar.py --categoria  # with the target's filter
python diagnosticar.py --n 10       # detail 10 failures, naming what beat the target
```

Measured 2026-09-09 over 178 documents and 53 questions:

| Failure family | no filter | with `--categoria` |
|---|---|---|
| `alvo-invisivel` (target outside top-50) | **0** | **0** |
| `distrator-de-outra-categoria` (winner from another category) | 14 | 2 |
| `distrator-vizinho` (winner from the target's own category) | 4 | 8 |

**Zero invisible targets changes the strategy.** The right document is always among the first 50: retrieval is not the bottleneck, ranking is. That rules out, before you spend a day on any of them, bigger chunks, more candidates, and swapping the embedding model — all three attack retrieval. And it names the real cause: a handful of generic books win questions about sales, positioning and copy indiscriminately.

**Noise floor: with 53 questions, ±3 hits means nothing.** A change that does not clear that is not a change.

### Three things this diagnosis suggested, all of which failed

Kept because each one looked right on the way in.

**Contextual prefix** (`semantico.py indexar --contexto titulo`, still shipped so the result stays reproducible). A 60-word passage loses its book's identity, so prefix the title and chapter before embedding — free, since the frontmatter is already computed. Result: 35 → 29/53 with `--categoria`, MRR 0.768 → 0.708. It does exactly half of what was hoped: cross-category distractors drop from 2 to 0, because the title anchors the book. But within a category every passage now shares a prefix from the same semantic neighbourhood, and what distinguished them dilutes. Since the recommended workflow already passes `--categoria`, the half that helps is redundant and the half that hurts is what you get.

**More candidates for the reranker** (`--topo 100`, `--topo 200`). The reranker does not receive documents, it receives the top-N passages by cosine, so a target that always ranks inside the top-50 *documents* could still miss the cross-encoder if a few passages crowd the head of the list. Measured: with `--categoria`, topo 50 and topo 100 both score 42/53, and topo 200 scores **37/53** with MRR falling from 0.839 to 0.810. The target was already reaching the cross-encoder; extra candidates only raise the chance that a plausible-but-wrong passage takes the top score. The default stays at 50.

**Hubness correction** (CSLS, no reindex needed). A book that is a neighbour of everything is the signature of hubness in high-dimensional space; the classic fix subtracts each passage's mean similarity to a corpus sample. With random seed 42 it scored 18 → 24/53 and was about to be adopted. With seeds 7, 1234 and 99 it scored 18, 17 and 17, and MRR fell from 0.514 to about 0.477. The gain belonged to the sample, not to the method. **Sweep the seed before believing a retrieval result.**


### What the reranker is worth, now that the corpus doubled

| Mode | 77 documents (07/09) | 178 documents (09/09) |
|---|---|---|
| semantic + `--categoria` | 37/53 · MRR 0.806 | 35/53 · MRR 0.768 |
| semantic + rerank + `--categoria` | 43/53 · MRR 0.869 | **42/53 · MRR 0.839** |

Every document added is also a distractor added, and accuracy fell on both rows. But **the reranker absorbs the growth**: doubling the corpus cost two hits without it and one with it. That is the strongest argument for the ~6 s per query — not the absolute score, but that it degrades more slowly as the shelf grows.


---

## Using it from Claude Code (the skill)

`skill/SKILL.md` installs as a Claude Code skill named **arquimedesbr**. Once installed at `~/.claude/skills/arquimedesbr/SKILL.md`, Claude consults the library on its own before writing copy, pricing something, or picking an architecture — and cites title + chapter + pages.

```bash
mkdir -p ~/.claude/skills/arquimedesbr && cp skill/SKILL.md ~/.claude/skills/arquimedesbr/
```

Then, in any project: `/arquimedesbr`, or just ask "what do the books say about pricing objections?"

The skill body tells the agent the consult order above, the honest limits, and — importantly — **to say the library does not cover a topic rather than answer from general knowledge while implying a source**. That instruction is the difference between a useful shelf and a confident liar.

It works with any agent that reads a system prompt, not only Claude Code. The file is plain markdown; paste it wherever your agent takes instructions.

---

## Customizing categories and domains

Default categories live in `motor/catalogar.py` (`ROTULOS`), and reflect one person's shelf:

`vendas` · `marketing` · `copy-persuasao` · `posicionamento-negocio` · `ux-conversao` · `design-arte` · `engenharia-software` · `frontend` · `python` · `rust` · `ia-llm` · `agentes-llm` · `dados-ml` · `ciencia-cognitiva` · `financas-investimentos` · `idiomas` · `seguranca-llm` · `seguranca-ofensiva` · `treino-endurance` · `matematica` · `busca-recuperacao` · `mercado-setorial` · `geral`

Change them to match your own. Each entry is a label plus the keywords that select it; the filename weighs more than the body.

Domains group categories and can be remapped **without touching code**, via a `dominio.json` at the root of your library:

```json
{
  "comercial": ["vendas", "copy-persuasao", "posicionamento-negocio"],
  "tecnico": ["python", "rust", "ia-llm"],
  "pessoal": ["treino-endurance", "financas-investimentos"]
}
```

A category that exists in the library but in no domain is included in **all** of them — so a newly added document never silently disappears from search.

### Where to change what

| I want to change | File |
|---|---|
| passage size, overlap, embedding model | `semantico.py` (`PASSAGEM_PALAVRAS`, `AVANCO`, `MODELO`) |
| chapter size, slicing rule | `fatiar.py` (`ALVO_PALAVRAS`, `MAX_PALAVRAS`) |
| categories and keywords | `catalogar.py` (`ROTULOS`) |
| heading/footer detection, cleanup | `extrair.py` |
| what counts as a worthless chapter | `qualidade.py` |
| ranking | `buscar.py` (`bm25`, `_PARADAS`) |
| fusion pool, cards per round, Rocchio weights | `consultar.py` (`POOL`, `PALAVRAS_CARTAO`, `ALFA`/`BETA`/`GAMA`) |
| what counts as a bibliography block | `fatiar.py` (`separar_referencias`, `_MARCA_BIBLIO`) |
| server port | `servidor.py` / `CONSULTAR_PORTA` |
| where the library lives | `raiz.py` |

---

## Honest limits

- **Tables become sequences of numbers.** Math formulas become noise. Two-column PDFs can scramble reading order. This is structural, not a bug to be fixed.
- **Category classification is deterministic keyword matching. It errs.** Trust the search, which scans the full text, over the category.
- **The graph measures shared vocabulary**, so it sometimes groups by language rather than by topic.
- **The code and CLI flags are in Portuguese.** `buscar` = search, `processar` = process, `--seco` = dry run, `--raiz` = root, `--categoria` = category. The docs are bilingual; the code was not rewritten, because renaming a working system is how working systems break. A full glossary is in [LEIAME.md](LEIAME.md#glossário-pt--en).
- **First indexing is slow** — roughly 40 minutes of CPU for ~90k passages. After that it is incremental and a new book costs seconds.
- **Every CLI call pays 8–19 s of model loading** unless `servidor.py` is up. The work itself is under half a second.
- **Everything here was built for one person's shelf and then generalized.** Where a default looks arbitrary, it probably encodes a measurement on a corpus that is not yours. Re-measure.

---

## Prior art / credit

The small-to-big retrieval pattern — search small passages, return the window around them — is described in *Building LLMs for Production*, chapter "Advanced RAG Techniques", pp. 220–229.

Built with [Claude Code](https://claude.com/claude-code). Contributions welcome, especially measurements on libraries that look nothing like the one this was tuned on.

MIT licensed. See [LICENSE](LICENSE).
