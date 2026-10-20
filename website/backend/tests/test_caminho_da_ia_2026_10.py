"""O caminho da IA na aba Alavancagem (20/10/2026): a mesma regra do placar
(alavancagem_caminho.subquery_dos_caminhos), em reais, passo a passo."""
import alavancagem_caminho as ac


def _p(i, result, odd=1.5, dia=None):
    return {"id": i, "result": result, "odd_combined": odd, "match_date": dia or f"2026-10-{i:02d}",
            "home_team_1": f"Casa{i}", "away_team_1": f"Fora{i}"}


def test_fecha_na_meta_e_abre_caminho_novo():
    picks = [_p(i, "GREEN", 1.5) for i in range(1, 8)]          # 7 greens, meta 6
    por, fechados, aberto = ac.caminhos_da_ia(picks, 100, meta=6)
    assert por[6]["caminho_encerra"] == "meta" and por[6]["bankroll_after"] == round(100 * 1.5 ** 6, 2)
    assert por[7]["caminho_passo"] == 1 and por[7]["bankroll_before"] == 100   # recomeçou
    assert fechados[0]["end_reason"] == "meta" and fechados[0]["greens"] == 6
    assert fechados[0]["units"] == round(1.5 ** 6 - 1, 4)
    assert aberto["passos"] == 1 and aberto["saldo"] == 150


def test_red_zera_e_custa_so_a_entrada():
    picks = [_p(1, "GREEN", 2), _p(2, "RED", 1.5), _p(3, "GREEN", 1.5)]
    por, fechados, aberto = ac.caminhos_da_ia(picks, 50)
    assert por[2]["bankroll_before"] == 100 and por[2]["bankroll_after"] == 0
    assert por[2]["caminho_encerra"] == "red"
    assert {k: v for k, v in fechados[0].items() if k != "steps"} == {"id": 2, "initial": 50, "final": 0, "realized": -50, "units": -1.0,
                           "greens": 1, "end_reason": "red", "started_at": "2026-10-01",
                           "ended_at": "2026-10-02"}
    assert por[3]["bankroll_before"] == 50 and aberto["steps"][0]["match"] == "Casa3 x Fora3"


def test_push_devolve_e_pick_do_dia_e_o_degrau_em_jogo():
    picks = [_p(1, "GREEN", 2), _p(2, "PUSH", 1.5), _p(3, None, 1.5)]
    por, fechados, aberto = ac.caminhos_da_ia(picks, 10)
    assert por[2]["bankroll_after"] == 20 and por[2]["caminho_passo"] == 2
    assert por[3] == {"bankroll_before": 20, "bankroll_after": None, "potential_return": 30,
                      "caminho_passo": 3, "caminho_encerra": None}
    assert fechados == [] and aberto["passos"] == 2


def test_bate_com_a_conta_do_placar():
    """Unidades dos caminhos fechados = a soma que o SQL do placar entrega
    (caminho_profit so' no passo que encerra)."""
    resultados = ["GREEN", "GREEN", "RED", "GREEN", "HALF-WIN", "GREEN", "GREEN", "GREEN", "GREEN", "PUSH"]
    picks = [_p(i + 1, r, 1.45) for i, r in enumerate(resultados)]
    _, fechados, _ = ac.caminhos_da_ia(picks, 1, meta=6)
    # caminho 1: G G R -> -1u ; caminho 2: G HW G G G G (6 passos) -> meta
    mult2 = 1.45 * (1 + 0.45 / 2) * 1.45 ** 4
    assert [f["end_reason"] for f in reversed(fechados)] == ["red", "meta"]
    assert round(sum(f["units"] for f in fechados), 4) == round(-1 + mult2 - 1, 4)


def test_bilhete_repetido_no_dia_conta_uma_vez():
    """Em PROD o motor gravou o mesmo bilhete 5 vezes em 7 dias; cada copia
    virava um passo. A copia sai do caminho e fica marcada."""
    def b(i, dia, fx=10, result="GREEN"):
        return {**_p(i, result, 1.5, dia), "fixture_id_1": fx, "market_1": "Gols", "line_1": "Over 1.5"}
    picks = [b(1, "2026-10-01"), b(2, "2026-10-02"), b(3, "2026-10-02"), b(4, "2026-10-02", fx=11)]
    por, _, aberto = ac.caminhos_da_ia(picks, 100)
    assert por[3] == {"caminho_duplicado": True}
    assert por[4]["caminho_passo"] == 3            # outro jogo no mesmo dia: passo novo
    assert aberto["passos"] == 3


def test_placar_tambem_descarta_a_copia():
    sql = ac.subquery_dos_caminhos()
    assert "DISTINCT ON (match_date, fixture_id_1, market_1, line_1" in sql and "FROM unicos" in sql


def test_caminho_fechado_leva_os_degraus():
    picks = [_p(1, "GREEN", 2), _p(2, "GREEN", 1.5), _p(3, "RED", 1.5)]
    _, fechados, _ = ac.caminhos_da_ia(picks, 10)
    assert [s["after"] for s in fechados[0]["steps"]] == [20, 30, 0]
