"""O script que remede o efeito do agregado nao pode errar em silencio.

`scripts/medir_efeito_do_agregado.py` existe pra decidir se as constantes de
tie_effect mudam. Um erro nele nao aparece como excecao -- aparece como uma
tabela plausivel e errada, que viraria constante do motor. Por isso os testes
aqui atacam exatamente o que uma medicao pode ter de errado sem parecer:
lookahead, dupla contagem, confusao entre mando e papel, e "a API nao publicou"
virando zero.
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

# `src/scripts/` esta' no .gitignore do repo, sob "Dados privados" -- nenhum
# script de medicao e' versionado, e este teste nao pode ser o unico arquivo
# rastreado que depende de um deles. Num clone limpo o import falharia e
# derrubaria a suite inteira por um modulo que nunca foi commitado.
#
# Com o skip, o teste roda onde o script existe (a maquina de quem mede) e se
# ausenta em silencio onde nao existe. A alternativa -- versionar o script --
# e' decisao de quem escreveu aquela linha do .gitignore, nao deste arquivo.
med = pytest.importorskip(
    "scripts.medir_efeito_do_agregado",
    reason="src/scripts/ nao e' versionado (.gitignore); o script de medicao "
           "so' existe na maquina onde a medicao foi feita",
)


def _jogo(dia, home, away, league_id=73, season=2026, **stats):
    """Jogo com folha completa por padrao -- cada teste sobrescreve o que
    precisa. league_id 73 e' Copa do Brasil (CLUB_CUP), nao pontos corridos."""
    base = {
        "match_date": date(2026, 8, dia), "league_id": league_id, "season": season,
        "home_team_id": home, "away_team_id": away,
        "home_goals": 1, "away_goals": 1,
        "home_corners": 5, "away_corners": 5,
        "home_total_shots": 10, "away_total_shots": 10,
        "home_shots_on": 4, "away_shots_on": 4,
        "home_fouls": 12, "away_fouls": 12,
        "home_goalkeeper_saves": 3, "away_goalkeeper_saves": 3,
        "home_yellow_cards": 2, "away_yellow_cards": 2,
        "home_red_cards": 0, "away_red_cards": 0,
    }
    base.update(stats)
    return base


# ─────────────────── 1. quem e' confronto de ida-e-volta ────────────────────


def test_mando_invertido_e_o_que_prova_o_confronto():
    ida = _jogo(1, home=10, away=20)
    volta = _jogo(8, home=20, away=10)
    assert len(med.achar_confrontos_de_volta([ida, volta], 45)) == 1


def test_dois_encontros_no_mesmo_mando_nao_sao_ida_e_volta():
    """Mesmos times, mesma competicao, mas o mando NAO inverteu: sao dois
    encontros quaisquer, e o agregado nao existe."""
    a = _jogo(1, home=10, away=20)
    b = _jogo(8, home=10, away=20)
    assert med.achar_confrontos_de_volta([a, b], 45) == []


def test_pontos_corridos_fica_de_fora():
    """No returno de liga o mando tambem inverte, e ali isso nao significa
    agregado nenhum. E' o mesmo recorte que competitive_pressure faz."""
    ida = _jogo(1, home=10, away=20, league_id=71)      # Serie A = LEAGUE
    volta = _jogo(8, home=20, away=10, league_id=71)
    assert med.achar_confrontos_de_volta([ida, volta], 45) == []


def test_janela_de_dias_corta_encontro_distante():
    ida = _jogo(1, home=10, away=20)
    volta = _jogo(28, home=20, away=10)
    assert len(med.achar_confrontos_de_volta([ida, volta], 45)) == 1
    assert med.achar_confrontos_de_volta([ida, volta], 10) == []


def test_competicoes_diferentes_nao_formam_confronto():
    ida = _jogo(1, home=10, away=20, league_id=73)
    volta = _jogo(8, home=20, away=10, league_id=13)
    assert med.achar_confrontos_de_volta([ida, volta], 45) == []


def test_nenhum_jogo_entra_em_dois_confrontos():
    """Tres encontros seguidos (grupo + mata-mata) nao podem gerar dois pares
    que compartilham o jogo do meio -- isso contaria a mesma partida duas vezes
    e estreitaria o erro-padrao de mentira. Medido contra PROD tambem: 134
    confrontos usam 268 jogos distintos, cada um uma vez so'."""
    a = _jogo(1, home=10, away=20)
    b = _jogo(8, home=20, away=10)
    c = _jogo(15, home=10, away=20)
    confrontos = med.achar_confrontos_de_volta([a, b, c], 45)
    usados = []
    for ida, volta in confrontos:
        usados.append((ida["match_date"], ida["home_team_id"]))
        usados.append((volta["match_date"], volta["home_team_id"]))
    assert len(usados) == len(set(usados)), "jogo reaproveitado entre confrontos"


# ─────────────────────── 2. papel de cada lado ──────────────────────────────


def test_quem_perdeu_a_ida_esta_atras():
    ida = _jogo(1, home=10, away=20, home_goals=2, away_goals=0)
    assert med.papeis_na_volta(ida) == {10: "na_frente", 20: "atras"}


def test_ida_empatada_deixa_os_dois_no_mesmo_papel():
    ida = _jogo(1, home=10, away=20, home_goals=1, away_goals=1)
    assert med.papeis_na_volta(ida) == {10: "empatado", 20: "empatado"}


def test_ida_sem_placar_nao_produz_papel():
    ida = _jogo(1, home=10, away=20, home_goals=None, away_goals=None)
    assert med.papeis_na_volta(ida) is None


# ──────────────── 3. media propria: mando, lookahead e folha ────────────────


def _historico(team_id, lado, valores, dia_inicial=1):
    jogos = []
    for i, v in enumerate(valores):
        if lado == "home":
            jogos.append(_jogo(dia_inicial + i, home=team_id, away=99, home_corners=v))
        else:
            jogos.append(_jogo(dia_inicial + i, home=99, away=team_id, away_corners=v))
    return jogos


def test_media_propria_so_conta_o_mesmo_mando():
    """Casa contra casa. Sem isso, "esta atras" se confunde com "esta jogando
    em casa", que e' o efeito mais forte do futebol."""
    em_casa = _historico(10, "home", [8, 8, 8, 8])
    fora = _historico(10, "away", [2, 2, 2, 2])
    media, n = med.media_propria(em_casa + fora, 10, "corners", "home", date(2026, 8, 20))
    assert media == 8.0 and n == 4


def test_media_propria_ignora_jogo_posterior():
    """Lookahead e' o erro que faz uma medicao parecer boa e ser circular."""
    antes = _historico(10, "home", [4, 4, 4, 4], dia_inicial=1)
    depois = _historico(10, "home", [99, 99, 99, 99], dia_inicial=20)
    media, n = med.media_propria(antes + depois, 10, "corners", "home", date(2026, 8, 10))
    assert media == 4.0 and n == 4


def test_media_propria_exige_amostra_minima():
    poucos = _historico(10, "home", [5, 5, 5])
    media, n = med.media_propria(poucos, 10, "corners", "home", date(2026, 8, 20))
    assert media is None and n == 3


def test_folha_incompleta_nao_vira_zero():
    """`_valor_do_lado` reusa o criterio do motor: um lado sem contador nao e'
    "aconteceram zero escanteios". Se virasse zero, o deslocamento sairia
    negativo de mentira e o Under ficaria inflado -- o mesmo vies que a
    correcao do `or 0` fechou no stats_model."""
    meia_folha = _jogo(1, home=10, away=20, home_corners=7, away_corners=None)
    assert med._valor_do_lado(meia_folha, "corners", "home") is None
    assert med._valor_do_lado(meia_folha, "corners", "away") is None


def test_cartao_conta_vermelho_como_dois():
    jogo = _jogo(1, home=10, away=20, home_yellow_cards=3, home_red_cards=1)
    assert med._valor_do_lado(jogo, "cards", "home") == 5.0


def test_cartao_sem_coluna_de_vermelho_nao_vira_zero():
    """Vermelho tem 68,7% de cobertura em PROD -- e' o buraco real da folha.
    Tratar ausencia como zero jogaria ~4% da amostra pro lado errado."""
    jogo = _jogo(1, home=10, away=20, home_red_cards=None, away_red_cards=None)
    assert med._valor_do_lado(jogo, "cards", "home") is None


# ─────────────────────── 4. a estatistica em si ─────────────────────────────


def test_resumo_devolve_media_erro_padrao_e_n():
    media, ep, n = med.resumo([2.0, 4.0, 6.0])
    assert n == 3
    assert media == 4.0
    assert ep == pytest.approx(2.0 / (3 ** 0.5))


def test_resumo_de_amostra_unica_nao_inventa_erro_padrao():
    media, ep, n = med.resumo([5.0])
    assert (media, ep, n) == (5.0, None, 1)


def test_resumo_vazio_nao_quebra():
    assert med.resumo([]) == (None, None, 0)


def test_sem_dispersao_o_erro_padrao_e_zero_e_a_linha_nao_divide_por_ele():
    """Valores identicos dao ep=0. A formatacao nao pode estourar
    ZeroDivisionError ao calcular sigma."""
    linha = med._linha("teste", [3.0, 3.0, 3.0])
    assert "n/a" in linha


# ───────────────── 5. a medicao ponta a ponta, com efeito plantado ──────────


def test_efeito_plantado_aparece_com_o_sinal_certo():
    """Quem esta' atras bate 4 escanteios acima da propria media de mando; quem
    esta' na frente bate 4 abaixo. A medicao tem que devolver exatamente isso,
    e no lado certo."""
    historico = (_historico(10, "away", [5, 5, 5, 5], dia_inicial=1)
                 + _historico(20, "home", [5, 5, 5, 5], dia_inicial=1))
    # Ida: 20 ganha em casa -> na volta 20 esta' na frente e 10 esta' atras.
    ida = _jogo(10, home=20, away=10, home_goals=2, away_goals=0)
    # Volta: manda o 10 (atras). Mas as medias que temos sao 10-fora e 20-casa,
    # entao a volta precisa respeitar esses mandos pra a comparacao existir.
    volta = _jogo(17, home=20, away=10, home_goals=0, away_goals=0,
                  home_corners=1, away_corners=9)
    jogos = historico + [ida, volta]

    por_lado, por_total = med.medir(jogos, [(ida, volta)])
    assert por_lado["corners"]["atras"] == [4.0]        # time 10, fora: 9 - 5
    assert por_lado["corners"]["na_frente"] == [-4.0]   # time 20, casa: 1 - 5
    assert por_total["corners"] == [0.0]                # os dois se cancelam


def test_lado_sem_media_propria_nao_entra_e_nao_derruba_o_outro():
    """Descarte e' por LADO. O time sem historico suficiente sai; o outro
    continua medido -- foi assim que a rodada contra PROD manteve 37 lados
    'atras' de 99 papeis brutos."""
    historico = _historico(10, "away", [5, 5, 5, 5], dia_inicial=1)  # so' o 10
    ida = _jogo(10, home=20, away=10, home_goals=2, away_goals=0)
    volta = _jogo(17, home=20, away=10, home_corners=1, away_corners=9)
    por_lado, por_total = med.medir(historico + [ida, volta], [(ida, volta)])
    assert por_lado["corners"]["atras"] == [4.0]
    assert por_lado["corners"]["na_frente"] == []
    # Total exige os DOIS lados: com um so', a pergunta "eles se cancelam?"
    # nao tem resposta.
    assert por_total["corners"] == []
