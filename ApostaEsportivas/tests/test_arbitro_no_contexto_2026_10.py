"""O arbitro no contexto da partida, no dossie da IA (18/10/2026)."""
from services.pick_engine import arbitro_no_contexto as ac

LIGA = {"avg_yellow": 4.5, "avg_red": 0.2, "games": 300}          # 4,9 pontos


def _arb(amarelo, vermelho=0.2, jogos=16, faltas=27.0):
    return {"avg_yellow": amarelo, "avg_red": vermelho, "games": jogos, "avg_fouls": faltas}


def _riv(label, excesso=2.0):
    return {"confiavel": True, "confrontos": 5, "media_h2h": 7.1, "baseline": 5.1,
            "excesso": excesso, "label": label}


def test_classico_com_arbitro_rigoroso():
    r = ac.leitura("Ramon Abatti, Brazil", _arb(5.8), LIGA, _riv("rivalidade_alta"))
    assert r["nome"] == "Ramon Abatti"
    assert r["pontos_de_cartao_por_jogo"] == 6.2 and r["pontos_de_cartao_da_liga"] == 4.9
    assert r["perfil"] == "rigoroso"
    assert r["temperatura"] == "confronto_quente_com_arbitro_rigoroso"
    assert r["confronto_direto_cartoes"]["excesso"] == 2.0
    assert r["faltas_por_jogo"] == 27.0


def test_perfis():
    assert ac.perfil_do_arbitro(16, 4.0, 4.9) == "leniente"
    assert ac.perfil_do_arbitro(16, 5.2, 4.9) == "na_media_da_liga"
    assert ac.perfil_do_arbitro(3, 8.0, 4.9) == "amostra_curta"     # 3 jogos e' ruido
    assert ac.perfil_do_arbitro(16, None, 4.9) is None


def test_temperatura_combina_os_dois_lados():
    assert ac.temperatura("leniente", "confronto_frio") == "confronto_frio_com_arbitro_leniente"
    assert ac.temperatura("rigoroso", "confronto_frio") == "confronto_frio_com_arbitro_rigoroso"
    assert ac.temperatura("na_media_da_liga", "rivalidade_alta") == "confronto_quente"
    assert ac.temperatura("rigoroso", "desconhecido") == "arbitro_rigoroso"
    assert ac.temperatura("na_media_da_liga", "normal") == "normal"
    assert ac.temperatura("amostra_curta", "desconhecido") is None


def test_sem_dado_nao_vira_numero():
    """Confronto sem amostra fica de fora; arbitro sem nada, bloco nenhum."""
    r = ac.leitura("Fulano", _arb(5.0), LIGA, {"confiavel": False, "label": "desconhecido"})
    assert "confronto_direto_cartoes" not in r and r["perfil"] == "na_media_da_liga"
    assert ac.leitura("Fulano", None, None, None) is None


def test_dossie_traz_o_bloco_e_a_ia_sabe_ler():
    import inspect
    from services.pick_engine import dossie_da_partida, ai_review
    assert '"arbitro": _arbitro_no_contexto(' in inspect.getsource(dossie_da_partida._montar)
    assert "dossie.arbitro" in inspect.getsource(ai_review)


def test_medicao_acha_o_arbitro_rigoroso_e_nao_inventa_no_neutro():
    """Liga sintetica: todo jogo da' 4 pontos de cartao, menos os do arbitro
    "R. Duro" (6). O residuo dele tem que sair ~+2 e o do resto ~0, so' com o
    que se sabia antes de cada jogo."""
    import random
    from datetime import date, timedelta
    from scripts import medir_arbitro_e_classico as m
    random.seed(7)
    jogos, d = [], date(2025, 1, 1)
    for i in range(1200):
        casa, fora = random.sample(range(1, 21), 2)
        duro = i % 5 == 0
        ref = random.choice(["R. Duro", "Rafael Duro"]) if duro else f"Arbitro {i % 7} Neutro"
        jogos.append((i, d + timedelta(hours=i), 71, casa, fora, ref, 6 if duro else 4))
    linhas = m.medir(jogos)
    t = m.tabela(linhas, "perfil")
    assert t["rigoroso"]["residuo"] > 1.0          # as duas grafias viraram uma pessoa
    assert abs(t["na_media_da_liga"]["residuo"]) < 0.6
