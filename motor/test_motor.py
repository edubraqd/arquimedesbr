"""Testes do motor. Rodar: python -m unittest test_motor -v

Cobre o que quebra em silencio: deteccao de idioma, descarte de capitulo de
apoio, escolha do nivel do sumario, limpeza de texto e o fatiamento. Nada aqui
toca disco nem rede.
"""
from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import buscar
import dominio
import catalogar
import consultar
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

    def test_bibliography_e_author_index_saem(self):
        # medido em 16/09: "bibliograf" nao casa "Bibliography" (ph); 4 caps
        # de 18,5k palavras + Author Index de 8k estavam util:sim
        for titulo in ("Bibliography", "Bibliography (parte 1/2)", "Author Index",
                       "Subject Index", "REFERENCES"):
            with self.subTest(titulo=titulo):
                self.assertTrue(qualidade.titulo_e_lixo(titulo))

    def test_prefixo_numerico_nao_esconde_secao_de_apoio(self):
        for titulo in ("5. References", "6. REFERENCES", "12 Bibliography",
                       "### 8. References", "A. Bibliografia"):
            with self.subTest(titulo=titulo):
                self.assertTrue(qualidade.titulo_e_lixo(titulo))

    def test_index_nao_pega_capitulo_sobre_indexacao(self):
        # IIR cap. 4 e 5 ("Index construction", "Index compression") estavam
        # fora da busca por causa do prefixo "index"
        for titulo in ("Index construction", "Index compression", "Indexing",
                       "Indexes and query plans"):
            with self.subTest(titulo=titulo):
                self.assertFalse(qualidade.titulo_e_lixo(titulo))
        for titulo in ("Index", "INDEX", "Index (parte 1/2)", "Índice remissivo",
                       "Index of terms"):
            with self.subTest(titulo=titulo):
                self.assertTrue(qualidade.titulo_e_lixo(titulo))

    def test_add_to_cart_em_capitulo_longo_e_conteudo(self):
        # 11 capitulos reais (AI-Powered Search 1 e 8, Modular Web Design 3-6,
        # 6,3k-10k palavras, ate 20 "add to cart" por ser botao de e-commerce)
        # estavam fora. Pagina de venda e UMA pagina: a unica real tem 659.
        md = " ".join(f"palavra{i % 900}" for i in range(3000)) + " add to cart " * 5
        util, _m = qualidade.avaliar("Chapter 3 Vary", md)
        self.assertTrue(util)


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

    # Em 16/09/2026 um `indexar` morreu com a sessao que o lancou (PID 33812)
    # e deixou a trava; a rodada seguinte recusou por 40 min ate alguem ler o
    # log. A trava guarda o PID: se ele nao existe mais, ela e orfa e sai.
    def test_trava_orfa_de_processo_morto_e_assumida(self):
        (self.raiz / semantico.ARQ_TRAVA).write_text("99999999", encoding="utf-8")
        with mock.patch.object(semantico, "_processo_vivo", return_value=False):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                with semantico.travar(self.raiz):
                    self.assertEqual(
                        (self.raiz / semantico.ARQ_TRAVA).read_text(encoding="utf-8"),
                        str(semantico.os.getpid()))
        self.assertIn("99999999", err.getvalue())
        self.assertFalse((self.raiz / semantico.ARQ_TRAVA).exists())

    def test_trava_de_processo_vivo_continua_recusando(self):
        (self.raiz / semantico.ARQ_TRAVA).write_text("4242", encoding="utf-8")
        with mock.patch.object(semantico, "_processo_vivo", return_value=True):
            with self.assertRaises(semantico.IndiceEmUso):
                with semantico.travar(self.raiz):
                    pass
        self.assertTrue((self.raiz / semantico.ARQ_TRAVA).exists())

    def test_trava_sem_pid_legivel_continua_recusando(self):
        # arquivo vazio ou lixo: nao da para saber de quem e, entao nao mexe
        (self.raiz / semantico.ARQ_TRAVA).write_text("", encoding="utf-8")
        with self.assertRaises(semantico.IndiceEmUso):
            with semantico.travar(self.raiz):
                pass

    def test_processo_vivo_reconhece_o_proprio_e_nega_pid_impossivel(self):
        self.assertTrue(semantico._processo_vivo(semantico.os.getpid()))
        self.assertFalse(semantico._processo_vivo(2**22 + 12345))

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


class TermoCurtoExigeFronteira(unittest.TestCase):
    """Palavra-chave curta nao pode casar dentro de outra palavra.

    Medido em 09/09/2026: "cro" (ux-conversao) acertava 8 vezes na ficha
    tecnica de um guia de professor de ingles e mandava o livro para a
    categoria que a operacao usa em msg1 e landing. Puxando o fio, "rust"
    casa dentro de "trust" -- palavra constante em livro de vendas. Os testes
    de `ownership` e `cargo` logo abaixo tratavam sintomas da mesma causa,
    escolhendo termos mais longos em vez de exigir fronteira.
    """

    def test_termo_curto_nao_casa_dentro_de_palavra(self):
        self.assertEqual(catalogar._ocorrencias("cro", "creditos autorais macro"), 0)
        self.assertEqual(catalogar._ocorrencias("rust", "building trust frustrated"), 0)

    def test_termo_curto_casa_quando_e_a_palavra(self):
        self.assertEqual(catalogar._ocorrencias("rust", "a linguagem rust e boa"), 1)
        self.assertEqual(catalogar._ocorrencias("cro", "otimizacao cro na pagina"), 1)

    def test_frase_continua_casando_como_substring(self):
        # frase de duas palavras ja e especifica: nao precisa de fronteira, e
        # exigir uma quebraria casamento no meio de texto corrido
        self.assertEqual(
            catalogar._ocorrencias("gap selling", "sobre gap selling, o metodo"), 1)

    def test_trust_nao_manda_livro_de_vendas_para_rust(self):
        corpo = "building trust with the customer, trust is earned " * 30
        self.assertNotEqual(
            catalogar.classificar(Path("gap-selling.pdf"), "Gap Selling", corpo),
            "rust")

    def test_livro_de_rust_de_verdade_continua_em_rust(self):
        corpo = ("a linguagem rust usa o borrow checker e cargo build " * 30)
        self.assertEqual(
            catalogar.classificar(Path("rust-book.pdf"), "The Rust Book", corpo),
            "rust")


class ContextoNaPassagem(unittest.TestCase):
    """Prefixo de contexto muda o que a busca COMPARA, nunca o que ENTREGA.

    A passagem tem 60 palavras e perde a identidade do livro. O prefixo
    devolve titulo e capitulo ao vetor usando frontmatter ja calculado. A
    janela entregue continua saindo do arquivo, entao o texto lido pelo
    usuario nao carrega prefixo nenhum.
    """

    CAMPOS = {"titulo": "Gap Selling", "capitulo": "CHAPTER 13",
              "termos": "problem identification, current state"}

    def test_modo_nenhum_nao_toca_na_passagem(self):
        self.assertEqual(semantico.prefixo_de_contexto(self.CAMPOS, "nenhum"), "")
        self.assertEqual(semantico._texto_para_embutir("", "o trecho"), "o trecho")

    def test_modo_titulo_junta_titulo_e_capitulo(self):
        p = semantico.prefixo_de_contexto(self.CAMPOS, "titulo")
        self.assertIn("Gap Selling", p)
        self.assertIn("CHAPTER 13", p)
        self.assertNotIn("current state", p)

    def test_modo_com_termos_inclui_os_termos(self):
        p = semantico.prefixo_de_contexto(self.CAMPOS, "titulo+termos")
        self.assertIn("current state", p)

    def test_prefixo_tem_teto(self):
        gordo = {"titulo": "t" * 500, "capitulo": "c" * 500}
        p = semantico.prefixo_de_contexto(gordo, "titulo")
        self.assertLessEqual(len(p), semantico._LIMITE_PREFIXO)

    def test_campo_faltando_nao_deixa_pontuacao_solta(self):
        p = semantico.prefixo_de_contexto({"titulo": "Gap Selling"}, "titulo")
        self.assertEqual(p, "Gap Selling")

    def test_passagem_entra_inteira_depois_do_prefixo(self):
        junto = semantico._texto_para_embutir("Gap Selling", "o trecho original")
        self.assertTrue(junto.endswith("o trecho original"))


class Realimentacao(unittest.TestCase):
    """Rocchio: a consulta anda na direcao do que serve e foge do que nao serve.

    Constantes de Introduction to Information Retrieval, cap. 9 (p. 214-231),
    que esta na base: alfa 1, beta 0,75, gama 0,15. O livro e explicito sobre
    gama < beta -- realimentacao positiva vale mais que negativa.
    """

    def vetores(self):
        # 0 e a consulta, 1 e "o que serve", 2 e "o que nao serve"
        import numpy as np
        return np.array([[1.0, 0.0, 0.0],
                         [0.0, 1.0, 0.0],
                         [0.0, 0.0, 1.0]], dtype=np.float32)

    def test_sem_julgamento_a_consulta_nao_muda(self):
        import numpy as np
        q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        novo = consultar.rocchio(q, self.vetores(), [], [])
        np.testing.assert_allclose(novo, q, atol=1e-6)

    def test_anda_na_direcao_do_relevante(self):
        import numpy as np
        q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        novo = consultar.rocchio(q, self.vetores(), [1], [])
        self.assertGreater(novo[1], 0.0)

    def test_foge_do_nao_relevante(self):
        import numpy as np
        q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        novo = consultar.rocchio(q, self.vetores(), [], [2])
        self.assertLess(novo[2], 0.0)

    def test_positivo_pesa_mais_que_negativo(self):
        import numpy as np
        q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        novo = consultar.rocchio(q, self.vetores(), [1], [2])
        self.assertGreater(novo[1], abs(novo[2]))

    def test_resultado_sai_normalizado(self):
        import numpy as np
        q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        novo = consultar.rocchio(q, self.vetores(), [1], [2])
        self.assertAlmostEqual(float(np.linalg.norm(novo)), 1.0, places=5)

    def test_constantes_sao_as_do_livro(self):
        self.assertEqual((consultar.ALFA, consultar.BETA, consultar.GAMA),
                         (1.0, 0.75, 0.15))


class PorteiroDoRecorte(unittest.TestCase):
    """Consulta nova sem recorte para, e categoria inexistente para com erro.

    O segundo caso e o que justifica o teste: sem validar, `--categoria vendass`
    monta um filtro vazio, a busca nao encontra nada e o programa imprime uma
    lista vazia com codigo 0 -- falha silenciosa, o pior modo.
    """

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        for cat in ("vendas", "agentes-llm", "inventada-sem-dominio"):
            for doc in ("a", "b"):
                (self.raiz / "markdown" / cat / doc).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.raiz, ignore_errors=True)

    def roda(self, *args):
        """Chama o CLI de verdade, capturando saida e codigo de retorno."""
        saida = io.StringIO()
        argv = ["consultar.py", "--raiz", str(self.raiz), *args]
        with mock.patch.object(sys, "argv", argv),              contextlib.redirect_stdout(saida):
            codigo = consultar.main()
        return codigo, saida.getvalue()

    def test_sem_recorte_recusa_e_lista_categorias(self):
        codigo, saida = self.roda("como responder que esta caro")
        self.assertEqual(codigo, 2)
        self.assertIn("exige recorte", saida)
        self.assertIn("vendas(2)", saida)

    def test_categoria_inexistente_nao_falha_calada(self):
        codigo, saida = self.roda("x", "--categoria", "vendass")
        self.assertEqual(codigo, 2)
        self.assertIn("nao existe na base", saida)

    def test_dominio_inexistente_lista_os_que_existem(self):
        codigo, saida = self.roda("x", "--dominio", "comercialx")
        self.assertEqual(codigo, 2)
        self.assertIn("comercial, pessoal, tecnico", saida)

    def test_sem_recorte_explicito_passa_do_porteiro(self):
        # passa o porteiro e morre depois, no indice que nao existe nesta raiz
        codigo, saida = self.roda("x", "--sem-recorte")
        self.assertEqual(codigo, 1)
        self.assertIn("indice semantico nao existe", saida)

    def test_categorias_lista_por_dominio_e_sai(self):
        codigo, saida = self.roda("--categorias")
        self.assertEqual(codigo, 0)
        self.assertIn("comercial: vendas(2)", saida)
        self.assertIn("tecnico: agentes-llm(2)", saida)

    def test_categoria_sem_dominio_aparece_em_vez_de_sumir(self):
        _codigo, saida = self.roda("--categorias")
        self.assertIn("inventada-sem-dominio(2)", saida)
        self.assertIn("sem dominio", saida)


class SecoNoMoverERemover(unittest.TestCase):
    """`--seco` precisa valer para --mover e --remover.

    Ate 10/09/2026 nao valia: `processar.py --mover X --para Y --seco` movia a
    pasta de verdade (descoberto movendo 11 documentos de categoria -- a previa
    executou), e o `--remover --seco` chamava shutil.rmtree no markdown. Uma
    previa que muta o disco e pior que nao ter previa: quem roda confia nela.
    """

    CATEGORIA = "vendas"
    OUTRA = "marketing"
    PASTA = "livro-qualquer"

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        doc = self.raiz / "markdown" / self.CATEGORIA / self.PASTA
        doc.mkdir(parents=True)
        rotulo = catalogar.ROTULOS[self.CATEGORIA]
        (doc / "01-abertura.md").write_text(
            f'---\ncategoria: "{self.CATEGORIA}"\n'
            f'categoria_rotulo: "{rotulo}"\n---\ncorpo\n',
            encoding="utf-8")
        (self.raiz / "processado" / self.CATEGORIA).mkdir(parents=True)
        (self.raiz / "processado" / self.CATEGORIA / "x.pdf").write_bytes(b"%PDF")
        self.manifesto = {"abc123": {
            "pasta": self.PASTA, "status": "ok", "categoria": self.CATEGORIA,
            "arquivo": "x.pdf", "titulo": "Livro Qualquer", "capitulos": 1,
            "palavras": 10, "paginas": 2, "idioma": "pt",
        }}

    def tearDown(self):
        shutil.rmtree(self.raiz, ignore_errors=True)

    def existe(self, categoria):
        return (self.raiz / "markdown" / categoria / self.PASTA).exists()

    def roda(self, fn, *args, **kw):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = fn(self.raiz, self.manifesto, *args, **kw)
        return codigo, saida.getvalue()

    def test_mover_seco_nao_move(self):
        codigo, saida = self.roda(processar.recategorizar, self.PASTA,
                                  self.OUTRA, seco=True)
        self.assertEqual(codigo, 0)
        self.assertIn("seco", saida)
        self.assertTrue(self.existe(self.CATEGORIA))
        self.assertFalse(self.existe(self.OUTRA))
        self.assertEqual(self.manifesto["abc123"]["categoria"], self.CATEGORIA)

    def test_mover_de_verdade_move_e_troca_o_frontmatter(self):
        codigo, _s = self.roda(processar.recategorizar, self.PASTA, self.OUTRA)
        self.assertEqual(codigo, 0)
        self.assertTrue(self.existe(self.OUTRA))
        self.assertFalse(self.existe(self.CATEGORIA))
        md = (self.raiz / "markdown" / self.OUTRA / self.PASTA /
              "01-abertura.md").read_text(encoding="utf-8")
        self.assertIn(f'categoria: "{self.OUTRA}"', md)
        self.assertIn(catalogar.ROTULOS[self.OUTRA], md)

    def test_categoria_inexistente_para_antes_de_tocar_o_disco(self):
        """Esta guarda ja existia no topo de recategorizar; o teste a fixa."""
        codigo, saida = self.roda(processar.recategorizar, self.PASTA,
                                  "categoria-que-nao-existe")
        self.assertEqual(codigo, 1)
        self.assertIn("categoria invalida", saida)
        # o documento nao pode ter saido do lugar
        self.assertTrue(self.existe(self.CATEGORIA))
        self.assertFalse((self.raiz / "markdown" /
                          "categoria-que-nao-existe").exists())

    def test_remover_seco_nao_apaga_markdown(self):
        codigo, saida = self.roda(processar.remover, self.PASTA, "teste",
                                  seco=True)
        self.assertEqual(codigo, 0)
        self.assertIn("seco", saida)
        self.assertTrue(self.existe(self.CATEGORIA))
        self.assertEqual(self.manifesto["abc123"]["status"], "ok")


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

    def test_indice_com_capitulo_util_nao_nao_reconstroi_a_toa(self):
        """Medido em 16/09: 139 capitulos `util: nao` nunca entram em `docs`,
        entao `_mudou` via 3.207 arquivos contra 3.068 e reconstruia o indice
        de 51 MB (159 s) em TODA consulta."""
        raiz = Path(tempfile.mkdtemp())
        pasta = raiz / "markdown" / "vendas" / "livro"
        pasta.mkdir(parents=True)
        (pasta / "01.md").write_text('---\ntitulo: "L"\n---\npreco objecao valor',
                                    encoding="utf-8")
        (pasta / "02.md").write_text('---\ntitulo: "L"\nutil: "nao"\n---\nsumario',
                                    encoding="utf-8")
        try:
            indice = buscar.carregar_indice(raiz)
            self.assertEqual(len(indice["docs"]), 1)
            self.assertFalse(buscar._mudou(raiz, indice))
        finally:
            shutil.rmtree(raiz, ignore_errors=True)


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


class ConsultaHibrida(unittest.TestCase):
    """consultar.py de 16/09: BM25 por RRF, `--tambem`, dedup por documento,
    `--mais`, categoria esgotada -> dominio, `--abrir` sem indice.

    Base pequena com vetores de 4 dimensoes e o modelo de embedding trocado
    por um dicionario: o que se testa e o ranking, nao o modelo.
    """

    VETORES = {
        "pt": [1.0, 0.0, 0.0, 0.0],
        "rocchio": [0.0, 1.0, 0.0, 0.0],     # faz as vezes do "--tambem" em ingles
    }
    # (categoria, doc, arquivo, capitulo, texto, vetor)
    DOCS = [
        ("vendas", "livro-a", "01-preco.md", "Preco",
         "objecao de preco desconto valor caro", [0.90, 0.10, 0.0, 0.0]),
        ("vendas", "livro-b", "01-abrir.md", "Abrir",
         "abertura da conversa fria com o cliente", [0.95, 0.00, 0.0, 0.0]),
        ("vendas", "livro-b", "02-fechar.md", "Fechar",
         "fechamento da venda e proximo passo", [0.50, 0.00, 0.8, 0.0]),
        ("vendas", "livro-c", "01-rocchio.md", "Rocchio",
         "rocchio relevance feedback query expansion", [0.0, 0.0, 1.0, 0.0]),
        ("python", "livro-d", "01-tipos.md", "Tipos",
         "tipos e anotacoes em python", [0.0, 0.0, 0.0, 1.0]),
        ("rust", "livro-e", "01-borrow.md", "Borrow",
         "borrow checker e ownership", [0.0, 0.0, 0.0, 0.9]),
    ]

    def setUp(self):
        import json

        import numpy as np

        self.raiz = Path(tempfile.mkdtemp())
        passagens, vetores = [], []
        for cat, doc, arq, cap, texto, vet in self.DOCS:
            pasta = self.raiz / "markdown" / cat / doc
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / arq).write_text(
                f'---\ntitulo: "{doc}"\ncapitulo: "{cap}"\ncategoria: "{cat}"\n'
                f'paginas: "1-2"\n---\n{texto}\n', encoding="utf-8")
            passagens.append({"caminho": f"markdown/{cat}/{doc}/{arq}", "ini": 0,
                              "n": len(texto.split()), "titulo": doc,
                              "capitulo": cap, "categoria": cat, "idioma": "pt",
                              "paginas": "1-2"})
            vetores.append(vet)
        np.savez_compressed(self.raiz / semantico.ARQ_VETORES,
                            v=np.array(vetores, dtype=np.float16))
        (self.raiz / semantico.ARQ_META).write_text(
            json.dumps({"passagens": passagens}), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.raiz, ignore_errors=True)

    def roda(self, *args):
        import numpy as np

        def vetor(texto):
            return np.array(self.VETORES[texto], dtype=np.float32)

        saida = io.StringIO()
        argv = ["consultar.py", "--raiz", str(self.raiz), "--sem-rerank", *args]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(consultar, "_vetor_da_consulta", side_effect=vetor), \
                contextlib.redirect_stdout(saida):
            codigo = consultar.main()
        return codigo, saida.getvalue()

    def sessao(self, saida):
        import re
        return re.search(r"sessao (\w+) ·", saida).group(1)

    def docs(self, saida):
        import re
        return re.findall(r"^\d+\. [+-][\d.]+\s+(\S+)", saida, re.M)

    def test_rodada_2_nao_repete_documento_ja_julgado(self):
        # Reproduz o bug de 16/09: o dedup era por passagem. Marcado livro-c
        # como bom, a consulta anda para o eixo dele e o capitulo 2 do livro-b
        # (que tambem aponta para la) vira a melhor passagem do livro-b -- e o
        # livro-b, ja julgado, voltava como se fosse novidade.
        _c, saida = self.roda("pt", "--categoria", "vendas", "--n", "3")
        self.assertEqual(self.docs(saida), ["livro-b", "livro-a", "livro-c"])
        _c, saida2 = self.roda("--sessao", self.sessao(saida),
                               "--sim", "3", "--nao", "1,2")
        self.assertNotIn("livro-b", self.docs(saida2))

    def test_bm25_traz_documento_que_o_vetor_nao_acha(self):
        # "rocchio" so existe no livro-c, cujo vetor e ortogonal a consulta
        _c, saida = self.roda("pt", "--tambem", "rocchio", "--categoria", "vendas",
                              "--n", "2")
        self.assertIn("livro-c", self.docs(saida))

    def test_tambem_move_o_vetor_para_o_meio_dos_dois_idiomas(self):
        import json

        import numpy as np

        _c, saida = self.roda("pt", "--tambem", "rocchio", "--categoria", "vendas")
        s = json.loads((self.raiz / consultar.ARQ_SESSOES).read_text("utf-8"))
        q = np.asarray(s[self.sessao(saida)]["q"])
        np.testing.assert_allclose(q, [0.7071, 0.7071, 0, 0], atol=1e-3)

    def test_mais_lista_outros_capitulos_do_mesmo_documento(self):
        _c, saida = self.roda("pt", "--categoria", "vendas", "--n", "2")
        self.assertEqual(self.docs(saida)[0], "livro-b")
        _c, mais = self.roda("--sessao", self.sessao(saida), "--mais", "1")
        self.assertIn("Fechar", mais)
        self.assertNotIn("livro-a", mais)
        # o capitulo novo ganha numero e pode ser aberto
        _c, aberto = self.roda("--sessao", self.sessao(saida), "--abrir", "3")
        self.assertIn("fechamento da venda", aberto)

    def test_categoria_esgotada_completa_com_o_dominio(self):
        _c, saida = self.roda("pt", "--categoria", "python", "--n", "3")
        self.assertEqual(self.docs(saida), ["livro-d", "livro-e"])
        self.assertIn("categoria python esgotada", saida)
        self.assertIn("dominio tecnico", saida)

    def test_abrir_nao_precisa_do_indice(self):
        _c, saida = self.roda("pt", "--categoria", "vendas")
        (self.raiz / semantico.ARQ_VETORES).unlink()
        (self.raiz / semantico.ARQ_META).unlink()
        codigo, aberto = self.roda("--sessao", self.sessao(saida), "--abrir", "1")
        self.assertEqual(codigo, 0)
        self.assertIn("abertura da conversa fria", aberto)

    def test_sessao_guarda_o_recorte_e_nao_os_indices(self):
        import json

        _c, saida = self.roda("pt", "--categoria", "vendas")
        s = json.loads((self.raiz / consultar.ARQ_SESSOES).read_text("utf-8"))
        s = s[self.sessao(saida)]
        self.assertEqual(s["categoria"], "vendas")
        self.assertNotIn("indices", s)


class ReferenciasDentroDoCapitulo(unittest.TestCase):
    """Bibliografia no fim de capitulo de conteudo vira capitulo proprio, util:nao.

    Medido em 16/09/2026: 289 capitulos `util: sim` carregavam 538k palavras
    de referencias (282k em dados-ml, 100k em agentes-llm). Cada entrada de
    bibliografia e uma passagem que compete no ranking com o texto de verdade.
    """

    def refs(self, n=60):
        return "\n".join(f"Autor{i}, A. and Outro{i}, B. ({1990 + i % 30}). Titulo "
                         f"do artigo {i}. Journal, 12(3), pp. {i}-{i + 9}."
                         for i in range(n))

    def corpo(self, n=400):
        return " ".join(f"conceito{i % 80} explicado{i % 7}" for i in range(n))

    def test_separa_o_bloco_de_referencias(self):
        md = self.corpo() + "\n\n### References\n\n" + self.refs()
        corpo, bloco = fatiar.separar_referencias(md)
        self.assertNotIn("Autor1,", corpo)
        self.assertIn("conceito1 ", corpo)
        self.assertIn("Autor1,", bloco)

    def test_apendice_depois_das_referencias_volta_ao_corpo(self):
        # 148 dos 289 casos medidos tem apendice depois das referencias;
        # a entrada de bibliografia que virou "###" nao conta como titulo
        md = (self.corpo() + "\n\nReferences\n\n" + self.refs()
              + "\n\n### Anthropic. Claude haiku 4.5. https://www.anthropic.com\n"
              + "\n\n### A Dataset Details\n\n"
              + self.corpo(200).replace("conceito", "apendice"))
        corpo, bloco = fatiar.separar_referencias(md)
        self.assertIn("apendice1 ", corpo)
        self.assertNotIn("apendice1 ", bloco)
        self.assertIn("anthropic.com", bloco)

    def test_mencao_curta_nao_corta(self):
        md = self.corpo() + "\n\nReferences\n\n" + self.refs(3)
        self.assertIsNone(fatiar.separar_referencias(md))

    def test_prosa_depois_do_titulo_nao_e_bibliografia(self):
        # "References" como titulo de secao de prosa (sem ano, sem pp.)
        md = self.corpo() + "\n\n## References\n\n" + self.corpo(300)
        self.assertIsNone(fatiar.separar_referencias(md))

    def paginas(self, *textos):
        class Pag:
            def __init__(self, numero, md):
                self.numero, self.md = numero, md
                self.palavras = len(md.split())

        class Doc:
            toc, aberturas = None, None

        d = Doc()
        d.paginas = [Pag(i + 1, t) for i, t in enumerate(textos)]
        return d

    def test_fatiar_da_capitulo_proprio_as_referencias(self):
        doc = self.paginas(self.corpo(600) + "\n\n### References\n\n" + self.refs())
        caps = fatiar.fatiar(doc)
        titulos = [c.titulo for c in caps]
        self.assertIn("References", titulos)
        self.assertNotIn("Autor1,", caps[0].md)
        self.assertTrue(qualidade.titulo_e_lixo(caps[-1].titulo))

    def test_secao_de_apoio_curta_nao_gruda_no_capitulo_anterior(self):
        # "gruda no anterior" (< 400 palavras) era outra porta de entrada da
        # bibliografia no capitulo de conteudo
        doc = self.paginas(self.corpo(600), "### References\n\n" + self.refs(20))
        doc.toc = [[1, "Capitulo 1", 1], [1, "References", 2]]
        caps = fatiar.fatiar(doc)
        self.assertNotIn("Autor1,", caps[0].md)


class ReentradaNoIndice(unittest.TestCase):
    """Capitulo que passa de util:nao para util:sim tem de ser embutido.

    Medido em 16/09: 10 capitulos (70k palavras) reabilitados por `--revisar`
    nunca entraram no indice -- o hash do corpo nao mudou, o metadado mudou,
    e o caminho de "metadado novo" so relia passagens que ja existiam.
    """

    def setUp(self):
        import numpy as np

        self.raiz = Path(tempfile.mkdtemp())
        self.md = self.raiz / "markdown" / "vendas" / "livro" / "01-cap.md"
        self.md.parent.mkdir(parents=True)
        self.escreve("nao")

        class Modelo:
            def embed(self, textos, batch_size=64):
                for _t in textos:
                    yield np.ones(384, dtype=np.float32)

        self.patch = mock.patch.object(semantico, "_modelo", return_value=Modelo())
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.raiz, ignore_errors=True)

    def escreve(self, util):
        corpo = " ".join(f"palavra{i % 50}" for i in range(200))
        self.md.write_text(f'---\ntitulo: "L"\nutil: "{util}"\n---\n{corpo}\n',
                           encoding="utf-8")

    def indexa(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return semantico.indexar(self.raiz)

    def test_nao_para_sim_reentra(self):
        self.assertEqual(len(self.indexa()["passagens"]), 0)
        self.escreve("sim")
        self.assertGreater(len(self.indexa()["passagens"]), 0)

    def test_sim_para_nao_sai(self):
        self.escreve("sim")
        self.assertGreater(len(self.indexa()["passagens"]), 0)
        self.escreve("nao")
        self.assertEqual(len(self.indexa()["passagens"]), 0)


class RevisarSeparaReferencias(unittest.TestCase):
    """`processar.py --revisar` aplica o corte de referencias ao markdown que existe."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        doc = self.raiz / "markdown" / "agentes-llm" / "paper-x"
        doc.mkdir(parents=True)
        refs = "\n".join(f"Autor{i}, A. ({2000 + i % 20}). Titulo {i}. pp. {i}-{i + 3}."
                         for i in range(60))
        corpo = " ".join(f"conceito{i % 80}" for i in range(500))
        (doc / "01-trecho-1.md").write_text(
            '---\ntitulo: "Paper X"\ncategoria: "agentes-llm"\ncapitulo: "Trecho 1"\n'
            'util: "sim"\n---\n# Trecho 1\n\n' + corpo + "\n\nReferences\n\n" + refs + "\n",
            encoding="utf-8")
        self.doc = doc
        self.manifesto = {"abc": {"pasta": "paper-x", "status": "ok",
                                  "categoria": "agentes-llm", "titulo": "Paper X",
                                  "capitulos": 1, "idioma": "en", "tipo": "paper"}}

    def tearDown(self):
        shutil.rmtree(self.raiz, ignore_errors=True)

    def test_revisar_corta_e_marca_util_nao(self):
        with contextlib.redirect_stdout(io.StringIO()):
            processar.revisar(self.raiz, self.manifesto)
        original = (self.doc / "01-trecho-1.md").read_text(encoding="utf-8")
        self.assertNotIn("Autor1,", original)
        novo = self.doc / "01-trecho-1.referencias.md"
        self.assertTrue(novo.exists())
        texto = novo.read_text(encoding="utf-8")
        self.assertIn("Autor1,", texto)
        self.assertIn('util: "nao"', texto)

    def test_revisar_seco_nao_corta(self):
        with contextlib.redirect_stdout(io.StringIO()):
            processar.revisar(self.raiz, self.manifesto, seco=True)
        self.assertIn("Autor1,", (self.doc / "01-trecho-1.md").read_text(encoding="utf-8"))
        self.assertFalse((self.doc / "01-trecho-1.referencias.md").exists())

    def test_segunda_passada_nao_corta_de_novo(self):
        with contextlib.redirect_stdout(io.StringIO()):
            processar.revisar(self.raiz, self.manifesto)
            processar.revisar(self.raiz, self.manifesto)
        self.assertEqual(len(list(self.doc.glob("*.referencias.md"))), 1)


class GuardaIndiceDisco(unittest.TestCase):
    """O indice diz de que disco ele foi feito; a consulta confere antes de usar.

    Em 14/09 um A/B deixou o indice orfao (6.412 passagens apontando para
    arquivo que nao existia) e ninguem viu ate 16/09: 90 capitulos util:sim
    fora da busca por dois dias. `conferir` compara o mtime gravado no indice
    com o do disco -- 0,2 s -- e a consulta avisa em vez de calar.
    """

    def setUp(self):
        import numpy as np

        self.raiz = Path(tempfile.mkdtemp())
        self.pasta = self.raiz / "markdown" / "vendas" / "livro"
        self.pasta.mkdir(parents=True)
        self.md = self.pasta / "01-cap.md"
        self.md.write_text('---\ntitulo: "L"\n---\n' + "palavra " * 100, encoding="utf-8")

        class Modelo:
            def embed(self, textos, batch_size=64):
                for _t in textos:
                    yield np.ones(384, dtype=np.float32)

        self.patch = mock.patch.object(semantico, "_modelo", return_value=Modelo())
        self.patch.start()
        with contextlib.redirect_stdout(io.StringIO()):
            self.meta = semantico.indexar(self.raiz)

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.raiz, ignore_errors=True)

    def test_em_dia_nao_avisa(self):
        self.assertIsNone(semantico.conferir(self.raiz, self.meta))

    def test_arquivo_novo_avisa(self):
        (self.pasta / "02-novo.md").write_text("---\n---\nnovo " * 50, encoding="utf-8")
        aviso = semantico.conferir(self.raiz, self.meta)
        self.assertIn("1 novo", aviso)
        self.assertIn("indexar", aviso)

    def test_arquivo_reescrito_avisa(self):
        import os
        os.utime(self.md, (1e9, 1e9))
        self.assertIn("1 alterado", semantico.conferir(self.raiz, self.meta))

    def test_arquivo_sumido_avisa(self):
        self.md.unlink()
        self.assertIn("1 sumido", semantico.conferir(self.raiz, self.meta))

    def test_indexar_sem_mudanca_ainda_carimba_indice_antigo(self):
        # indice de antes de 16/09 nao tem mtimes: a proxima indexacao, mesmo
        # sem nada para embutir, grava o carimbo em vez de dizer "nada mudou"
        import json
        meta_path = self.raiz / semantico.ARQ_META
        antigo = json.loads(meta_path.read_text(encoding="utf-8"))
        antigo.pop("mtimes")
        meta_path.write_text(json.dumps(antigo), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            semantico.indexar(self.raiz)
        novo = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertIn("mtimes", novo)

    def test_consulta_avisa_na_stderr(self):
        import numpy as np

        (self.pasta / "02-novo.md").write_text("---\n---\nnovo " * 50, encoding="utf-8")
        erro, saida = io.StringIO(), io.StringIO()
        argv = ["consultar.py", "--raiz", str(self.raiz), "--sem-rerank",
                "--sem-recorte", "x"]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(consultar, "_vetor_da_consulta",
                                  return_value=np.ones(384, dtype=np.float32)), \
                contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            consultar.main()
        self.assertIn("indice semantico desatualizado", erro.getvalue())


class ProcessarEncadeiaIndexar(unittest.TestCase):
    """Mexeu no markdown, reindexa. Antes so avisava, e o aviso era ignorado
    (indice orfao por dois dias em 14-16/09)."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        (self.raiz / "markdown").mkdir()
        (self.raiz / "manifesto.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.raiz, ignore_errors=True)

    def roda(self, *args):
        argv = ["processar.py", "--raiz", str(self.raiz), *args]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(processar.semantico, "indexar") as indexar, \
                contextlib.redirect_stdout(io.StringIO()):
            processar.main()
        return indexar

    def test_revisar_reindexa(self):
        self.assertTrue(self.roda("--revisar").called)

    def test_revisar_seco_nao_reindexa(self):
        self.assertFalse(self.roda("--revisar", "--seco").called)

    def test_sem_indexar_desliga(self):
        self.assertFalse(self.roda("--revisar", "--sem-indexar").called)


class ServidorResidente(ConsultaHibrida):
    """`servidor.py` guarda indice e modelos em memoria; `consultar.py` encaminha.

    Medido em 16/09: 8-19 s por rodada, dos quais 0,4 s de trabalho -- o resto
    e carregar json (80 MB), npz (175 MB), modelo (3-9 s) e cross-encoder
    (3 s) a cada chamada. Herda a base pequena de ConsultaHibrida.
    """

    def setUp(self):
        import socket
        import threading

        import servidor

        super().setUp()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.porta = sock.getsockname()[1]
        self.httpd = servidor.montar(self.raiz, self.porta)
        self.fio = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.fio.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def roda(self, *args):
        return super().roda("--porta", str(self.porta), *args)

    # os testes herdados rodam todos de novo, agora pelo servidor

    def test_o_servidor_e_quem_atende(self):
        import servidor

        antes = servidor.ATENDIDAS
        codigo, saida = self.roda("pt", "--categoria", "vendas", "--n", "2")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.docs(saida), ["livro-b", "livro-a"])
        self.assertEqual(servidor.ATENDIDAS, antes + 1)

    def test_local_ignora_o_servidor(self):
        import servidor

        antes = servidor.ATENDIDAS
        _c, saida = self.roda("pt", "--categoria", "vendas", "--n", "2", "--local")
        self.assertEqual(self.docs(saida), ["livro-b", "livro-a"])
        self.assertEqual(servidor.ATENDIDAS, antes)

    def test_indice_novo_no_disco_entra_sem_reiniciar(self):
        import json
        import os

        import numpy as np

        self.roda("pt", "--categoria", "vendas", "--n", "2")
        # troca o indice: so o livro-c, com vetor igual a consulta
        meta = {"passagens": [{"caminho": "markdown/vendas/livro-c/01-rocchio.md",
                               "ini": 0, "n": 5, "titulo": "livro-c",
                               "capitulo": "Rocchio", "categoria": "vendas",
                               "idioma": "pt", "paginas": "1-2"}]}
        (self.raiz / semantico.ARQ_META).write_text(json.dumps(meta), encoding="utf-8")
        np.savez_compressed(self.raiz / semantico.ARQ_VETORES,
                            v=np.array([[1.0, 0, 0, 0]], dtype=np.float16))
        os.utime(self.raiz / semantico.ARQ_META, (2e9, 2e9))
        _c, saida = self.roda("pt", "--categoria", "vendas", "--n", "2")
        self.assertEqual(self.docs(saida), ["livro-c"])

    def test_porta_fechada_cai_para_local(self):
        import servidor

        antes = servidor.ATENDIDAS
        _c, saida = ConsultaHibrida.roda(self, "--porta", "1", "pt",
                                         "--categoria", "vendas", "--n", "2")
        self.assertEqual(self.docs(saida), ["livro-b", "livro-a"])
        self.assertEqual(servidor.ATENDIDAS, antes)


if __name__ == "__main__":
    unittest.main()
