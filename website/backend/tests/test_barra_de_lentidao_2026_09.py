"""A barra do topo também acende quando o dado demora.

Ela cobria os dois casos em que o usuário SABE que pediu algo: trocar de rota e
clicar. Ficava de fora o terceiro, que é o que mais incomoda -- a tela já
montou e um número demora porque a consulta ao banco está lenta. Nada dizia
"ainda estou buscando", e a leitura natural disso é "travou".

O LIMIAR É O QUE IMPEDE A BARRA DE PISCAR SOZINHA. Várias telas fazem polling em
segundo plano (o sino, o "está ao vivo?", o Admin de 3 em 3 segundos). Acender
por requisição deixaria a barra em movimento perpétuo enquanto a pessoa lê a
tela parada, que é o oposto do que ela comunica.
"""
import os
import re


def _front(arquivo: str) -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src")
    with open(os.path.join(base, arquivo), encoding="utf-8") as fh:
        return fh.read()


def test_existe_um_limiar_e_ele_nao_e_curto():
    """Curto demais e o poll de fundo acende a barra sozinho."""
    bus = _front("services/progressBus.ts")
    m = re.search(r"LIMIAR_LENTIDAO_MS = (\d+)", bus)
    assert m, "limiar nao encontrado"
    assert int(m.group(1)) >= 500


def test_acende_uma_vez_por_rajada():
    """Sem zerar o relógio a barra reacenderia a cada tique enquanto a
    requisição não volta."""
    bus = _front("services/progressBus.ts")
    bloco = bus[bus.index("function conferirLentidao"):]
    assert "desdeQuandoOcupado = null" in bloco.split("LIMIAR_LENTIDAO_MS")[1][:200]


def test_o_vigia_para_quando_ninguem_ouve():
    """Timer solto num módulo global roda pra sempre, inclusive em aba de fundo."""
    bus = _front("services/progressBus.ts")
    assert "clearInterval(vigia); vigia = null" in bus


def test_a_barra_reusa_o_mesmo_ciclo():
    """Um comportamento só · duas animações competindo pelo topo da tela seriam
    duas barras."""
    barra = _front("components/TopProgressBar.tsx")
    assert "assinarLentidao(" in barra
    assert "setGatilhoManual(g => g + 1)" in barra


def test_lentidao_nao_reinicia_um_ciclo_em_andamento():
    """A primeira versão remontava o efeito a cada disparo: a barra voltava a 8%
    e recomeçava, e numa tela com várias consultas lentas em sequência ela ia e
    voltava várias vezes · o oposto de "acabou a barra, carregou tudo"."""
    barra = _front("components/TopProgressBar.tsx")
    assert "if (!rodando.current) setGatilhoManual" in barra
    assert "rodando.current = true" in barra
    assert "rodando.current = false" in barra


def test_o_ciclo_so_fecha_com_a_fila_vazia_por_um_tempo():
    """Entre uma resposta e o pedido seguinte existe um respiro de
    milissegundos, e nesse respiro a barra fechava · a requisição seguinte
    abria outra. Exigindo silêncio CONTÍNUO, a cascata fecha uma vez só."""
    import re
    barra = _front("components/TopProgressBar.tsx")
    m = re.search(r"SILENCIO_MS = (\d+)", barra)
    assert m, "constante de silencio nao encontrada"
    assert 200 <= int(m.group(1)) <= 800
    assert "quietoDesde" in barra
