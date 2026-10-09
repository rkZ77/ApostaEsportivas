# -*- coding: utf-8 -*-
"""Perfil tatico medido (team_profile_model, 2026-10-08).

Prende: a orientacao (cada metrica do lado certo do jogo), o que nao existe
nao vira zero, o encolhimento pela amostra, a separacao por tecnico pelo
coach_id, a carreira separada do clube, o 2o tempo conforme o placar do
intervalo e a referencia da competicao.
"""
from datetime import date

import pytest

from services.pick_engine import team_profile_model as tpm

T, ADV = 10, 20


def jogo(d, casa=True, posse=60, passes=500, prec=85, chutes=15, imp_adv=3, faltas=10,
         esc=6, esc_ced=3, gols=2, ced=1, ht=(1, 0), chutes_1t=7, esc_1t=3,
         fora=5, dentro=10, xg=1.8, mes=9):
    eu, ele = ("home", "away") if casa else ("away", "home")
    m = {"match_date": date(2026, mes, d), "home_team_id": T if casa else ADV,
         "away_team_id": ADV if casa else T, "league_id": 71}
    m.update({f"{eu}_possession": posse, f"{ele}_possession": 100 - posse,
              f"{eu}_passes": passes, f"{eu}_passes_accuracy": prec,
              f"{eu}_total_shots": chutes, f"{ele}_offsides": imp_adv,
              f"{eu}_fouls": faltas, f"{eu}_corners": esc, f"{ele}_corners": esc_ced,
              f"{eu}_goals": gols, f"{ele}_goals": ced,
              f"{eu}_goals_ht": ht[0], f"{ele}_goals_ht": ht[1],
              f"{eu}_total_shots_1h": chutes_1t, f"{eu}_corners_1h": esc_1t,
              f"{eu}_shots_outsidebox": fora, f"{eu}_shots_insidebox": dentro,
              f"{eu}_xg": xg})
    return m


def test_metricas_saem_do_lado_certo_em_casa_e_fora():
    for casa in (True, False):
        mt = tpm.metricas_taticas_do_jogo(jogo(1, casa=casa), T)
        assert mt["posse"] == 60 and mt["escanteios"] == 6 and mt["escanteios_cedidos"] == 3
        assert mt["impedimentos_provocados"] == 3          # impedimento DO ADVERSARIO
        assert mt["chutes_por_100_passes"] == pytest.approx(3.0)
        assert mt["fracao_chutes_fora_da_area"] == pytest.approx(1 / 3, abs=1e-3)
        assert mt["xg_por_chute"] == pytest.approx(0.12)


def test_folha_nao_publicada_nao_vira_zero():
    m = jogo(1)
    for k in list(m):
        if k.endswith(("_xg", "_insidebox", "_outsidebox")):
            m[k] = None
    m["home_possession"] = 0          # posse 0 = folha vazia
    mt = tpm.metricas_taticas_do_jogo(m, T)
    assert "posse" not in mt and "xg_por_chute" not in mt
    assert "fracao_chutes_fora_da_area" not in mt


def test_poucos_jogos_ficam_perto_da_media_da_competicao():
    ref = {"posse": 50.0}
    um = tpm.perfil_tatico([jogo(1, posse=70)], T, ref)["metricas"]["posse"]
    vinte = tpm.perfil_tatico([jogo(d, posse=70) for d in range(1, 21)], T, ref)["metricas"]["posse"]
    assert um["media"] == 70 and um["encolhida"] == pytest.approx((70 + 5 * 50) / 6)
    assert vinte["encolhida"] == pytest.approx((20 * 70 + 5 * 50) / 25)
    assert abs(vinte["encolhida"] - 70) < abs(um["encolhida"] - 70)


def test_sem_jogos_o_perfil_e_vazio_e_nao_inventa():
    p = tpm.perfil_tatico([], T)
    assert p["jogos"] == 0 and p["metricas"] == {} and p["por_placar"] == {}


def test_segundo_tempo_conforme_o_placar_do_intervalo():
    # Perdendo no intervalo, o time chuta 12 no 2o tempo; vencendo, 4.
    perdendo = [jogo(d, ht=(0, 1), chutes=17, chutes_1t=5) for d in range(1, 6)]
    vencendo = [jogo(d, ht=(1, 0), chutes=9, chutes_1t=5) for d in range(6, 11)]
    p = tpm.perfil_tatico(perdendo + vencendo, T)["por_placar"]
    assert p["perdendo"]["chutes"]["diferenca"] > 0 > p["vencendo"]["chutes"]["diferenca"]
    assert p["perdendo"]["chutes"]["n"] == 5


def test_regime_do_tecnico_flagra_mudanca_observada():
    antes = [jogo(d, posse=60 + (d % 2), mes=8) for d in range(1, 9)]
    depois = [jogo(d, posse=42 + (d % 2), mes=9) for d in range(1, 7)]
    r = tpm.comparar_regimes(antes + depois, T, "2026-09-01")
    assert r["metricas"]["posse"]["mudou"] is True and r["metricas"]["posse"]["z"] < -2
    assert r["metricas"]["escanteios"]["mudou"] is False


def test_regime_com_um_jogo_avisa_em_vez_de_concluir():
    r = tpm.comparar_regimes([jogo(1, mes=8), jogo(2, mes=8), jogo(1, mes=9)], T, "2026-09-01")
    assert r["metricas"] == {} and "insuficientes" in r["aviso"]


def test_perfil_separa_tecnico_pelo_coach_id_e_nao_pela_data():
    # Interino no meio: A, interino B, A de novo nao existe -- B depois de A.
    jogos = [jogo(d, posse=40, mes=9) for d in (1, 8)] + [jogo(d, posse=65, mes=8) for d in (1, 8, 15)]
    esc = [(date(2026, 9, 8), 2, "Novo", "3-5-2"), (date(2026, 9, 1), 2, "Novo", "3-5-2"),
           (date(2026, 8, 15), 1, "Antigo", "4-3-3"), (date(2026, 8, 8), 1, "Antigo", "4-3-3"),
           (date(2026, 8, 1), 1, "Antigo", "4-3-3")]
    p = tpm.perfil_por_tecnico(jogos, T, esc)
    assert p["tecnico_atual"] == 2
    assert p["no_clube_com_o_atual"]["metricas"]["posse"]["media"] == 40
    assert p["no_clube_com_os_anteriores"]["metricas"]["posse"]["media"] == 65


def test_carreira_do_tecnico_fica_separada_do_clube():
    outro_time = 99
    carreira = [(jogo(d, posse=40), T) for d in (1, 2)] + [({**jogo(3, posse=70),
                                                             "home_team_id": outro_time}, outro_time)]
    c = tpm.perfil_da_carreira(carreira)
    assert c["times"] == sorted({T, outro_time}) and c["jogos"] == 3
    assert c["metricas"]["posse"]["media"] == pytest.approx(50)
    assert tpm.perfil_da_carreira([]) is None


def test_referencia_da_competicao_le_os_dois_lados():
    ref = tpm.referencia_da_competicao([jogo(1, posse=60), jogo(2, posse=70)])
    assert ref["posse"] == pytest.approx(50)          # (60+40+70+30)/4


def test_formacoes_e_linha_de_tres():
    esc = [(None, 1, "X", "3-5-2"), (None, 1, "X", "3-4-3"), (None, 1, "X", "4-3-3")]
    f = tpm.formacoes(esc)
    assert f["variacoes"] == 3 and f["linha_de_tres"] == pytest.approx(0.67, abs=0.01)
    assert tpm.formacoes([]) is None and tpm.linha_de_defesa("x") is None


def test_cenarios_do_intervalo_somam_um():
    p = tpm.perfil_tatico([jogo(d) for d in range(1, 6)], T)
    c = tpm.cenarios_do_intervalo(p, p)
    assert c["mandante_vencendo"] + c["empatando"] + c["mandante_perdendo"] == pytest.approx(1, abs=0.01)
    assert tpm.cenarios_do_intervalo({"metricas": {}}, p) is None


def test_perfil_antigo_continua_igual():
    """O rotulo de estilo e o compare_matchup ainda alimentam texto e Score
    Final; nada deles mudou nesta etapa."""
    p = tpm.build_profile([jogo(d) for d in range(1, 6)], T)
    assert p["tactical_profile"]["style"] == "Posse de bola dominante"
    assert set(tpm.compare_matchup(p, p)) == {"goals", "corners", "cards"}
