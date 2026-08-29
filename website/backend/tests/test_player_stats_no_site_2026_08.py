"""Player Stats aparece no site inteiro, e nao so' na tabela (2026-08-27).

O motor Player Stats escreve em `picks_player_stats` desde 27/08, e o backend
ja' o servia em `/suggestions/today`, na analise, no placar publico e no
resumo. O FRONTEND nunca leu a chave, e tres pontos do backend tambem ficaram
para tras -- todos do mesmo tipo, e todos com precedente escrito no proprio
codigo:

  · `banca.STAKE_LIMITS`     tipo fora do mapa devolve "Tipo invalido" e o
                             botao Apostar quebra DEPOIS de o usuario
                             confirmar. Ja aconteceu com faltas/goleiros;
  · `banca._TABELAS_MERCADO` tipo esquecido nao da erro: o pick some do
                             somatorio e a banca fica errada em silencio;
  · leaderboard de public.py aposta que conta na banca do usuario e some do
                             ranking, porque o CASE devolve NULL e o
                             FILTER (WHERE result IS NOT NULL) descarta.

Este arquivo trava os tres, mais a unica duplicacao que a tela precisou:
o rotulo em PT de cada metodo.

Nada toca banco: e' leitura de codigo-fonte e de constante.
"""

import os
import re
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RAIZ = os.path.dirname(os.path.dirname(_BACKEND))
sys.path.insert(0, _BACKEND)

_FRONT = os.path.join(os.path.dirname(_BACKEND), "frontend", "src")
_MOTOR = os.path.join(_RAIZ, "ApostaEsportivas", "src")


def _ler(*partes) -> str:
    with open(os.path.join(*partes), encoding="utf-8") as f:
        return f.read()


# ── o backend ────────────────────────────────────────────────────────────
def test_o_follow_aceita_pick_de_jogador():
    import routers.banca as banca

    assert "player_stats" in banca.STAKE_LIMITS
    minimo, maximo = banca.STAKE_LIMITS["player_stats"]
    # Teto igual ao dos outros mercados proprios, nao ao do VIP: amostra
    # historica menor, entao a incerteza da estimativa e' maior mesmo com
    # margem boa.
    assert (minimo, maximo) == (1, 6)


def test_a_banca_soma_o_pick_de_jogador():
    import routers.banca as banca

    assert banca._TABELAS_MERCADO.get("player_stats", (None,))[0] == "picks_player_stats"


def test_o_resolve_pick_sabe_ler_a_tabela():
    """Sem o ramo, `_resolve_pick` devolve None e o follow responde 404 num
    pick que existe."""
    src = _ler(_BACKEND, "routers", "banca.py")
    assert 'pick_type == "player_stats"' in src
    assert "FROM picks_player_stats pp" in src


def test_o_ranking_publico_nao_descarta_a_aposta():
    # JOIN e CASE saem de `pick_sources` desde 29/08 (ver o teste irmao em
    # test_home_2026_08.py) · a assercao segue a fonte em vez do literal.
    import pick_sources

    ativas = list(pick_sources._FONTES)
    assert "picks_player_stats" in pick_sources.joins_sql(ativas)
    # Precisa do CASE de result E do de profit · so' um dos dois zera o lucro
    # sem zerar a contagem, que e' pior que ficar de fora.
    for coluna in ("result", "profit"):
        assert "'player_stats'" in pick_sources.case_sql(ativas, coluna)


def test_o_placar_publico_conta_a_fonte():
    src = _ler(_BACKEND, "routers", "public.py")
    assert "_sub_mercado(\"picks_player_stats\"" in src


# ── o frontend ───────────────────────────────────────────────────────────
def test_a_aba_mercados_desenha_a_secao():
    src = _ler(_FRONT, "pages", "Picks.tsx")
    assert "today?.player_stats" in src, "a tela nao le a chave que o backend devolve"
    assert 'tipo="player_stats"' in src, "a secao nao e' desenhada"


def test_o_card_e_o_mesmo_do_vip():
    """Card paralelo foi justamente o que produziu a deriva de faltas/goleiros
    (ficou sem stake, sem lucro potencial, sem odd real do usuario). A traducao
    pro formato do SuggestionCard e' o unico caminho."""
    src = _ler(_FRONT, "pages", "Picks.tsx")
    assert "mercadoParaSuggestion(p, 'player_stats')" in src


def test_o_teto_de_unidades_bate_com_o_backend():
    """O modal deixava escolher mais unidades do que o backend aceita e a
    aposta so' falhava no POST, com erro generico depois da confirmacao."""
    import routers.banca as banca

    src = _ler(_FRONT, "components", "SuggestionCard.tsx")
    achado = re.search(r"MAX_UNITS_POR_TIPO[^}]*player_stats:\s*(\d+)", src, re.S)
    assert achado, "player_stats fora do teto por tipo do card"
    assert int(achado.group(1)) == banca.STAKE_LIMITS["player_stats"][1]


def test_o_peso_de_stake_bate_dos_dois_lados():
    """Peso diferente entre back e front faria a mesma aposta valer unidades
    diferentes no calculo e na tela."""
    from stake_plan import STAKE_PADRAO

    src = _ler(_FRONT, "utils", "stakePlan.ts")
    achado = re.search(r"player_stats:\s*(\d+)", src)
    assert achado
    assert int(achado.group(1)) == STAKE_PADRAO["player_stats"]


# ── a unica duplicacao ───────────────────────────────────────────────────
def test_todo_metodo_do_motor_tem_rotulo_na_tela():
    """`market` guarda o nome do mercado NA CASA, em ingles ("Player Shots on
    Target"). A tela troca pelo rotulo do metodo, e a lista dele vive no motor
    (player_stats_engine/methods.py). Este teste e' o que impede as duas de se
    abrirem em duas -- mesmo servico que test_estatistica_a_mao presta pra
    definicao de folha completa.
    """
    metodos = _ler(_MOTOR, "services", "player_stats_engine", "methods.py")
    slugs = set(re.findall(r'slug="([a-z_]+)"', metodos))
    assert slugs, "nenhum metodo lido do catalogo do motor"

    tela = _ler(_FRONT, "pages", "Picks.tsx")
    bloco = tela[tela.index("const LABEL_DO_METODO"):]
    bloco = bloco[:bloco.index("}")]
    rotulados = set(re.findall(r"^\s*([a-z_]+):", bloco, re.M))

    faltando = slugs - rotulados
    assert not faltando, f"metodo sem rotulo em PT na tela: {sorted(faltando)}"
