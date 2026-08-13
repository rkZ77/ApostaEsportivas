"""Escudo servido no tamanho que a tela usa (main.py::_reduzir_logo).

MEDIDO com celular emulado contra producao, 2026-08-13:

    102 imagens, 1.1MB baixados
    370KB so' de escudo (18 arquivos, 20.6KB de media)
    LCP 3604ms

A origem manda 150x150 e a tela desenha a 16px (LeagueLogo), 18-24px
(TeamLogo) ou 32px (Fixtures). Em escudos reais: 44.8KB -> 3.1KB.

O que nao pode acontecer, e e' o que estes testes cobrem: escudo sumir da tela
porque a reducao falhou, fundo branco no lugar da transparencia, e servidor que
ja rodava continuar devolvendo a imagem antiga do cache em disco.
"""
import io

import pytest

from PIL import Image

import main


def png(tamanho, cor=(0, 200, 0, 255), modo="RGBA"):
    buf = io.BytesIO()
    Image.new(modo, tamanho, cor).save(buf, "PNG")
    return buf.getvalue()


def ruidoso(tamanho):
    """PNG que nao comprime a toa -- imagem chapada sai pequena demais pra o
    teste de reducao dizer alguma coisa."""
    import random

    random.seed(7)
    im = Image.new("RGBA", tamanho)
    im.putdata([(random.randrange(256), random.randrange(256),
                 random.randrange(256), 255) for _ in range(tamanho[0] * tamanho[1])])
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ── O ganho ───────────────────────────────────────────────────────────────
def test_escudo_grande_e_reduzido():
    bruto = ruidoso((150, 150))
    saida = main._reduzir_logo(bruto)

    assert len(saida) < len(bruto)
    with Image.open(io.BytesIO(saida)) as im:
        assert max(im.size) == main._LOGO_LADO


def test_lado_alvo_cobre_o_maior_uso_da_tela_em_retina():
    """O maior desenho de escudo no site e' 32px (Fixtures). 64 cobre 2x e nada
    mais -- baixar 150px pra desenhar 32 era o problema."""
    assert main._LOGO_LADO == 64


# ── O que nao pode quebrar ────────────────────────────────────────────────
def test_transparencia_e_preservada():
    """Quantize com o metodo padrao (mediancut) perde o alfa e o escudo ganha
    um quadrado branco atras. Por isso FASTOCTREE."""
    bruto = png((150, 150), cor=(0, 200, 0, 0))
    saida = main._reduzir_logo(bruto)

    with Image.open(io.BytesIO(saida)) as im:
        assert im.convert("RGBA").getchannel("A").getextrema()[0] < 255


def test_conteudo_invalido_devolve_o_original():
    """Falha aqui nao pode virar escudo faltando na tela: serve o original,
    pesado porem correto."""
    assert main._reduzir_logo(b"isto nao e um png") == b"isto nao e um png"


def test_imagem_ja_pequena_nao_e_mexida():
    """Reprocessar o que ja cabe seria gastar CPU pra talvez piorar."""
    bruto = png((32, 32))

    assert main._reduzir_logo(bruto) == bruto


def test_nunca_devolve_arquivo_maior_que_o_original():
    """Paletizar pode INCHAR imagem que ja era pequena e otimizada. A regra e'
    servir o menor dos dois, sempre."""
    bruto = png((150, 150))  # chapada: comprime muito bem no original

    assert len(main._reduzir_logo(bruto)) <= len(bruto)


# ── Cache ─────────────────────────────────────────────────────────────────
def test_chave_de_cache_mudou_com_o_formato():
    """O cache em disco de antes guarda a imagem ORIGINAL. Sem trocar a chave,
    servidor que ja rodava continuaria devolvendo os 45KB pra sempre e a
    mudanca so' valeria em maquina nova."""
    assert main._LOGO_CACHE_V, "sem versao no nome do arquivo em cache"
    assert str(main._LOGO_LADO) in main._LOGO_CACHE_V, \
        "a versao do cache tem que acompanhar o lado servido"


def test_nome_do_arquivo_em_cache_carrega_a_versao():
    import inspect

    fonte = inspect.getsource(main._serve_logo)
    assert "_LOGO_CACHE_V" in fonte


def test_cabecalho_de_cache_do_navegador_continua_longo():
    """O ganho de banda depende tanto da reducao quanto de nao rebaixar toda
    visita."""
    cc = main._LOGO_CACHE_HEADERS["Cache-Control"]
    assert "max-age=" in cc and "public" in cc
