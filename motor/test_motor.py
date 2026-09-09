"""Testes do motor. Rodar: python -m unittest test_motor -v

Cobre o que quebra em silencio: deteccao de idioma, descarte de capitulo de
apoio, escolha do nivel do sumario, limpeza de texto e o fatiamento. Nada aqui
toca disco nem rede.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

import buscar
import dominio
import catalogar
import extrair
import fatiar
import processar
import qualidade
import semantico


class Idioma(unittest.TestCase):
    def test_reconhece_os_quatro_idiomas_da_base(self):
        casos = {
            "pt": "de que nao para uma com os dos das quando entao voce seu sua "
                  "pelo porque tambem ja mais sao estao fazer ser tem isso este",
            "en": "the of and to in that is for with as was are this these from "
                  "have has been will would there their which when what about",
            "es": "de que no para una con los las del eso este muy cuando "
                  "entonces usted nosotros por hasta porque tambien ya mas son",
            "fr": "le la les des une pour avec dans que qui est sont ete plus "
                  "cette ces vous nous leur mais comme sur par tout meme aussi",
        }
        for esperado, texto in casos.items():
            with self.subTest(idioma=esperado):
                self.assertEqual(qualidade.detectar_idioma(texto * 3)[0], esperado)

    def test_texto_curto_nao_arrisca_palpite(self):
        self.assertEqual(qualidade.detectar_idioma("oi")[0], "xx")

    def test_tabela_de_numeros_nao_vira_idioma(self):
        self.assertEqual(qualidade.detectar_idioma("12 34 56 78 " * 60)[0], "xx")


class Utilidade(unittest.TestCase):
    def corpo(self, n=300):
        return " ".join(f"palavra{i % 90}" for i in range(n))

    def test_titulo_de_apoio_sai_da_busca(self):
        for titulo in ("Copyright Page", "Contents", "Index", "Sumario",
                       "About the Author", "Advance Praise for X", "Bibliografia"):
            with self.subTest(titulo=titulo):
                self.assertFalse(qualidade.avaliar(titulo, self.corpo())[0])

    def test_capitulo_normal_fica(self):
        util, motivo = qualidade.avaliar("5. Encapsulation", self.corpo())
        self.assertTrue(util, motivo)
        self.assertEqual(motivo, "")

    def test_pagina_de_venda_sai(self):
        md = self.corpo() + " Available Formats: eBook Testbank Solutions Manual"
        util, motivo = qualidade.avaliar("Trecho 1", md)
        self.assertFalse(util)
        self.assertIn("pagina de venda", motivo)

    def test_indice_remissivo_sai_mesmo_com_titulo_inocente(self):
        # sem pontilhado de proposito: aqui quem tem de disparar e a regra de
        # linha curta terminando em numero, nao a de sumario
        md = "\n".join(f"Assunto numero {i} {i * 3}" for i in range(60))
        util, motivo = qualidade.avaliar("Capitulo 9", md)
        self.assertFalse(util)
        self.assertIn("indice remissivo", motivo)

    def test_sumario_com_pontilhado_sai(self):
        md = " ".join(f"Titulo do capitulo {i} . . . . . . . {i * 7}" for i in range(30))
        util, motivo = qualidade.avaliar("Trecho 1", md)
        self.assertFalse(util)
        self.assertIn("pontilhado", motivo)

    def test_ownership_nao_manda_livro_de_gamification_para_rust(self):
        from pathlib import Path as P

        corpo = "core drive ownership and possession " * 40 + "gamification design"
        self.assertNotEqual(
            catalogar.classificar(P("actionable-gamification.pdf"), "Actionable Gamification", corpo),
            "rust",
        )

    def test_tabela_de_numeros_sai(self):
        # capitulo 4 do Power Meter e so tabela de conversao de potencia
        md = " ".join(f"{i / 7:.2f}" for i in range(400))
        util, motivo = qualidade.avaliar("Trecho 4", md)
        self.assertFalse(util)
        self.assertIn("tabela de numeros", motivo)

    def test_texto_com_alguns_numeros_fica(self):
        md = ("o modelo previu 42 unidades em 2024 contra 38 no ano anterior "
              "porque a demanda cresceu de forma consistente ") * 12
        self.assertTrue(qualidade.avaliar("3. Previsao", md)[0])

    def test_cargo_em_portugues_nao_manda_livro_para_rust(self):
        from pathlib import Path as P

        corpo = ("o cargo de gerente exige carga de trabalho e cargo publico " * 30)
        self.assertNotEqual(
            catalogar.classificar(P("apaixone-se-pelo-problema.pdf"),
                                  "Apaixone-se pelo problema", corpo),
            "rust",
        )

    def test_capitulo_curto_sai(self):
        self.assertFalse(qualidade.avaliar("1. Intro", "so vinte palavras " * 5)[0])


class PontilhadoDeSumario(unittest.TestCase):
    """Contar pontilhado nao basta; o que separa e quanto do texto ele ocupa.

    Em 09/09/2026 a regra por contagem (>= 12 runs) tirou da busca 23 dos 34
    capitulos de Security Analysis: o OCR das tabelas financeiras produz
    pontilhado no meio de prosa legitima. Medido nos 27 capitulos afetados,
    sumario de verdade fica entre 15,8% e 48,7% do texto em pontos; capitulo
    de conteudo com tabela nao passa de 5,5%.
    """

    def test_sumario_de_verdade_sai_da_busca(self):
        # titulo neutro de proposito: quem tem de disparar e a regra de
        # pontilhado, nao a de titulo de apoio
        linha = "Capitulo sobre alguma coisa . . . . . . . . . . . . . . 54\n"
        util, motivo = qualidade.avaliar("Trecho 1", linha * 40)
        self.assertFalse(util)
        self.assertIn("pontilhado", motivo)

    def prosa(self, linhas=80, por_linha=15):
        """Texto variado e em varias linhas.

        Repetir a mesma frase cai na regra de vocabulario degenerado, e um
        paragrafo unico faz as linhas de tabela virarem maioria e disparar a
        regra de indice remissivo -- nenhuma das duas e a que se testa aqui.
        """
        return "\n".join(
            " ".join(f"conceito{(i * por_linha + j) % 400} analise{j % 97}"
                     for j in range(por_linha))
            for i in range(linhas))

    def test_prosa_com_tabela_financeira_continua_na_busca(self):
        # o caso Security Analysis: pontilhado existe, mas afogado em prosa
        tabela = "Net earnings . . . . . 1,240\n" * 20
        util, motivo = qualidade.avaliar("Depreciation", self.prosa() + tabela)
        self.assertTrue(util, motivo)

    def test_poucos_pontilhados_nunca_descartam(self):
        util, motivo = qualidade.avaliar(
            "Capitulo", self.prosa() + "referencia . . . . 4\n" * 5)
        self.assertTrue(util, motivo)


class Epub(unittest.TestCase):
    """EPUB e zip de XHTML: entra com stdlib, sem dependencia nova.

    Uma Pagina por documento do spine (e nao um bloco unico como o .docx),
    porque o spine ja e a ordem de leitura -- assim o fatiamento cai em
    fronteira de capitulo e a citacao aponta para um lugar real.
    """

    CONTAINER = (
        '<?xml version="1.0"?>'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/livro.opf"'
        ' media-type="application/oebps-package+xml"/></rootfiles></container>'
    )

    def opf(self, titulo="Livro de Teste", itens=("c1", "c2")):
        manifesto = "".join(
            f'<item id="{i}" href="{i}.xhtml" media-type="application/xhtml+xml"/>'
            for i in itens)
        spine = "".join(f'<itemref idref="{i}"/>' for i in itens)
        return (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:title>{titulo}</dc:title><dc:creator>Alguem</dc:creator>'
            '</metadata>'
            f'<manifest>{manifesto}</manifest><spine>{spine}</spine></package>'
        )

    def xhtml(self, h, corpo):
        return (f'<html><head><title>x</title><style>p{{color:red}}</style></head>'
                f'<body><h1>{h}</h1><p>{corpo}</p></body></html>')

    def montar(self, titulo="Livro de Teste", capitulos=None):
        capitulos = capitulos or {
            "c1": ("Primeiro capitulo", "Texto do primeiro capitulo aqui."),
            "c2": ("Segundo capitulo", "Texto do segundo capitulo aqui."),
        }
        destino = Path(self.tmp) / "livro.epub"
        with zipfile.ZipFile(destino, "w") as z:
            z.writestr("mimetype", "application/epub+zip")
            z.writestr("META-INF/container.xml", self.CONTAINER)
            z.writestr("OEBPS/livro.opf", self.opf(titulo, tuple(capitulos)))
            for nome, (h, corpo) in capitulos.items():
                z.writestr(f"OEBPS/{nome}.xhtml", self.xhtml(h, corpo))
        return destino

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_uma_pagina_por_documento_do_spine(self):
        doc = extrair.extrair_epub(self.montar())
        self.assertEqual(len(doc.paginas), 2)
        self.assertEqual(doc.extrator, "epub")
        self.assertEqual(doc.autor, "Alguem")

    def test_titulo_h1_vira_cabecalho_markdown(self):
        doc = extrair.extrair_epub(self.montar())
        self.assertIn("## Primeiro capitulo", doc.paginas[0].md)

    def test_css_e_script_nao_entram_no_texto(self):
        doc = extrair.extrair_epub(self.montar())
        self.assertNotIn("color:red", doc.paginas[0].md)

    def test_respeita_a_ordem_do_spine(self):
        doc = extrair.extrair_epub(self.montar())
        self.assertIn("primeiro", doc.paginas[0].md.lower())
        self.assertIn("segundo", doc.paginas[1].md.lower())

    def test_extensao_reconhecida_pelo_despachante(self):
        self.assertIn(".epub", extrair.EXTENSOES)
        doc = extrair.extrair(self.montar())
        self.assertEqual(doc.extrator, "epub")

    def test_epub_sem_texto_falha_em_vez_de_entrar_vazio(self):
        vazio = {"c1": ("", "")}
        with self.assertRaises(ValueError):
            extrair.extrair_epub(self.montar(capitulos=vazio))


class TituloDeEpubReempacotado(unittest.TestCase):
    """Quem reempacota epub costuma por o nome do arquivo como titulo."""

    def test_tira_extensao_escapes_e_site(self):
        bruto = r"The Challenger Sale: Taking Control   \( PDFDrive.com \).epub"
        self.assertEqual(extrair._limpar_titulo_epub(bruto),
                         "The Challenger Sale: Taking Control")

    def test_titulo_limpo_fica_intacto(self):
        for bom in ("Gap Selling", "SPIN Selling: 2nd Edition"):
            with self.subTest(titulo=bom):
                self.assertEqual(extrair._limpar_titulo_epub(bom), bom)

    def test_parenteses_que_nao_sao_site_ficam(self):
        bruto = "Fluent Python (2nd Edition)"
        self.assertEqual(extrair._limpar_titulo_epub(bruto), bruto)


class TravaEEscritaDoIndice(unittest.TestCase):
    """Duas rodadas juntas corromperam um indice de 151 MB em 09/09/2026.

    A segunda leu o .npz no meio da escrita da primeira: BadZipFile e 40 min
    de CPU para refazer. A trava impede a corrida; a escrita atomica impede
    que uma rodada morta no meio deixe arquivo pela metade.
    """

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.raiz, ignore_errors=True)

    def test_segunda_indexacao_simultanea_e_recusada(self):
        with semantico.travar(self.raiz):
            with self.assertRaises(semantico.IndiceEmUso):
                with semantico.travar(self.raiz):
                    pass

    def test_trava_sai_do_disco_no_fim(self):
        with semantico.travar(self.raiz):
            self.assertTrue((self.raiz / semantico.ARQ_TRAVA).exists())
        self.assertFalse((self.raiz / semantico.ARQ_TRAVA).exists())

    def test_trava_sai_do_disco_mesmo_com_erro(self):
        with self.assertRaises(ZeroDivisionError):
            with semantico.travar(self.raiz):
                1 / 0
        self.assertFalse((self.raiz / semantico.ARQ_TRAVA).exists())

    def test_escrita_atomica_preserva_a_extensao(self):
        # np.savez_compressed acrescenta ".npz" sozinho: se o temporario for
        # "x.npz.parcial", o que ele escreve e "x.npz.parcial.npz" e o
        # os.replace troca um arquivo que nunca existiu
        vistos = []
        destino = self.raiz / ".indice-semantico.npz"
        semantico.escrever_atomico(
            destino, lambda p: (vistos.append(p.suffix), p.write_bytes(b"ok")))
        self.assertEqual(vistos[0], ".npz")
        self.assertEqual(destino.read_bytes(), b"ok")

    def test_falha_no_meio_nao_deixa_destino_corrompido(self):
        destino = self.raiz / ".indice-semantico.npz"
        destino.write_bytes(b"indice bom de antes")

        def explode(p):
            p.write_bytes(b"metade")
            raise OSError("disco cheio")

        with self.assertRaises(OSError):
            semantico.escrever_atomico(destino, explode)
        self.assertEqual(destino.read_bytes(), b"indice bom de antes")
        self.assertEqual(list(self.raiz.glob("*.parcial*")), [])


class CapituloIlegivel(unittest.TestCase):
    """Um capitulo que o disco recusa nao pode custar a varredura inteira.

    Caso real de 09/09/2026: o antivirus poe em quarentena o capitulo 16 do
    Gray Hat Hacking porque o TEXTO do livro casa com Exploit:Win32/Pdfjsc.Q.
    O arquivo continua no disco, com tamanho, e toda leitura devolve OSError 22
    -- o que derrubou `semantico.py indexar` no meio da base.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        buscar._ilegiveis_avisados.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_capitulo_normal_e_lido(self):
        f = self.tmp / "01-cap.md"
        f.write_text("conteudo", encoding="utf-8")
        self.assertEqual(buscar.ler_capitulo(f), "conteudo")

    def test_oserror_vira_none_em_vez_de_explodir(self):
        class Recusa:
            def read_text(self, **kwargs):
                raise OSError(22, "Invalid argument")

            def __str__(self):
                return "quarentenado.md"

        self.assertIsNone(buscar.ler_capitulo(Recusa()))

    def test_avisa_uma_vez_so_por_arquivo(self):
        class Recusa:
            def read_text(self, **kwargs):
                raise OSError(22, "Invalid argument")

            def __str__(self):
                return "mesmo.md"

        buscar.ler_capitulo(Recusa())
        buscar.ler_capitulo(Recusa())
        self.assertEqual(len(buscar._ilegiveis_avisados), 1)

    def test_texto_malformado_continua_passando(self):
        # errors="replace" ja cobria isto; a mudanca nao pode ter quebrado
        f = self.tmp / "02-cap.md"
        f.write_bytes(b"valido \xff\xfe invalido")
        self.assertIn("valido", buscar.ler_capitulo(f))


class TipoDeDocumento(unittest.TestCase):
    def test_tese_precisa_de_duas_marcas(self):
        uma = "o orientador: sugeriu ler o livro sobre vendas"
        self.assertEqual(qualidade.detectar_tipo("Vendas", uma), "livro")
        duas = ("UNIVERSIDADE FEDERAL do Rio de Janeiro, Projeto de Graduacao "
                "apresentado ao curso, Orientador: prof. dr.")
        self.assertEqual(qualidade.detectar_tipo("Hidrodinamica", duas), "tese")

    def test_reconhece_manual_e_apostila(self):
        self.assertEqual(
            qualidade.detectar_tipo("Inner Rep", "Manual de Produto rev5"), "manual")
        self.assertEqual(
            qualidade.detectar_tipo("PNL", "Apostila do curso de formacao"), "apostila")

    def test_livro_comum_continua_livro(self):
        corpo = "how to sell more by asking questions so the buyer sees the problem"
        self.assertEqual(qualidade.detectar_tipo("SPIN Selling", corpo), "livro")


class CanarioDeExtracao(unittest.TestCase):
    """A falha que motivou o canario nao dava erro: so um documento vazio."""

    def test_nao_opina_sobre_arquivo_que_nao_e_pdf(self):
        razao, aviso = processar.conferir_extracao(Path("livro.txt"), 10_000)
        self.assertEqual((razao, aviso), (0.0, ""))

    def test_avisa_quando_perde_texto(self):
        # 22% e o caso real do Zero to Production antes da correcao
        razao, aviso = processar._julgar_extracao(31_092, 141_113)
        self.assertLess(razao, 0.8)
        self.assertIn("possivel perda", aviso)

    def test_calado_quando_a_extracao_esta_sadia(self):
        razao, aviso = processar._julgar_extracao(20_247, 21_192)
        self.assertGreater(razao, 0.9)
        self.assertEqual(aviso, "")

    def test_escaneado_nao_dispara_alarme_falso(self):
        # PDF imagem tem cru ~0 e o OCR e que produz o texto
        self.assertEqual(processar._julgar_extracao(60_000, 120), (0.0, ""))


class DpiSeguroNoOcr(unittest.TestCase):
    """Pagina gigante nao pode estourar o limite de pixels do PIL.

    Security Analysis (735 pag.) tem pagina que a 300 dpi renderiza 1,8 bilhao
    de pixels; o PIL barra como decompression bomb e, na versao antiga, o erro
    subia ate derrubar a fila inteira de 21 arquivos no sexto.
    """

    class _Rect:
        def __init__(self, w, h):
            self.width, self.height = w, h

    class _Pagina:
        def __init__(self, w, h):
            self.rect = DpiSeguroNoOcr._Rect(w, h)

    def _pixels(self, page, dpi):
        return (page.rect.width * dpi / 72.0) * (page.rect.height * dpi / 72.0)

    def test_pagina_normal_mantem_o_dpi(self):
        # A4 a 300 dpi da ~8,7 MPix: bem abaixo do teto, nao mexe
        pagina = self._Pagina(595, 842)
        self.assertEqual(extrair._dpi_seguro(pagina, 300), 300)

    def test_pagina_gigante_baixa_o_dpi(self):
        # o caso real: pagina enorme que a 300 dpi passa de 1,7 GPix
        pagina = self._Pagina(8000, 11000)
        dpi = extrair._dpi_seguro(pagina, 300)
        self.assertLess(dpi, 300)
        self.assertLessEqual(self._pixels(pagina, dpi), extrair.MAX_PIXELS_OCR)

    def test_pagina_absurda_ainda_respeita_o_teto(self):
        # nao existe piso de dpi: o teto de pixels vence sempre, porque
        # reconhecer mal e melhor que perder a pagina e a fila atras dela
        pagina = self._Pagina(200000, 200000)
        dpi = extrair._dpi_seguro(pagina, 300)
        self.assertGreaterEqual(dpi, 1)
        self.assertLessEqual(self._pixels(pagina, dpi), extrair.MAX_PIXELS_OCR)

    def test_pagina_sem_retangulo_nao_quebra(self):
        class Vazia:
            rect = None
        self.assertEqual(extrair._dpi_seguro(Vazia(), 300), 300)


class Limpeza(unittest.TestCase):
    def test_junta_palavra_quebrada_por_hifen(self):
        self.assertEqual(extrair._normalizar("compre-\nendeu"), "compreendeu")

    def test_troca_ligadura(self):
        self.assertEqual(extrair._normalizar("eﬁciente"), "eficiente")

    def test_assinatura_ignora_numero_de_pagina(self):
        self.assertEqual(
            extrair._assinatura("Capitulo 3 | 41"),
            extrair._assinatura("Capitulo 3 | 42"),
        )

    def test_borda_repetida_so_conta_com_paginas_suficientes(self):
        pagina = [{"texto": "RODAPE DO LIVRO", "linhas": 1, "tam": 9.0, "negrito": 0.0}]
        self.assertEqual(extrair._bordas_repetidas([pagina] * 3), set())
        self.assertIn(
            extrair._assinatura("RODAPE DO LIVRO"),
            extrair._bordas_repetidas([pagina] * 10),
        )


class Fatiamento(unittest.TestCase):
    def test_prefere_nivel_com_tamanho_de_capitulo(self):
        # nivel 1 = 3 "partes" de 233 paginas; nivel 2 = 28 capitulos de 25
        toc = [[1, f"Parte {i}", 1 + i * 233] for i in range(3)]
        toc += [[2, f"Cap {i}", 1 + i * 25] for i in range(28)]
        self.assertEqual(fatiar._nivel_util(toc, 700), 2)

    def test_titulos_na_mesma_pagina_viram_um_corte(self):
        toc = [[1, "A", 10], [1, "B", 10], [1, "C", 40], [1, "D", 80]]
        cortes = fatiar._cortes_do_toc(toc, 120)
        self.assertEqual([c[0] for c in cortes], [10, 40, 80])
        self.assertIn("B", cortes[0][1])

    def test_corte_por_tamanho_respeita_paragrafo(self):
        paragrafos = ["\n\n".join(["palavra " * 100] * 5)]
        partes = fatiar._dividir_por_tamanho(paragrafos[0], 200)
        self.assertGreater(len(partes), 1)
        self.assertTrue(all(p.strip() for p in partes))

    def bloco(self, texto, tam, linhas=1):
        return {"texto": texto, "linhas": linhas, "tam": tam, "negrito": 0.0}

    def paginas_com_titulo(self, n_paginas, passo, tam_titulo=18.0):
        """Livro sintetico: titulo grande a cada `passo` paginas, corpo em 10pt."""
        paginas = []
        for i in range(n_paginas):
            blocos = []
            if i % passo == 0:
                blocos.append(self.bloco(f"Capitulo {i // passo}", tam_titulo))
            blocos.append(self.bloco("corpo " * 60, 10.0, linhas=8))
            paginas.append(blocos)
        return paginas

    def test_detecta_capitulo_pelo_tamanho_da_fonte(self):
        paginas = self.paginas_com_titulo(120, 20)
        achados = extrair.aberturas_de_capitulo(paginas, 10.0)
        self.assertEqual(sorted(achados), list(range(0, 120, 20)))

    def test_recusa_deteccao_que_so_cobre_o_fim_do_livro(self):
        # o caso do Refactoring UI: fonte grande so aparece na segunda metade
        paginas = [[self.bloco("corpo " * 60, 10.0, linhas=8)] for _ in range(250)]
        for i in (158, 171, 200, 249):
            paginas[i].insert(0, self.bloco(f"Secao {i}", 18.0))
        self.assertEqual(extrair.aberturas_de_capitulo(paginas, 10.0), {})

    def test_recusa_quando_um_bloco_engole_o_livro(self):
        paginas = [[self.bloco("corpo " * 60, 10.0, linhas=8)] for _ in range(200)]
        for i in (2, 6, 10, 14):        # quatro cortes no comeco, nada depois
            paginas[i].insert(0, self.bloco(f"Parte {i}", 18.0))
        self.assertEqual(extrair.aberturas_de_capitulo(paginas, 10.0), {})

    def test_titulo_detectado_perde_o_numero_de_pagina(self):
        self.assertEqual(extrair._limpar_titulo("44\nCapitulo dos"), "Capitulo dos")

    def test_slug_tira_acento_e_pontuacao(self):
        self.assertEqual(fatiar.slug("Precificação: o Guia!"), "precificacao-o-guia")


class SpansDeEspaco(unittest.TestCase):
    """PDF de LaTeX carrega o espaco num span proprio (fonte Type1).

    Descartar esse span colava o texto inteiro e a base gravava 18% do
    documento sem erro nenhum na tela — medido no arXiv 2608.23953.
    """

    @staticmethod
    def _pagina(spans):
        return {"blocks": [{"type": 0, "lines": [
            {"spans": [{"text": t, "size": 10.0, "flags": 0} for t in spans]}]}]}

    class _Falsa:
        def __init__(self, dados): self._dados = dados
        def get_text(self, _modo): return self._dados

    def test_span_de_espaco_vira_espaco(self):
        pagina = self._Falsa(self._pagina(["Figure", " ", "1:", " ", "The", " ", "three"]))
        blocos = extrair._blocos_da_pagina(pagina)
        self.assertEqual(blocos[0]["texto"], "Figure 1: The three")

    def test_nao_inventa_espaco_dentro_de_palavra(self):
        # troca de fonte no meio da palavra nao pode virar "ex emplo"
        pagina = self._Falsa(self._pagina(["ex", "emplo"]))
        blocos = extrair._blocos_da_pagina(pagina)
        self.assertEqual(blocos[0]["texto"], "exemplo")

    def test_espaco_nao_duplica(self):
        pagina = self._Falsa(self._pagina(["a", " ", " ", "b"]))
        blocos = extrair._blocos_da_pagina(pagina)
        self.assertEqual(blocos[0]["texto"], "a b")


class Catalogo(unittest.TestCase):
    def test_nome_do_arquivo_pesa_mais_que_o_corpo(self):
        from pathlib import Path

        categoria = catalogar.classificar(
            Path("spin-selling-espanol.pdf"), "SPIN Selling", "texto qualquer"
        )
        self.assertEqual(categoria, "vendas")

    def test_sem_sinal_cai_em_geral(self):
        from pathlib import Path

        self.assertEqual(
            catalogar.classificar(Path("xyz.pdf"), "Xyz", "lorem ipsum dolor"),
            "geral",
        )

    def test_numero_formatado_nao_estraga_rotulo(self):
        self.assertEqual(catalogar._num(2889432), "2.889.432")

    def test_titulo_limpa_id_do_scribd_e_sufixo_de_pirataria(self):
        from pathlib import Path

        class Doc:
            titulo = ""

        t = catalogar.titulo_de(Path("123456789-Fluent-Python-True-PDF.pdf"), Doc())
        self.assertEqual(t, "Fluent Python")


class Busca(unittest.TestCase):
    def test_tokenizar_tira_acento_e_palavra_de_parada(self):
        self.assertEqual(buscar.tokenizar("A precificação do serviço"),
                         ["precificacao", "servico"])

    def test_bm25_prefere_documento_com_mais_termos_da_consulta(self):
        indice = {
            "total": 2,
            "media": 10,
            "df": {"preco": 2, "objecao": 1},
            "docs": [
                {"caminho": "a", "categoria": "x", "n": 10,
                 "tf": {"preco": 3, "objecao": 2}},
                {"caminho": "b", "categoria": "x", "n": 10, "tf": {"preco": 9}},
            ],
        }
        ordem = [d["caminho"] for _p, _n, d in buscar.bm25(indice, "preco objecao")]
        self.assertEqual(ordem[0], "a")

    def test_documento_gigante_nao_ganha_so_por_casar_todo_termo(self):
        # a Encyclopedia of Big Data (478 mil palavras) vencia qualquer consulta
        # porque a ordenacao olhava numero de termos distintos antes do score
        indice = {
            "total": 2, "media": 500, "df": {"preco": 2, "objecao": 2},
            "docs": [
                {"caminho": "gigante", "categoria": "x", "n": 5000,
                 "tf": {"preco": 2, "objecao": 2}},
                {"caminho": "focado", "categoria": "x", "n": 300,
                 "tf": {"preco": 25, "objecao": 18}},
            ],
        }
        ordem = [d["caminho"] for _p, _n, d in buscar.bm25(indice, "preco objecao")]
        self.assertEqual(ordem[0], "focado")

    def test_fusao_bilingue_premia_primeiro_lugar_e_nao_presenca_dupla(self):
        indice = {
            "total": 3, "media": 100, "df": {"preco": 2, "price": 2},
            "docs": [
                # 1o lugar em portugues, invisivel em ingles
                {"caminho": "pt", "categoria": "x", "n": 100, "tf": {"preco": 40}},
                # medianos nas duas: nao podem passar na frente
                {"caminho": "meio1", "categoria": "x", "n": 100,
                 "tf": {"preco": 1, "price": 1}},
                {"caminho": "meio2", "categoria": "x", "n": 100,
                 "tf": {"preco": 1, "price": 1}},
            ],
        }
        ordem = [d["caminho"] for _p, d in buscar.fundir(indice, ["preco", "price"])]
        self.assertEqual(ordem[0], "pt")

    def test_frontmatter_le_campos(self):
        campos = buscar._frontmatter('---\ntitulo: "X"\nutil: "nao"\n---\ncorpo')
        self.assertEqual(campos["titulo"], "X")
        self.assertEqual(campos["util"], "nao")


class Passagens(unittest.TestCase):
    def test_janela_desliza_com_sobreposicao(self):
        corpo = " ".join(str(i) for i in range(500))
        ps = semantico._passagens(corpo)
        self.assertEqual(ps[0][0], 0)
        self.assertEqual(ps[1][0], semantico.AVANCO)
        self.assertLess(ps[1][0], semantico.PASSAGEM_PALAVRAS)  # ha sobreposicao

    def test_texto_curto_vira_uma_passagem(self):
        self.assertEqual(len(semantico._passagens("uma frase curta qualquer")), 1)

    def test_corpo_descarta_frontmatter(self):
        self.assertEqual(
            semantico._corpo('---\na: "1"\n---\ntexto real').strip(), "texto real"
        )


class Dominio(unittest.TestCase):
    """O filtro de dominio erra em silencio: ou some com documento, ou nao filtra."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        (self.raiz / "markdown" / "vendas").mkdir(parents=True)
        (self.raiz / "markdown" / "python").mkdir(parents=True)
        (self.raiz / "markdown" / "geral").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.raiz, ignore_errors=True)

    def test_sem_dominio_nao_restringe(self):
        self.assertIsNone(dominio.categorias(self.raiz, None))

    def test_comercial_pega_vendas_e_nao_python(self):
        cats = dominio.categorias(self.raiz, "comercial")
        self.assertIn("vendas", cats)
        self.assertNotIn("python", cats)

    def test_tecnico_pega_python_e_nao_vendas(self):
        cats = dominio.categorias(self.raiz, "tecnico")
        self.assertIn("python", cats)
        self.assertNotIn("vendas", cats)

    def test_categoria_sem_dominio_entra_em_todos(self):
        """Documento novo nunca pode sumir calado por falta de classificacao."""
        for nome in ("comercial", "tecnico", "pessoal"):
            self.assertIn("geral", dominio.categorias(self.raiz, nome))

    def test_validar_acusa_categoria_nao_mapeada(self):
        self.assertEqual(dominio.validar(self.raiz, {"vendas", "geral"}), ["geral"])

    def test_dominio_inexistente_para_o_programa(self):
        with self.assertRaises(SystemExit):
            dominio.categorias(self.raiz, "nao-existe")

    def test_json_sobrescreve_o_mapa_embutido(self):
        (self.raiz / "dominio.json").write_text(
            '{"comercial": ["python"]}', encoding="utf-8"
        )
        self.assertIn("python", dominio.categorias(self.raiz, "comercial"))

    def test_categoria_tirada_de_todos_os_dominios_volta_como_nao_mapeada(self):
        """Armadilha do dominio.json, fixada aqui porque surpreende.

        Tirar `vendas` do unico dominio que a continha nao a exclui da busca: ela
        vira categoria sem dominio, e a regra de nao sumir com documento a
        devolve para todos. Para separar de verdade, mova a categoria para outro
        dominio em vez de apenas apagar da lista.
        """
        (self.raiz / "dominio.json").write_text(
            '{"comercial": ["python"]}', encoding="utf-8"
        )
        self.assertIn("vendas", dominio.categorias(self.raiz, "comercial"))
        (self.raiz / "dominio.json").write_text(
            '{"comercial": ["python"], "pessoal": ["vendas"]}', encoding="utf-8"
        )
        self.assertNotIn("vendas", dominio.categorias(self.raiz, "comercial"))

    def test_cada_categoria_cai_em_no_maximo_um_dominio(self):
        vistas = []
        for cats in dominio.DOMINIOS.values():
            vistas.extend(cats)
        self.assertEqual(len(vistas), len(set(vistas)))


class IndiceSemantico(unittest.TestCase):
    """Metadado que muda sem o corpo mudar tem de chegar na busca."""


    def test_assinatura_muda_com_titulo(self):
        a = semantico._assinatura_meta({"titulo": "Antigo", "capitulo": "1"})
        b = semantico._assinatura_meta({"titulo": "Novo", "capitulo": "1"})
        self.assertNotEqual(a, b)

    def test_assinatura_muda_com_util(self):
        a = semantico._assinatura_meta({"titulo": "X", "util": "sim"})
        b = semantico._assinatura_meta({"titulo": "X", "util": "nao"})
        self.assertNotEqual(a, b)

    def test_assinatura_ignora_campo_que_a_busca_nao_usa(self):
        a = semantico._assinatura_meta({"titulo": "X", "autor": "Fulano"})
        b = semantico._assinatura_meta({"titulo": "X", "autor": "Sicrano"})
        self.assertEqual(a, b)

    def test_meta_da_passagem_cai_no_caminho_quando_falta_campo(self):
        caminho = Path("markdown/vendas/livro-x/03-cap.md")
        meta = semantico._meta_da_passagem({}, caminho)
        self.assertEqual(meta["titulo"], "livro-x")
        self.assertEqual(meta["categoria"], "vendas")
        self.assertEqual(meta["idioma"], "xx")


if __name__ == "__main__":
    unittest.main()
