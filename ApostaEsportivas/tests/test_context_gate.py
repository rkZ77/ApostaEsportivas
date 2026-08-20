"""Gate de contexto: o caso Fluminense x Vasco.

"Under cartoes" aprovado num classico, jogo de volta valendo classificacao. A
taxa historica vinha de 15 jogos de pontos corridos e estava certa PRA AQUELE
UNIVERSO -- o erro nao foi de calculo, foi de universo.

O gate anterior (referee_model.cards_market_eligible) era cego a direcao: so'
bloqueava jogo frio, e liberava jogo quente inteiro, Over e Under igualmente.
"""
from datetime import date

import pytest

from services.pick_engine import context_gate, match_context_model, rivalry_model


# ======================================================================
# Leitura do round
# ======================================================================
@pytest.mark.parametrize("texto,leg", [
    ("Quarter-finals - 2nd Leg", 2), ("Round of 16 - 1st Leg", 1),
    ("Semi-finals - 2nd Leg", 2), ("Final - 1st Leg", 1),
    ("Regular Season - 12", None), ("Group Stage - 3", None),
])
def test_identifica_ida_e_volta(texto, leg):
    assert match_context_model.parse_leg(texto) == leg


@pytest.mark.parametrize("texto,fase", [
    ("Quarter-finals - 2nd Leg", "QUARTAS"),
    ("Semi-finals - 1st Leg", "SEMIFINAL"),
    ("Round of 16 - 2nd Leg", "OITAVAS"),
    ("Final", "FINAL"),
    ("Regular Season - 12", None),
])
def test_identifica_a_fase(texto, fase):
    assert match_context_model.parse_fase(texto) == fase


def test_semifinal_nao_e_confundida_com_final():
    """'Semi-finals' contem 'final' como substring -- a ordem dos padroes
    importa e este teste trava ela."""
    assert match_context_model.parse_fase("Semi-finals - 2nd Leg") == "SEMIFINAL"


# ======================================================================
# Agregado
# ======================================================================
FLU, VASCO = 100, 200


def _ida(gols_flu, gols_vasco, league_id=73, quando=date(2026, 7, 30)):
    """Ida com o Flu de mandante."""
    return {"match_date": quando, "league_id": league_id, "season": 2026,
            "home_team_id": FLU, "away_team_id": VASCO,
            "home_goals": gols_flu, "away_goals": gols_vasco,
            "home_yellow_cards": 3, "away_yellow_cards": 3,
            "home_red_cards": 0, "away_red_cards": 0}


def test_agregado_resolve_o_mando_invertido_na_volta():
    """Na volta o Vasco e' mandante. Os gols tem que seguir o TIME, nao a
    coluna home/away -- e' onde um calculo de agregado erra de sinal."""
    ctx = match_context_model.tie_context(
        "Quarter-finals - 2nd Leg", home_team_id=VASCO, away_team_id=FLU,
        jogo_de_ida=_ida(gols_flu=2, gols_vasco=1),
    )
    assert ctx["is_jogo_de_volta"] is True
    assert ctx["agregado_home"] == 1     # Vasco fez 1 na ida
    assert ctx["agregado_away"] == 2     # Flu fez 2 na ida
    assert ctx["lider_agregado"] == "away"
    assert ctx["precisa_de_resultado"] == "home"


def test_ida_empatada_obriga_os_dois():
    ctx = match_context_model.tie_context(
        "Semi-finals - 2nd Leg", VASCO, FLU, _ida(1, 1))
    assert ctx["precisa_de_resultado"] == "ambos"
    assert ctx["empate_classifica"] is None


def test_jogo_de_ida_nao_tem_agregado():
    ctx = match_context_model.tie_context("Quarter-finals - 1st Leg", FLU, VASCO, None)
    assert ctx["is_jogo_de_volta"] is False
    assert ctx["agregado_home"] is None


def test_campeonato_de_pontos_corridos_nao_e_mata_mata():
    ctx = match_context_model.tie_context("Regular Season - 12", FLU, VASCO, None)
    assert ctx["is_mata_mata"] is False
    assert match_context_model.stakes_score(ctx) == 0.5


def test_volta_decisiva_pesa_mais_que_ida_de_fase_inicial():
    volta_semi = match_context_model.tie_context("Semi-finals - 2nd Leg", VASCO, FLU, _ida(1, 1))
    ida_oitavas = match_context_model.tie_context("Round of 16 - 1st Leg", FLU, VASCO, None)
    assert (match_context_model.stakes_score(volta_semi)
            > match_context_model.stakes_score(ida_oitavas))


def test_encontrar_ida_ignora_confronto_de_outra_competicao():
    """O classico do campeonato tres meses atras nao e' a ida do mata-mata."""
    h2h = [
        _ida(2, 1, league_id=73, quando=date(2026, 7, 30)),   # Copa do Brasil
        _ida(0, 0, league_id=71, quando=date(2026, 8, 2)),    # Brasileirao, mais recente
    ]
    achado = match_context_model.encontrar_jogo_de_ida(h2h, league_id=73, season=2026)
    assert achado["match_date"] == date(2026, 7, 30)


# ======================================================================
# Rivalidade medida
# ======================================================================
def _confronto(amarelos_casa, amarelos_fora, vermelhos=0):
    return {"home_team_id": FLU, "away_team_id": VASCO,
            "home_yellow_cards": amarelos_casa, "away_yellow_cards": amarelos_fora,
            "home_red_cards": vermelhos, "away_red_cards": 0}


def test_rivalidade_medida_no_h2h_nao_listada():
    """Nenhuma lista de classicos: o excesso sai do proprio historico."""
    h2h = [_confronto(4, 4) for _ in range(6)]     # 8 pontos por confronto
    sinal = rivalry_model.rivalry_signal(h2h, baseline_cartoes=4.5)
    assert sinal["confiavel"] is True
    assert sinal["label"] == "rivalidade_alta"
    assert sinal["excesso"] == pytest.approx(3.5)


def test_confronto_sem_excesso_nao_vira_rivalidade():
    h2h = [_confronto(2, 2) for _ in range(6)]     # 4 pontos, igual a base
    sinal = rivalry_model.rivalry_signal(h2h, baseline_cartoes=4.0)
    assert sinal["label"] == "normal"


def test_amostra_curta_nao_sustenta_rivalidade():
    """Ausencia de dado nunca vira evidencia."""
    sinal = rivalry_model.rivalry_signal([_confronto(5, 5)], baseline_cartoes=4.0)
    assert sinal["confiavel"] is False
    assert rivalry_model.intensity_delta(sinal) == 0.0


def test_vermelho_conta_dobrado_no_h2h():
    com_vermelho = rivalry_model.rivalry_signal(
        [_confronto(3, 3, vermelhos=1) for _ in range(5)], baseline_cartoes=4.0)
    sem_vermelho = rivalry_model.rivalry_signal(
        [_confronto(3, 3) for _ in range(5)], baseline_cartoes=4.0)
    assert com_vermelho["media_h2h"] - sem_vermelho["media_h2h"] == pytest.approx(2.0)


# ======================================================================
# O gate, e o caso completo
# ======================================================================
def _confronto_completo(amarelos_casa, amarelos_fora, gols_flu=2, gols_vasco=1):
    """Confronto direto com placar E cartoes explicitos.

    Montado campo a campo de proposito: a primeira versao deste teste fazia
    {**_confronto(...), **_ida(...)}, e o merge sobrescrevia a contagem de
    cartoes pela do outro dict -- a fixture media 6 pontos quando dizia medir
    8, e o caso "classico pesado" nao era o que estava sendo testado.
    """
    return {"match_date": date(2026, 7, 30), "league_id": 73, "season": 2026,
            "home_team_id": FLU, "away_team_id": VASCO,
            "home_goals": gols_flu, "away_goals": gols_vasco,
            "home_yellow_cards": amarelos_casa, "away_yellow_cards": amarelos_fora,
            "home_red_cards": 0, "away_red_cards": 0}


def _contexto_flu_vasco():
    """Classico pesado: 8 pontos de cartao por confronto contra base 4,5."""
    return context_gate.build_context(
        round_str="Quarter-finals - 2nd Leg",
        home_team_id=VASCO, away_team_id=FLU,
        h2h_matches=[_confronto_completo(4, 4) for _ in range(6)],
        league_id=73, season=2026, baseline_cartoes=4.5,
    )


def _contexto_classico_morno():
    """Mesmo mata-mata, mas confronto sem excesso disciplinar real."""
    return context_gate.build_context(
        round_str="Quarter-finals - 2nd Leg",
        home_team_id=VASCO, away_team_id=FLU,
        h2h_matches=[_confronto_completo(2, 2) for _ in range(6)],
        league_id=73, season=2026, baseline_cartoes=4.5,
    )


def _cand(market_type, direcao, taxa=0.74):
    return {"market_type": market_type, "_direction": direcao, "taxa_real": taxa,
            "odd": 1.75, "market_name": f"{market_type} Mais/Menos",
            "value_label": f"{direcao} 5.5", "prob_baseline_value": 0.57}


def test_o_caso_flu_vasco_bloqueia_under_cartoes():
    """O pick que originou tudo isto."""
    ctx = _contexto_flu_vasco()
    veredito = context_gate.evaluate(_cand("cards", "under"), ctx)
    assert veredito["bloqueado"] is True
    assert veredito["motivos"]


def test_over_cartoes_no_mesmo_jogo_passa():
    """O gate e' direcional: barra o lado que contradiz, nao o mercado."""
    ctx = _contexto_flu_vasco()
    assert context_gate.evaluate(_cand("cards", "over"), ctx)["bloqueado"] is False


@pytest.mark.parametrize("familia", ["corners", "shots", "shots_on_target", "goals"])
def test_gate_vale_para_todas_as_familias_de_volume_nao_so_cartoes(familia):
    """Quem precisa do resultado se abre: sobe escanteio, chute e gol junto."""
    ctx = _contexto_flu_vasco()
    assert context_gate.evaluate(_cand(familia, "under"), ctx)["pressao_total"] > 0


def test_faltas_saiu_da_lista_de_volume():
    """`fouls` estava neste parametrize por mecanismo suposto ("falta tatica
    sobe quando o jogo abre") e saiu em 2026-08-19 por medicao: nos jogos de
    volta reais da base, quem precisa reverter comete 2.48 faltas A MENOS por
    jogo. Ver context_gate.FAMILIAS_DIRECIONAIS e tie_effect._MEDIDO."""
    ctx = _contexto_flu_vasco()
    assert context_gate.evaluate(_cand("fouls", "under"), ctx)["pressao_total"] == 0.0


def test_jogo_de_campeonato_comum_nao_sofre_nada():
    ctx = context_gate.build_context(
        "Regular Season - 12", FLU, VASCO, h2h_matches=[], league_id=71,
        season=2026, baseline_cartoes=4.5)
    veredito = context_gate.evaluate(_cand("cards", "under"), ctx)
    assert veredito["bloqueado"] is False
    assert veredito["penalidade"] == 0.0


def test_sem_contexto_o_gate_e_inerte():
    veredito = context_gate.evaluate(_cand("cards", "under"), None)
    assert veredito["bloqueado"] is False
    assert veredito["pressao_total"] == 0.0


def test_mercado_fora_das_familias_de_volume_nao_e_afetado():
    ctx = _contexto_flu_vasco()
    assert context_gate.evaluate(_cand("btts", "under"), ctx)["aplicavel"] is False


def test_classico_morno_penaliza_mas_nao_bloqueia():
    """A penalidade e' proporcional ao que foi MEDIDO -- mata-mata sem excesso
    disciplinar real nao merece o mesmo tratamento do classico pesado. E' o
    que separa isto de um 'if classico then reject'."""
    veredito = context_gate.evaluate(_cand("cards", "under"), _contexto_classico_morno())
    assert veredito["bloqueado"] is False
    assert veredito["penalidade"] > 0


def test_classico_pesado_pressiona_mais_que_o_morno():
    pesado = context_gate.evaluate(_cand("cards", "under"), _contexto_flu_vasco())
    morno = context_gate.evaluate(_cand("cards", "under"), _contexto_classico_morno())
    assert pesado["pressao_total"] > morno["pressao_total"]


def test_explicacao_de_rejeicao_lista_os_fatores():
    ctx = _contexto_flu_vasco()
    cand = _cand("cards", "under")
    texto = context_gate.explicar_rejeicao(cand, context_gate.evaluate(cand, ctx))
    assert "rejeitada porque" in texto
    assert texto.count("\n- ") >= 2      # mais de um fator listado
    assert "%" in texto                  # com o peso de cada um


def test_gate_pode_ser_desligado_por_configuracao():
    """Interruptor de producao: se o gate bloquear demais, desligar e' uma
    linha de config, sem reverter codigo."""
    from services.pick_engine.config import PickEngineConfig
    cfg = PickEngineConfig(use_context_gate=False)
    assert cfg.use_context_gate is False
    from services.pick_engine.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG.use_context_gate is True
