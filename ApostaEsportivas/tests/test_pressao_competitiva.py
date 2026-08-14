"""Camada de necessidade competitiva em pontos corridos (2026-08-14).

O caso que o usuario levantou e que da nome a metade destes testes:

    "um time em 10o lugar na rodada 5 e' diferente do mesmo time em 10o na
     rodada 35, estando perto do rebaixamento"

A tabela de producao so' tem rodada ~22 hoje, entao o fim de campeonato -- que
e' onde a camada precisa morder -- e' construido aqui.
"""
import pytest

from services.pick_engine import competitive_pressure as cp
from services.pick_engine import context_gate, context_model


def _tabela(pontos_por_rank: list, jogadas: int, formas: dict | None = None,
            zonas: dict | None = None, n_times: int = 20):
    """Tabela sintetica no formato de league_standings.

    `zonas` mapeia rank -> description; os ranks nao citados ficam sem
    descricao (meio de tabela), como a API faz de verdade.
    """
    zonas = zonas or {}
    formas = formas or {}
    linhas = []
    for i in range(n_times):
        rank = i + 1
        pontos = pontos_por_rank[i] if i < len(pontos_por_rank) else max(0, 40 - rank)
        linhas.append({
            "team_id": 100 + rank, "team_name": f"Time {rank}", "rank": rank,
            "points": pontos, "goal_diff": 0, "form": formas.get(rank, "DDDDD"),
            "played": jogadas, "wins": 0, "draws": 0, "losses": 0,
            "description": zonas.get(rank),
        })
    return linhas


#: Desenho do Brasileirao: G4 de Libertadores, 5o de qualificacao, 6-11
#: Sudamericana, 17-20 rebaixamento.
_ZONAS_BR = {
    **{r: "Promotion - Copa Libertadores (Group Stage)" for r in (1, 2, 3, 4)},
    5: "Promotion - Copa Libertadores (Qualification)",
    **{r: "Promotion - Copa Sudamericana (Group Stage)" for r in range(6, 12)},
    **{r: "Relegation - Serie B" for r in (17, 18, 19, 20)},
}


# ───────────────────────── zonas e fronteiras ──────────────────────────


def test_zonas_nao_fundem_libertadores_com_sul_americana():
    """As duas viram CONTINENTAL, mas sao objetivos diferentes -- fundir apaga
    a fronteira do G4, pela qual meio campeonato joga."""
    zonas = cp.mapear_zonas(_tabela([50 - r for r in range(20)], 22, zonas=_ZONAS_BR))
    limites = [(z["rank_de"], z["rank_ate"], z["tipo"]) for z in zonas]
    assert (1, 1, cp.TITULO) in limites          # o lider disputa o titulo
    assert (2, 4, cp.CONTINENTAL) in limites     # o resto do G4, separado
    assert (5, 5, cp.CONTINENTAL) in limites
    assert (17, 20, cp.REBAIXAMENTO) in limites


def test_zona_de_rebaixamento_sai_da_marcacao_da_api():
    assert cp.classificar_zona("Relegation - Serie B") == cp.REBAIXAMENTO
    assert cp.classificar_zona("Relegation Playoffs") == cp.REBAIXAMENTO
    assert cp.classificar_zona("Promotion Play-offs") == cp.PROMOCAO
    assert cp.classificar_zona("Champions League league stage") == cp.CONTINENTAL
    assert cp.classificar_zona(None) == cp.NEUTRA


def test_rodadas_totais_saem_do_tamanho_da_tabela():
    assert cp.rodadas_totais(_tabela([], 10, n_times=20)) == 38
    assert cp.rodadas_totais(_tabela([], 10, n_times=18)) == 34
    assert cp.rodadas_totais([]) is None


# ─────────────── o caso do usuario: mesma posicao, rodadas diferentes ───────


def _decimo_colocado(jogadas):
    """10o lugar, 4 pontos acima do Z4 -- variando so' a rodada."""
    pontos = [60, 58, 55, 52, 50, 48, 46, 44, 42, 40,
              39, 38, 37, 37, 36, 36, 36, 30, 25, 20]
    tabela = _tabela(pontos, jogadas, zonas=_ZONAS_BR)
    return cp.situacao(tabela, 110)   # team_id do rank 10


def test_decimo_na_rodada_5_nao_gera_necessidade():
    s = _decimo_colocado(5)
    assert s["necessidade"] == 0.0
    assert "tabela ainda nao informa" in s["motivo"]


def test_decimo_na_rodada_35_gera_necessidade_real():
    s = _decimo_colocado(35)
    assert s["necessidade"] > 0.30
    assert s["rodadas_restantes"] == 3


def test_a_necessidade_cresce_com_a_rodada_sem_degrau():
    """Rampa continua: o corte binario da primeira versao fazia a rodada 13 e
    a rodada 37 valerem igual."""
    valores = [_decimo_colocado(r)["necessidade"] for r in (5, 12, 20, 28, 35)]
    assert valores == sorted(valores)
    assert valores[0] == 0.0 and valores[-1] > valores[2] > 0


# ───────────────────── ordenacao dentro da mesma rodada ────────────────────


def test_quem_esta_no_z4_precisa_mais_que_quem_esta_no_meio_da_tabela():
    """Pesar so' a zona de DESTINO invertia o campeonato: quem esta' dentro do
    Z4 tem como alvo a zona neutra (peso 0) e aparecia mais tranquilo que o
    12o colocado. Achado validando contra a tabela real do Brasileirao."""
    pontos = [60, 58, 55, 52, 50, 48, 46, 44, 42, 40,
              39, 38, 37, 36, 35, 34, 33, 32, 25, 20]
    tabela = _tabela(pontos, 34, zonas=_ZONAS_BR)
    dentro_do_z4 = cp.situacao(tabela, 117)     # rank 17
    meio_de_tabela = cp.situacao(tabela, 112)   # rank 12
    assert dentro_do_z4["necessidade"] > meio_de_tabela["necessidade"]
    assert dentro_do_z4["zona_atual"] == cp.REBAIXAMENTO


def test_lider_folgado_quase_nao_tem_necessidade():
    pontos = [80, 60, 58, 55, 52, 50, 48, 46, 44, 42,
              40, 39, 38, 37, 36, 35, 34, 33, 25, 20]
    tabela = _tabela(pontos, 34, zonas=_ZONAS_BR)
    lider = cp.situacao(tabela, 101)
    assert lider["necessidade"] < 0.20


def test_diferenca_fora_de_alcance_nao_e_mais_disputa():
    """14 pontos com 3 rodadas (9 em disputa) nao e' pressao, e' aritmetica
    encerrada."""
    pontos = [60, 58, 55, 52, 50, 48, 46, 44, 42, 40,
              38, 36, 34, 32, 30, 28, 26, 24, 22, 5]
    tabela = _tabela(pontos, 35, zonas=_ZONAS_BR)
    lanterna = cp.situacao(tabela, 120)
    alvo = lanterna["alvo_acima"]
    assert alvo["pontos_de_distancia"] > lanterna["pontos_em_disputa"]
    # Ainda tem o piso de estar na zona, mas nao a urgencia da fronteira.
    assert lanterna.get("urgencia_alvo") == 0.0


def test_forma_ruim_perto_da_fronteira_aumenta_a_necessidade():
    pontos = [60, 58, 55, 52, 50, 48, 46, 44, 42, 40,
              39, 38, 37, 36, 35, 34, 33, 32, 25, 20]
    caindo = _tabela(pontos, 34, zonas=_ZONAS_BR, formas={16: "LLLLL"})
    subindo = _tabela(pontos, 34, zonas=_ZONAS_BR, formas={16: "WWWWW"})
    assert cp.situacao(caindo, 116)["necessidade"] > cp.situacao(subindo, 116)["necessidade"]


def test_forma_le_o_formato_da_api():
    assert cp.pontos_da_forma("WWDLL") == {
        "jogos": 5, "pontos": 7, "por_jogo": 1.4, "sequencia": "WWDLL"}
    assert cp.pontos_da_forma(None) is None
    assert cp.pontos_da_forma("") is None


# ──────────────────────── leitura da PARTIDA ───────────────────────────────


def _tabela_fim_de_ano():
    pontos = [60, 58, 55, 52, 50, 48, 46, 44, 42, 40,
              39, 38, 37, 36, 35, 34, 33, 32, 30, 20]
    return _tabela(pontos, 35, zonas=_ZONAS_BR)


def test_dois_times_na_briga_produzem_intensidade_alta():
    tabela = _tabela_fim_de_ano()
    p = cp.pressao_da_partida(tabela, 116, 117)   # 16o x 17o, linha do Z4
    assert p["disponivel"]
    assert p["intensidade"] > 0.5
    assert p["confronto_direto"]["direto"]


def test_desesperado_contra_acomodado_produz_assimetria():
    """Tabela com um meio ISOLADO de proposito: no fixture apertado de
    _tabela_fim_de_ano nao existe time acomodado -- ate' o lider estava a 2
    pontos do 2o com 3 rodadas, que e' briga de titulo, nao conforto."""
    pontos = [70, 66, 62, 58, 54, 50, 48, 47, 46, 45,
              44, 43, 32, 22, 21, 20, 19, 18, 17, 16]
    tabela = _tabela(pontos, 35, zonas=_ZONAS_BR)
    # 13o: 12 pontos abaixo da zona continental e 13 acima do Z4, com so' 9
    # ainda em disputa -- nao alcanca nem e' alcancado. Fim de temporada dele.
    acomodado = cp.situacao(tabela, 113)
    assert acomodado["necessidade"] == 0.0
    p = cp.pressao_da_partida(tabela, 113, 118)   # acomodado x dentro do Z4
    assert p["assimetria"] > 0.3


def test_sem_tabela_a_camada_e_inerte():
    """Copa/mata-mata nao tem classificacao coletada -- e ausencia de dado
    nunca pode virar sinal."""
    p = cp.pressao_da_partida([], 1, 2)
    assert p["disponivel"] is False
    assert p["intensidade"] == 0.0


def test_copa_de_clube_nao_usa_a_camada_nem_com_tabela_coletada():
    """A Sudamericana (liga 11) tem 32 times numa tabela unica de fase de
    grupos, onde cada um joga 6 partidas. A formula de pontos corridos leria
    62 rodadas e trataria a fase inteira como comeco de temporada -- da o
    numero certo por acidente aritmetico, e acidente nao e' decisao."""
    tabela = _tabela([12, 10, 9, 7], 6, n_times=32)
    p = cp.pressao_da_partida(tabela, 101, 102, league_id=11)
    assert p["disponivel"] is False
    assert "pontos corridos" in p["motivo"]
    # A mesma tabela numa liga de verdade passa pela camada.
    assert cp.vale_para_a_competicao(71) is True
    assert cp.vale_para_a_competicao(13) is False   # Libertadores


def test_time_fora_da_tabela_nao_inventa_situacao():
    s = cp.situacao(_tabela_fim_de_ano(), 999)
    assert s["disponivel"] is False
    assert s["necessidade"] == 0.0


# ─────────────────────────── integracao ────────────────────────────────────


def test_context_score_usa_a_camada_medida_quando_ela_existe():
    tabela = _tabela_fim_de_ano()
    p = cp.pressao_da_partida(tabela, 116, 117)
    com = context_model.context_score({"pressao_competitiva": p, "round_phase": None})
    sem = context_model.context_score({"pressao_competitiva": None, "round_phase": None})
    assert com > sem


def test_context_score_nao_passa_do_teto_antigo():
    """O bonus antigo somava ate 0.06 (0.03 por lado). O topo da escala nao
    subiu -- o que mudou e' que agora ele exige uma partida que valha isso."""
    p = {"disponivel": True, "intensidade": 1.0, "assimetria": 1.0}
    score = context_model.context_score({"pressao_competitiva": p, "round_phase": None})
    assert score == pytest.approx(0.56, abs=1e-4)


def test_mata_mata_nao_recebe_pressao_de_tabela():
    """A classificacao da fase de liga nao descreve mais a partida quando o
    mata-mata comecou -- regra que ja valia pro bonus antigo."""
    p = {"disponivel": True, "intensidade": 1.0, "assimetria": 0.0}
    score = context_model.context_score(
        {"pressao_competitiva": p, "round_phase": "KNOCKOUT_TWO_LEGS"})
    assert score == 0.5


def test_gate_penaliza_under_em_jogo_de_tabela_apertada():
    tabela = _tabela_fim_de_ano()
    ctx = {"pressao_competitiva": cp.pressao_da_partida(tabela, 116, 117),
           "stakes": 0.5, "tie": {}, "rivalidade": {}}
    under = context_gate.evaluate({"market_type": "corners", "value": "Under"}, ctx)
    over = context_gate.evaluate({"market_type": "corners", "value": "Over"}, ctx)
    assert under["pressao_total"] > 0
    # Confirmar nao gera bonus -- so o lado contrariado e penalizado.
    assert over["pressao_total"] == 0.0


def test_gate_ignora_tabela_folgada():
    pontos = [80, 70, 60, 55, 50, 48, 46, 44, 42, 40,
              38, 36, 34, 32, 30, 28, 20, 15, 10, 5]
    tabela = _tabela(pontos, 34, zonas=_ZONAS_BR)
    ctx = {"pressao_competitiva": cp.pressao_da_partida(tabela, 102, 103),
           "stakes": 0.5, "tie": {}, "rivalidade": {}}
    assert context_gate.evaluate({"market_type": "corners", "value": "Under"}, ctx)["pressao_total"] == 0.0
