"""Necessidade do resultado no motor Live (2026-08-14).

A regra que estes testes travam, e que e' o pedido inteiro:

    o contexto pre-jogo diz o REGULAMENTO (agregado da ida, o que cada lado
    precisa na tabela); o campo diz o que esta' acontecendo. Onde os dois
    discordam, quem ganha e' o campo.
"""
import pytest

from services.pick_engine_live import need_model as nm
from services.pick_engine_live import residual_model as rm
from services.pick_engine_live import signal_score


def _estado(minuto=70, home=0, away=0, **extra):
    return {"minuto": minuto, "home_goals": home, "away_goals": away,
            "goals_total": home + away,
            "diferenca_gols": abs(home - away),
            "saldo_mandante": home - away, **extra}


def _tie(ida_home=1, ida_away=0, volta=True, peso=0.70):
    return {"is_mata_mata": True, "is_jogo_de_volta": volta,
            "agregado_home": ida_home, "agregado_away": ida_away,
            "peso_fase": peso, "fase": "QUARTAS"}


# ───────────────────────── urgencia temporal ────────────────────────────


def test_precisar_de_gol_cedo_ainda_nao_e_comportamento():
    assert nm.urgencia_temporal(20) == 0.0
    assert nm.urgencia_temporal(55) == 0.0


def test_a_urgencia_cresce_com_o_cronometro():
    assert nm.urgencia_temporal(60) < nm.urgencia_temporal(75) < nm.urgencia_temporal(88)
    assert nm.urgencia_temporal(90) <= nm.URGENCIA_MAXIMA


def test_sem_minuto_nao_ha_urgencia():
    assert nm.urgencia_temporal(None) == 0.0


# ──────────────────── agregado recalculado EM CAMPO ─────────────────────


def test_agregado_soma_a_ida_com_o_placar_de_agora():
    """Mandante perdeu a ida por 1x0 (jogando fora, entao na volta ele e' o
    `agregado_away` da ida... o tie ja' resolve isso por team_id). Aqui: ida
    0x1 contra o mandante de hoje, e ele vence a volta por 1x0 -> empatado."""
    ag = nm.agregado_ao_vivo(_tie(ida_home=0, ida_away=1), saldo_mandante=1)
    assert ag["diferenca_agregada"] == 0
    assert ag["quem_precisa"] == nm.AMBOS


def test_agregado_identifica_quem_precisa_reverter():
    ag = nm.agregado_ao_vivo(_tie(ida_home=2, ida_away=0), saldo_mandante=0)
    assert ag["diferenca_agregada"] == 2
    assert ag["quem_precisa"] == nm.AWAY and ag["lider"] == nm.HOME


def test_gol_em_campo_vira_o_confronto():
    """O ponto do modulo: o agregado NAO e' um campo herdado do pre-jogo."""
    tie = _tie(ida_home=0, ida_away=1)
    assert nm.agregado_ao_vivo(tie, saldo_mandante=0)["quem_precisa"] == nm.HOME
    assert nm.agregado_ao_vivo(tie, saldo_mandante=2)["quem_precisa"] == nm.AWAY


def test_jogo_de_ida_nao_tem_agregado():
    assert nm.agregado_ao_vivo(_tie(volta=False), saldo_mandante=1) is None
    assert nm.agregado_ao_vivo(None, saldo_mandante=1) is None


# ─────────────────────────── necessidade ────────────────────────────────


def test_sem_contexto_a_necessidade_e_zero_e_diz_por_que():
    """Jogo sem contexto LIDO nao e' jogo sem contexto -- os dois nao podem
    produzir o mesmo numero por acidente."""
    n = nm.necessidade(_estado(), None)
    assert n["disponivel"] is False and n["intensidade"] == 0.0
    assert n["motivo"] == "sem contexto pre-jogo carregado"


def test_mata_mata_apertado_no_fim_produz_necessidade_alta():
    n = nm.necessidade(_estado(minuto=85, home=0, away=0), {"tie": _tie(0, 1)})
    assert n["quem_precisa"] == nm.HOME
    assert n["intensidade"] > 0.3
    assert n["origem"] == "mata_mata"


def test_a_mesma_situacao_no_comeco_do_jogo_nao_pesa():
    cedo = nm.necessidade(_estado(minuto=30), {"tie": _tie(0, 1)})
    tarde = nm.necessidade(_estado(minuto=85), {"tie": _tie(0, 1)})
    assert cedo["intensidade"] == 0.0
    assert tarde["intensidade"] > 0.0


def test_agregado_empatado_deixa_os_dois_precisando():
    n = nm.necessidade(_estado(minuto=80), {"tie": _tie(1, 1)})
    assert n["quem_precisa"] == nm.AMBOS
    assert "agregado empatado" in " ".join(n["descricao"])


def test_peso_da_fase_modula_a_necessidade():
    final = nm.necessidade(_estado(minuto=85), {"tie": _tie(0, 1, peso=1.00)})
    fase_32 = nm.necessidade(_estado(minuto=85), {"tie": _tie(0, 1, peso=0.50)})
    assert final["intensidade"] > fase_32["intensidade"]


# ─────────────────── tabela: placar corrige a necessidade ───────────────


def _pressao(nec_home=0.8, nec_away=0.1):
    return {"disponivel": True, "intensidade": max(nec_home, nec_away),
            "assimetria": abs(nec_home - nec_away),
            "home": {"disponivel": True, "necessidade": nec_home},
            "away": {"disponivel": True, "necessidade": nec_away}}


def test_quem_precisa_de_pontos_e_esta_perdendo_precisa_do_resultado_inteiro():
    n = nm.necessidade(_estado(minuto=80, home=0, away=1),
                       {"pressao_competitiva": _pressao()})
    assert n["quem_precisa"] == nm.HOME
    assert n["precisa_home"] == pytest.approx(0.8)


def test_quem_precisa_de_pontos_mas_esta_GANHANDO_nao_forca():
    """O cruzamento que faltava: necessidade de PONTOS nao e' necessidade de
    mudar o placar. Time desesperado que esta' vencendo administra -- e quem
    passa a precisar e' o outro lado, que agora esta' perdendo."""
    n = nm.necessidade(_estado(minuto=80, home=1, away=0),
                       {"pressao_competitiva": _pressao(nec_home=0.8, nec_away=0.1)})
    assert n["precisa_home"] == 0.0
    assert n["quem_precisa"] == nm.AWAY


def test_ninguem_precisa_quando_o_placar_ja_serve_a_quem_tinha_pressao():
    """Mandante pressionado esta' ganhando e o visitante nao precisava de nada:
    ninguem tem motivo pra mudar o jogo."""
    n = nm.necessidade(_estado(minuto=80, home=1, away=0),
                       {"pressao_competitiva": _pressao(nec_home=0.8, nec_away=0.0)})
    assert n["quem_precisa"] is nm.NINGUEM
    assert n["intensidade"] == 0.0


def test_empate_serve_pela_metade():
    n = nm.necessidade(_estado(minuto=80, home=0, away=0),
                       {"pressao_competitiva": _pressao()})
    assert 0 < n["precisa_home"] < 0.8


def test_mata_mata_manda_na_tabela():
    """Onde ha eliminacao em jogo, a classificacao nao decide nada."""
    n = nm.necessidade(_estado(minuto=80, home=1, away=0),
                       {"tie": _tie(0, 2), "pressao_competitiva": _pressao()})
    assert n["origem"] == "mata_mata"
    assert n["quem_precisa"] == nm.HOME   # ainda perde por 1 no agregado


# ─────────────────── o campo desmente o contexto ────────────────────────


def test_contexto_desmentido_pelo_campo_desconta_a_projecao():
    """'aos 30 minutos o mandante nao cria nada -> nao continuar assumindo
    pressao apenas pelo contexto'."""
    n = nm.necessidade(_estado(minuto=85), {"tie": _tie(0, 1)})
    parado = nm.confirma_o_contexto(n, {"total": 0.35})
    ativo = nm.confirma_o_contexto(n, {"total": 0.70})
    assert parado["fator"] < 1.0 < ativo["fator"]
    assert parado["alinhado"] is False


def test_desmentir_pesa_mais_que_confirmar():
    """Confirmar so' repete o que a pressao ja' disse; desmentir e'
    informacao nova."""
    n = nm.necessidade(_estado(minuto=85), {"tie": _tie(0, 1)})
    parado = nm.confirma_o_contexto(n, {"total": 0.35})
    ativo = nm.confirma_o_contexto(n, {"total": 0.70})
    assert (1 - parado["fator"]) > (ativo["fator"] - 1)


def test_sem_necessidade_nao_ha_o_que_confirmar():
    c = nm.confirma_o_contexto(None, {"total": 0.70})
    assert c["aplicavel"] is False and c["fator"] == 1.0


# ─────────────────────────── integracao ─────────────────────────────────


def test_necessidade_entra_no_lambda_residual():
    estado = _estado(minuto=85)
    n = nm.necessidade(estado, {"tie": _tie(0, 1)})
    com = rm.ajuste_estado("corners", estado, necessidade=n,
                           confirmacao={"fator": 1.0})
    sem = rm.ajuste_estado("corners", estado)
    assert com["fator"] > sem["fator"]
    assert any("necessidade" in c["motivo"] for c in com["componentes"])


def test_necessidade_desmentida_nao_infla_o_lambda():
    estado = _estado(minuto=85)
    n = nm.necessidade(estado, {"tie": _tie(0, 1)})
    desmentida = nm.confirma_o_contexto(n, {"total": 0.30})
    com = rm.ajuste_estado("corners", estado, necessidade=n, confirmacao=desmentida)
    sem = rm.ajuste_estado("corners", estado)
    assert com["fator"] <= sem["fator"]


def test_necessidade_sustenta_over_e_contradiz_under():
    estado = _estado(minuto=85)
    n = nm.necessidade(estado, {"tie": _tie(0, 1)})
    comum = dict(familia="corners", estado=estado, pressao={"total": 0.6},
                 ritmo={"score": 1.0}, tendencia=None, janelas=None,
                 taxa_estimada_min=None, necessidade=n)
    over = signal_score.convergencia(direcao="over", **comum)
    under = signal_score.convergencia(direcao="under", **comum)
    achar = lambda c: next(s for s in c["sinais"] if s["sinal"] == "necessidade_resultado")
    assert achar(over)["posicao"] == "a_favor"
    assert achar(under)["posicao"] == "contra"


def test_pesos_da_convergencia_somam_um():
    assert sum(signal_score.PESOS.values()) == pytest.approx(1.0, abs=1e-9)


def test_estado_guarda_o_placar_com_sinal():
    """Sem o sinal, 2x0 e 0x2 eram o mesmo estado -- e nenhuma pergunta de
    'quem precisa' tinha resposta."""
    assert _estado(home=2, away=0)["saldo_mandante"] == 2
    assert _estado(home=0, away=2)["saldo_mandante"] == -2
    assert _estado(home=2, away=0)["diferenca_gols"] == _estado(home=0, away=2)["diferenca_gols"]
