"""Temporada inteira do arbitro (18/10/2026): ligas extras do pais, listagem
com o nome dele, e folha de cartao/falta/VAR pelo /fixtures?ids=."""
from datetime import datetime

from collectors import arbitro_temporada_service as at
from collectors import calendario_service


def _liga(lid, nome, eventos=True, stats=True, atual=True):
    return {"league": {"id": lid, "name": nome}, "country": {"name": "Brazil"},
            "seasons": [{"year": 2026, "current": atual,
                         "coverage": {"fixtures": {"events": eventos, "statistics_fixtures": stats}}}]}


def test_liga_extra_fica_so_a_que_diz_algo_do_arbitro():
    ativas = {71}
    assert at.liga_serve(_liga(72, "Serie B"), ativas) == (72, 2026, "Serie B", "Brazil")
    assert at.liga_serve(_liga(71, "Serie A"), ativas) is None              # ja' ativa
    assert at.liga_serve(_liga(74, "Brasileiro Women"), ativas) is None
    assert at.liga_serve(_liga(75, "Copa Sao Paulo de Futebol Junior"), ativas) is None
    assert at.liga_serve(_liga(76, "Paulista U20"), ativas) is None
    assert at.liga_serve(_liga(77, "Serie D", eventos=False, stats=False), ativas) is None  # sem cobertura
    assert at.liga_serve(_liga(78, "Copa do Brasil", stats=False), ativas) == (78, 2026, "Copa do Brasil", "Brazil")
    assert at.liga_serve(_liga(79, "Carioca", atual=False), ativas) is None


def _fx(fid, status="FT", referee="Raphael Claus, Brazil", gh=2, ga=1):
    return {"fixture": {"id": fid, "referee": referee, "date": "2026-10-01T22:00:00+00:00",
                        "status": {"short": status}},
            "league": {"id": 72, "season": 2026, "name": "Serie B"},
            "teams": {"home": {"id": 1, "name": "Goias"}, "away": {"id": 2, "name": "Sport"}},
            "goals": {"home": gh, "away": ga}}


def test_listagem_guarda_so_jogo_encerrado_com_arbitro():
    linhas = at.linhas_da_listagem([_fx(1), _fx(2, status="NS"), _fx(3, referee=None), _fx(1)], "Serie B")
    assert len(linhas) == 1                                   # repetido entre paginas vira um
    (l,) = linhas
    assert l[0] == 1 and l[3] == "Serie B" and l[6] == "Raphael Claus, Brazil"
    assert l[4] == datetime(2026, 10, 1, 22, 0)              # UTC sem fuso, como match_statistics
    assert (l[11], l[12]) == (2, 1)


def _folha(tid, amarelo, vermelho, faltas):
    return {"team": {"id": tid}, "statistics": [
        {"type": "Yellow Cards", "value": amarelo}, {"type": "Red Cards", "value": vermelho},
        {"type": "Fouls", "value": faltas}, {"type": "Corner Kicks", "value": 4}]}


def _ev(tid, tipo, det, minuto=10):
    return {"team": {"id": tid}, "type": tipo, "detail": det, "time": {"elapsed": minuto}}


def test_folha_vem_da_estatistica_e_o_var_dos_eventos():
    item = {**_fx(1), "statistics": [_folha(2, 3, None, 14), _folha(1, 2, 1, 12)],
            "events": [_ev(1, "Var", "Goal cancelled", 67), _ev(2, "Goal", "Penalty", 30),
                       _ev(1, "Card", "Yellow Card")]}
    d = at.folha_do_item(item)
    assert (d["home_yellow_cards"], d["away_yellow_cards"]) == (2, 3)
    assert (d["home_red_cards"], d["away_red_cards"]) == (1, 0)   # null na folha publicada e' zero
    assert (d["home_fouls"], d["away_fouls"]) == (12, 14)
    assert d["var_lances"] == [{"minuto": 67, "team_id": 1, "detalhe": "Goal cancelled"}]
    assert d["penaltis"] == 1 and d["tem_eventos"]


def test_sem_folha_o_cartao_sai_dos_eventos_e_a_falta_fica_nula():
    item = {**_fx(1), "statistics": [],
            "events": [_ev(1, "Card", "Yellow Card"), _ev(1, "Card", "Yellow Card"),
                       _ev(2, "Card", "Yellow Card"), _ev(2, "Card", "Second Yellow card"),
                       _ev(1, "Card", "Red Card")]}
    d = at.folha_do_item(item)
    assert (d["home_yellow_cards"], d["away_yellow_cards"]) == (2, 1)
    assert (d["home_red_cards"], d["away_red_cards"]) == (1, 1)
    assert d["home_fouls"] is None and d["away_fouls"] is None    # nunca 0 inventado


def test_sem_folha_e_sem_evento_nada_vira_numero():
    d = at.folha_do_item({**_fx(1), "statistics": [], "events": []})
    assert all(d[k] is None for k in ("home_yellow_cards", "away_red_cards", "home_fouls"))
    assert d["var_lances"] is None and d["penaltis"] is None and d["tem_eventos"] is False


def test_calendario_grava_o_arbitro_de_graca():
    (linha,) = calendario_service.linhas_da_temporada([_fx(10)], 71, 2026)
    assert linha[10] == "Raphael Claus, Brazil"


def test_comando_roda_no_tudo_logo_depois_dos_dados():
    import main
    etapas = [c.nome for c in main.COMANDOS if c.etapa]
    assert etapas[etapas.index("dados") + 1] == "arbitros"
