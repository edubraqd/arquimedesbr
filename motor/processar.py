"""Motor da base de conhecimento.

Le tudo que estiver em `nao-processado/`, converte em markdown fatiado por
capitulo dentro de `markdown/<categoria>/<documento>/`, move o original para
`processado/` (ou `falhas/`) e reescreve o `INDEX.md` da base.

    python processar.py                 # processa a fila inteira
    python processar.py --seco          # mostra o que faria, nao escreve nada
    python processar.py --limite 3      # so os 3 primeiros
    python processar.py --reprocessar   # refaz mesmo o que ja esta no manifesto
    python processar.py --status        # o que tem na base hoje
    python processar.py --so-indice     # regenera INDEX.md a partir do manifesto
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import catalogar  # noqa: E402
import extrair as extracao  # noqa: E402
import qualidade  # noqa: E402
from fatiar import fatiar, slug  # noqa: E402

from raiz import RAIZ_PADRAO  # noqa: E402
# Corte de "nao vale a pena": PDF escaneado da 0 palavras/pagina. Livro com
# muita figura da pouco por pagina e ainda assim e util, entao o total tambem
# conta - so cai em falha quem falha nos dois criterios.
MIN_PALAVRAS_POR_PAGINA = 15
MIN_PALAVRAS_TOTAL = 3000


def sha256(caminho: Path, bloco: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        while chunk := f.read(bloco):
            h.update(chunk)
    return h.hexdigest()


def mover(origem: Path, destino_dir: Path) -> Path:
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / origem.name
    n = 1
    while destino.exists():
        destino = destino_dir / f"{origem.stem}__{n}{origem.suffix}"
        n += 1
    shutil.move(str(origem), str(destino))
    return destino


def arquivar(origem: Path, destino_dir: Path, digest: str) -> Path | None:
    """Move o original para a pasta de destino, ou apaga se ja houver copia igual.

    Sem isso, reenviar o mesmo PDF criava `arquivo__1.pdf`, `__2`... ao lado do
    que ja estava arquivado: medido, 15 copias redundantes e 168 MB.
    """
    destino_dir.mkdir(parents=True, exist_ok=True)
    for existente in destino_dir.glob("*" + origem.suffix):
        if existente.stat().st_size == origem.stat().st_size and sha256(existente) == digest:
            origem.unlink()
            return None
    return mover(origem, destino_dir)


def fila(entrada: Path) -> list:
    itens = [
        p for p in sorted(entrada.rglob("*"))
        if p.is_file() and p.suffix.lower() in extracao.EXTENSOES
    ]
    return itens


def processar_um(caminho: Path, raiz: Path, manifesto: dict, usar_ocr: bool,
                 seco: bool, reprocessar: bool) -> str:
    digest = sha256(caminho)
    registro = manifesto.get(digest)
    if registro and registro.get("status") == "ok" and not reprocessar:
        print(f"  ja na base ({registro['titulo']}) - arquivando original")
        if not seco:
            arquivar(caminho, raiz / "processado" / registro["categoria"], digest)
        return "duplicado"
    if registro and registro.get("status") == "removido" and not reprocessar:
        print(f"  removido antes ({registro.get('motivo', 'sem motivo')}) - nao volta")
        if not seco:
            arquivar(caminho, raiz / "removidos", digest)
        return "removido"

    def progresso(i, total, fase):
        print(f"    {fase} {i}/{total}", flush=True)

    inicio = time.time()
    doc = extracao.extrair(caminho, usar_ocr=usar_ocr, progresso=progresso)
    titulo = catalogar.titulo_de(caminho, doc)
    n_paginas = len(doc.paginas)
    palavras = doc.palavras
    por_pagina = palavras / n_paginas if n_paginas else 0

    if por_pagina < MIN_PALAVRAS_POR_PAGINA and palavras < MIN_PALAVRAS_TOTAL:
        motivo = (
            f"texto insuficiente ({por_pagina:.0f} palavras/pagina, "
            f"{palavras} no total, {n_paginas} paginas)"
        )
        if palavras == 0 and not extracao.ocr_disponivel():
            motivo += " - sem camada de texto; instale o Tesseract e reprocesse"
        print(f"  FALHA: {motivo}")
        manifesto[digest] = {
            "arquivo": caminho.name, "titulo": titulo, "status": "falha",
            "erro": motivo, "paginas": n_paginas, "palavras": palavras,
            "quando": datetime.now().isoformat(timespec="seconds"),
        }
        if not seco:
            mover(caminho, raiz / "falhas")
        return "falha"

    razao, aviso = conferir_extracao(caminho, palavras)
    if aviso:
        print(f"  AVISO: {aviso}")

    amostra = catalogar.amostra_do_doc(doc)
    categoria = catalogar.classificar(caminho, titulo, amostra)
    idioma, confianca = qualidade.detectar_idioma(amostra)
    tipo = qualidade.detectar_tipo(titulo, amostra)
    capitulos = fatiar(doc)
    pasta = slug(titulo)

    meta = {
        "titulo": titulo,
        "autor": doc.autor,
        "categoria": categoria,
        "categoria_rotulo": catalogar.ROTULOS.get(categoria, categoria),
        "idioma": idioma,
        "tipo": tipo,
        "fonte": caminho.name,
        "sha256": digest[:16],
        "total_paginas": n_paginas,
        "total_palavras": palavras,
        "extrator": doc.extrator,
        "extraido_em": datetime.now().date().isoformat(),
    }

    uteis = sum(1 for c in capitulos if qualidade.avaliar(c.titulo, c.md)[0])
    print(
        f"  {titulo} -> {categoria} [{idioma}/{tipo}] | {n_paginas} pag | {palavras} palavras | "
        f"{uteis}/{len(capitulos)} capitulos uteis | {time.time() - inicio:.1f}s"
    )
    if seco:
        for cap in capitulos[:8]:
            print(f"      {cap.ordem:02d} {cap.titulo[:70]} ({cap.palavras} palavras)")
        if len(capitulos) > 8:
            print(f"      ... +{len(capitulos) - 8} capitulos")
        return "seco"

    catalogar.escrever_livro(raiz / "markdown", categoria, pasta, meta, capitulos)
    manifesto[digest] = {
        "arquivo": caminho.name, "titulo": titulo, "autor": doc.autor,
        "categoria": categoria, "pasta": pasta, "status": "ok",
        "idioma": idioma, "idioma_confianca": confianca, "tipo": tipo,
        "paginas": n_paginas, "palavras": palavras, "capitulos": len(capitulos),
        "capitulos_uteis": uteis, "extrator": doc.extrator,
        "razao_extracao": round(razao, 3),
        "quando": datetime.now().isoformat(timespec="seconds"),
    }
    mover(caminho, raiz / "processado" / categoria)
    return "ok"


def _avisar_indice(quantos: int = 0) -> None:
    """Mover ou remover documento deixa o indice semantico apontando para o vazio.

    O indice guarda o caminho de cada passagem, e nem `--mover` nem `--remover`
    o reescrevem. Medido em 07/09: 4 documentos movidos bastaram para 9.185
    passagens (8,7%) ficarem orfas, e as consultas com `--rerank` morriam com
    FileNotFoundError. Reindexar e barato porque a chave e o hash do corpo -
    nada e reembutido, so os caminhos sao reescritos.
    """
    print()
    print("o indice semantico ficou desatualizado. rode:")
    print("    python motor/semantico.py indexar")


def conferir_extracao(caminho: Path, palavras: int, minimo: float = 0.80):
    """Compara o que a extracao rendeu com o texto cru do PDF.

    Existe por causa de uma falha que passou meses sem ninguem ver: spans de
    espaco descartados colavam o texto de PDF em LaTeX, e 13 documentos entraram
    com 22% a 74% do conteudo - sem erro na tela, so um documento quase vazio.
    Medido depois da correcao: a mediana da base e 0,99, e o pior caso legitimo
    (cabecalho, sumario e indice removidos de proposito) fica em 0,81.

    Devolve (razao, aviso). Razao 0 quando nao da para comparar.
    """
    if caminho.suffix.lower() != ".pdf":
        return 0.0, ""
    try:
        import fitz

        with fitz.open(caminho) as doc:
            cru = sum(len(pagina.get_text().split()) for pagina in doc)
    except Exception:
        return 0.0, ""
    return _julgar_extracao(palavras, cru, minimo)


def _julgar_extracao(palavras: int, cru: int, minimo: float = 0.80):
    """Parte pura da conferencia, para poder testar sem abrir PDF."""
    if cru < 1000:
        return 0.0, ""            # escaneado: quem manda e o OCR, nao o cru
    razao = palavras / cru
    if razao >= minimo:
        return razao, ""
    return razao, (
        f"extraiu {razao * 100:.0f}% do texto cru ({palavras} de {cru} palavras)"
        " - possivel perda; confira antes de confiar neste documento"
    )


def recategorizar(raiz: Path, manifesto: dict, pasta: str, nova: str) -> int:
    """Corrige a categoria de um documento ja processado.

    A classificacao automatica e por palavra-chave e erra; a curadoria manual
    precisa de um caminho que ajuste markdown, frontmatter, manifesto e indice
    de uma vez so, sem reprocessar o PDF.
    """
    if nova not in catalogar.ROTULOS:
        print("categoria invalida. use uma de: " + ", ".join(sorted(catalogar.ROTULOS)))
        return 1
    alvo = None
    for digest, item in manifesto.items():
        if item.get("pasta") == pasta and item.get("status") == "ok":
            alvo = (digest, item)
            break
    if alvo is None:
        print(f"pasta '{pasta}' nao esta no manifesto")
        return 1

    digest, item = alvo
    antiga = item["categoria"]
    if antiga == nova:
        print("ja esta nessa categoria")
        return 0

    origem = raiz / "markdown" / antiga / pasta
    destino = raiz / "markdown" / nova / pasta
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        shutil.rmtree(destino)
    shutil.move(str(origem), str(destino))
    for md in destino.glob("*.md"):
        texto = md.read_text(encoding="utf-8")
        texto = texto.replace(f'categoria: "{antiga}"', f'categoria: "{nova}"', 1)
        texto = texto.replace(
            f'categoria_rotulo: "{catalogar.ROTULOS[antiga]}"',
            f'categoria_rotulo: "{catalogar.ROTULOS[nova]}"',
            1,
        )
        md.write_text(texto, encoding="utf-8")

    pdf = raiz / "processado" / antiga / item["arquivo"]
    if pdf.exists():
        mover(pdf, raiz / "processado" / nova)

    item["categoria"] = nova
    manifesto[digest] = item
    catalogar.salvar_manifesto(raiz / "manifesto.json", manifesto)
    catalogar.gerar_indice(raiz, manifesto)
    print(f"{item['titulo']}: {antiga} -> {nova}")
    _avisar_indice()
    return 0


def _reescrever_frontmatter(md: Path, novos: dict) -> None:
    texto = md.read_text(encoding="utf-8")
    if not texto.startswith("---"):
        return
    fim = texto.find("\n---", 3)
    if fim == -1:
        return
    campos = {}
    for linha in texto[3:fim].strip().splitlines():
        if ":" in linha:
            k, v = linha.split(":", 1)
            campos[k.strip()] = v.strip()
    for k in ("util", "motivo_descarte", "idioma", "tipo"):
        campos.pop(k, None)
    campos.update({k: catalogar._yaml(v) for k, v in novos.items()})
    cabeca = "---\n" + "\n".join(f"{k}: {v}" for k, v in campos.items()) + "\n---"
    md.write_text(cabeca + texto[fim + 4:], encoding="utf-8")


def revisar(raiz: Path, manifesto: dict, seco: bool = False) -> int:
    """Recalcula idioma e utilidade sobre o markdown que ja existe.

    Serve para aplicar regra nova sem reabrir PDF: extrair e fatiar sao a parte
    cara, e nada neles mudou. Uma passada completa leva segundos.
    """
    mudou_arquivo = 0
    por_pasta = {i["pasta"]: (d, i) for d, i in manifesto.items()
                 if i.get("status") == "ok" and i.get("pasta")}
    descartados_total = 0

    for pasta, (digest, item) in sorted(por_pasta.items()):
        dir_doc = raiz / "markdown" / item["categoria"] / pasta
        if not dir_doc.exists():
            continue
        capitulos = sorted(p for p in dir_doc.glob("*.md") if p.name != "INDEX.md")
        amostra, descartados, pendentes, rosto = [], [], [], []
        for md in capitulos:
            bruto = md.read_text(encoding="utf-8", errors="replace")
            campos = {}
            corpo = bruto
            if bruto.startswith("---"):
                fim = bruto.find("\n---", 3)
                if fim != -1:
                    for linha in bruto[3:fim].strip().splitlines():
                        if ":" in linha:
                            k, v = linha.split(":", 1)
                            campos[k.strip()] = v.strip().strip('"')
                    corpo = bruto[fim + 4:]
            titulo_cap = campos.get("capitulo", md.stem)
            util, motivo = qualidade.avaliar(titulo_cap, corpo)
            if not util:
                descartados.append((md.name, motivo))
                # o rosto costuma ser descartado como apoio, mas e justamente
                # onde a tese se declara ("Projeto de Graduacao apresentado")
                if len(rosto) < 2:
                    rosto.append(corpo[:6000])
            elif len(amostra) < 6:
                amostra.append(corpo[:12000])
            pendentes.append((md, campos, util, motivo))

        junta = "\n".join(amostra)
        idioma, confianca = qualidade.detectar_idioma(junta)
        tipo = qualidade.detectar_tipo(
            item.get("titulo", ""), "\n".join(rosto + [junta]))

        # segunda passada: o idioma e do documento inteiro, entao so da para
        # gravar no capitulo depois de ler a amostra de todos eles
        for md, campos, util, motivo in pendentes:
            marca_util = "sim" if util else "nao"
            if seco or (campos.get("util") == marca_util
                        and campos.get("idioma") == idioma
                        and campos.get("tipo") == tipo):
                continue
            novos = {"idioma": idioma, "tipo": tipo, "util": marca_util}
            if motivo:
                novos["motivo_descarte"] = motivo
            _reescrever_frontmatter(md, novos)
            mudou_arquivo += 1
        descartados_total += len(descartados)
        marca = "" if item.get("idioma") == idioma else f"  idioma: {item.get('idioma', '?')} -> {idioma}"
        if descartados or marca:
            print(f"{item['titulo'][:58]:58} [{idioma}] "
                  f"{len(capitulos) - len(descartados)}/{len(capitulos)} uteis{marca}")
            for nome, motivo in descartados[:4]:
                print(f"    fora: {nome} ({motivo})")
        if not seco:
            item["idioma"] = idioma
            item["tipo"] = tipo
            item["idioma_confianca"] = confianca
            item["capitulos"] = len(capitulos)
            item["capitulos_uteis"] = len(capitulos) - len(descartados)
            manifesto[digest] = item

    if not seco:
        catalogar.salvar_manifesto(raiz / "manifesto.json", manifesto)
        catalogar.gerar_indice(raiz, manifesto)
    print(f"\n{len(por_pasta)} documentos revisados, {descartados_total} capitulos "
          f"fora da busca, {mudou_arquivo} arquivos atualizados"
          + (" (seco: nada escrito)" if seco else ""))
    return 0


def remover(raiz: Path, manifesto: dict, pasta: str, motivo: str) -> int:
    """Tira um documento da base.

    O markdown e apagado (regeneravel a partir do PDF), o original vai para
    `removidos/` em vez de ser destruido, e o manifesto guarda a decisao para o
    documento nao voltar sozinho na proxima rodada.
    """
    alvo = None
    for digest, item in manifesto.items():
        if item.get("pasta") == pasta and item.get("status") == "ok":
            alvo = (digest, item)
            break
    if alvo is None:
        print(f"pasta '{pasta}' nao esta na base")
        return 1

    digest, item = alvo
    md = raiz / "markdown" / item["categoria"] / pasta
    if md.exists():
        shutil.rmtree(md)

    pdf = raiz / "processado" / item["categoria"] / item["arquivo"]
    destino = None
    if pdf.exists():
        destino = mover(pdf, raiz / "removidos")

    manifesto[digest] = {
        **item,
        "status": "removido",
        "motivo": motivo,
        "quando": datetime.now().isoformat(timespec="seconds"),
    }
    catalogar.salvar_manifesto(raiz / "manifesto.json", manifesto)
    catalogar.gerar_indice(raiz, manifesto)
    print(f"removido: {item['titulo']}")
    print(f"  motivo:   {motivo}")
    print(f"  markdown: apagado ({item.get('capitulos', '?')} capitulos)")
    print(f"  original: {destino if destino else 'nao estava em processado/'}")
    _avisar_indice()
    return 0


def status(raiz: Path, manifesto: dict) -> None:
    ok = [v for v in manifesto.values() if v.get("status") == "ok"]
    falhas = [v for v in manifesto.values() if v.get("status") == "falha"]
    pendentes = fila(raiz / "nao-processado")
    print(f"base:        {raiz}")
    print(f"processados: {len(ok)} documentos, "
          f"{sum(i.get('palavras', 0) for i in ok):,} palavras".replace(",", "."))
    print(f"falhas:      {len(falhas)}")
    print(f"na fila:     {len(pendentes)}")
    por_cat = {}
    for i in ok:
        por_cat[i["categoria"]] = por_cat.get(i["categoria"], 0) + 1
    for cat in sorted(por_cat, key=lambda c: -por_cat[c]):
        print(f"  {cat:26} {por_cat[cat]}")
    for f in falhas:
        print(f"  FALHA {f['arquivo']}: {f.get('erro', '?')}")
    print(f"OCR disponivel: {'sim' if extracao.ocr_disponivel() else 'nao'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Motor da base de conhecimento")
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--arquivo", type=Path, help="processa um arquivo especifico")
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--seco", action="store_true", help="nao escreve nada")
    ap.add_argument("--reprocessar", action="store_true")
    ap.add_argument("--sem-ocr", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--so-indice", action="store_true")
    ap.add_argument("--mover", metavar="PASTA",
                    help="corrige a categoria de um documento ja processado")
    ap.add_argument("--para", metavar="CATEGORIA")
    ap.add_argument("--remover", metavar="PASTA",
                    help="tira o documento da base; original vai para removidos/")
    ap.add_argument("--motivo", default="removido na curadoria")
    ap.add_argument("--revisar", action="store_true",
                    help="recalcula idioma e utilidade sem reabrir PDF")
    args = ap.parse_args()

    raiz = args.raiz
    manifesto_path = raiz / "manifesto.json"
    manifesto = catalogar.carregar_manifesto(manifesto_path)

    if args.status:
        status(raiz, manifesto)
        return 0
    if args.revisar:
        return revisar(raiz, manifesto, seco=args.seco)
    if args.remover:
        return remover(raiz, manifesto, args.remover, args.motivo)
    if args.mover:
        if not args.para:
            print("--mover exige --para <categoria>")
            return 1
        return recategorizar(raiz, manifesto, args.mover, args.para)
    if args.so_indice:
        catalogar.gerar_indice(raiz, manifesto)
        print(f"indice reescrito: {raiz / 'INDEX.md'}")
        return 0

    itens = [args.arquivo] if args.arquivo else fila(raiz / "nao-processado")
    if args.limite:
        itens = itens[: args.limite]
    if not itens:
        print("nada em nao-processado/")
        return 0

    usar_ocr = not args.sem_ocr
    if usar_ocr and not extracao.ocr_disponivel():
        print("aviso: Tesseract nao encontrado - PDF escaneado vai para falhas/")

    print(f"{len(itens)} arquivo(s) na fila\n")
    placar = {}
    for n, caminho in enumerate(itens, 1):
        print(f"[{n}/{len(itens)}] {caminho.name}")
        try:
            r = processar_um(caminho, raiz, manifesto, usar_ocr, args.seco,
                             args.reprocessar)
        except Exception as e:  # nao deixa um PDF ruim derrubar a fila
            print(f"  ERRO: {e.__class__.__name__}: {e}")
            traceback.print_exc(limit=2)
            r = "erro"
            if not args.seco:
                manifesto[sha256(caminho)] = {
                    "arquivo": caminho.name, "titulo": caminho.stem,
                    "status": "falha", "erro": f"{e.__class__.__name__}: {e}",
                    "quando": datetime.now().isoformat(timespec="seconds"),
                }
                mover(caminho, raiz / "falhas")
        placar[r] = placar.get(r, 0) + 1
        if not args.seco:
            catalogar.salvar_manifesto(manifesto_path, manifesto)

    if not args.seco:
        catalogar.gerar_indice(raiz, manifesto)

    print("\nresumo: " + ", ".join(f"{k}={v}" for k, v in sorted(placar.items())))
    if not args.seco:
        print(f"indice: {raiz / 'INDEX.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
