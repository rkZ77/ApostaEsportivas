# -*- coding: utf-8 -*-
"""Contexto de competicao: formato, agregado e efeito medido por lado.

O QUE ESTES TESTES TRAVAM
-------------------------
O motor ja' sabia reconstruir o agregado de um mata-mata (match_context_model,
2026-08-13) e usava esse conhecimento pra UMA coisa so': penalizar Under de
mercado de jogo inteiro. Um "Escanteios Casa Over" num jogo em que o mandante
precisava reverter um 0x1 recebia ajuste contextual de exatamente 0.0.

A camada de 2026-08-19 fecha isso, e cada teste aqui trava uma das quatro
decisoes que ela tomou:

  1. formato sai de EVIDENCIA, nunca do nome da competicao;
  2. o efeito e' REDISTRIBUICAO -- age no mercado de um time, quase nao age no
     mercado de jogo inteiro;
  3. o efeito e' MEDIDO, inclusive onde a medicao contraria a intuicao
     (faltas caem pra quem ataca);
  4. o contexto NUNCA cria elegibilidade -- ele melhora o EV publicado de um
     pick que ja' passava, e pode reprovar um que passava.
"""
from datetime import datetime

import pytest

from services.pick_engine import (competition_profile, context_gate, ranking,
                                  tie_effect)
from services.pick_engine import match_context_model as mcm
from services.pick_engine.config import DEFAULT_CONFIG

ATLETICO, ADVERSARIO = 1062, 152
SUL_AMERICANA, TEMPORADA = 11, 2026
DIA_DA_VOLTA = datetime(2026, 8, 20)


def _ida(gols_atletico: int, gols_adversario: int) -> list:
    """A ida na casa do adversario -- o mando inverte entre as duas pernas."""
    return [{"league_id": SUL_AMERICANA, "season": TEMPORADA,
             "match_date": datetime(2026, 8, 13),
             "home_team_id": ADVERSARIO, "away_team_id": ATLETICO,
             "home_goals": gols_adversario, "away_goals": gols_atletico}]


def _contexto(gols_atletico: int, gols_adversario: int, round_str="Round of 16") -> dict:
    return context_gate.build_context(
        round_str=round_str, home_team_id=ATLETICO, away_team_id=ADVERSARIO,
        h2h_matches=_ida(gols_atletico, gols_adversario),
        league_id=SUL_AMERICANA, season=TEMPORADA,
        baseline_cartoes=None, match_date=DIA_DA_VOLTA)


def _candidato(**kwargs) -> dict:
    """Escanteios Casa Over 4.5 @1.67 -- o pick real que motivou a revisao."""
    base = {
        "market_type": "corners", "scope": "home", "_direction": "over",
        "_line_val": 4.5, "odd": 1.67, "taxa_real": 0.632,
        "prob_baseline_value": 0.599, "confidence": 0.84, "Q": 0.85,
        "amostra": 12, "ev": 0.0554, "edge": 0.033,
        "convergence": {"expected_value": 5.45},
    }
    return {**base, **kwargs}


# ─────────────────── 1. formato sai de evidencia ──────────────────────────
def test_formato_de_copa_sai_do_confronto_nao_do_nome_da_competicao():
    """"Round of 16" seco, sem "1st leg"/"2nd leg" -- e' o que a API-Football
    manda nas oitavas de Libertadores e Sul-Americana, medido em producao. O
    formato tem que sair da inversao de mando do confronto anterior."""
    tie = _contexto(0, 1)["tie"]
    assert tie["formato"] == mcm.COPA_IDA_E_VOLTA
    assert tie["formato_origem"] == "confronto"
    assert tie["is_jogo_de_volta"] is True


def test_jogo_unico_nao_vira_ida_e_volta_por_ser_copa():
    """Sem confronto anterior e sem rotulo de perna, o regulamento responde --
    e a final da CONMEBOL e' em jogo unico mesmo num torneio de duas pernas."""
    tie = mcm.tie_context("Final", ATLETICO, ADVERSARIO, None, league_id=SUL_AMERICANA)
    assert tie["formato"] == mcm.COPA_JOGO_UNICO
    assert tie["formato_origem"] == "regulamento"
    assert tie["agregado_home"] is None


def test_competicao_sem_regulamento_cadastrado_nao_advinha():
    """Liga desconhecida em fase de mata-mata: DESCONHECIDO, nao "jogo unico".
    Jogo unico e' uma afirmacao, e o motor nao a tem."""
    tie = mcm.tie_context("Quarter-finals", ATLETICO, ADVERSARIO, None, league_id=999999)
    assert tie["formato"] == mcm.FORMATO_DESCONHECIDO
    assert tie["formato_origem"] is None


def test_regra_de_gol_fora_nunca_e_assumida():
    """Tri-estado preservado: competicao cadastrada diz False (abolida),
    competicao nao cadastrada diz None -- e None nunca vira False no caminho."""
    assert _contexto(0, 1)["tie"]["regras"]["gol_fora"] is False
    desconhecida = mcm.tie_context("Semi-finals", ATLETICO, ADVERSARIO, None, league_id=999999)
    assert desconhecida["regras"]["gol_fora"] is None


def test_round_phase_do_ledger_para_de_chamar_ida_e_volta_de_jogo_unico():
    """As 34 pernas de mata-mata gravadas ate 2026-08-19 estavam TODAS como
    KNOCKOUT_SINGLE, num universo em que oitavas de CONMEBOL sao de duas
    pernas. round_phase e' dimensao de segmentacao -- o rotulo errado somava
    jogo unico e volta no mesmo balde de calibracao."""
    assert competition_profile.classify_round_phase("Round of 16") == "KNOCKOUT_SINGLE"
    assert competition_profile.classify_round_phase(
        "Round of 16", formato=mcm.COPA_IDA_E_VOLTA) == "KNOCKOUT_TWO_LEGS"


# ─────────────────── 2. os seis cenarios do pedido ────────────────────────
@pytest.mark.parametrize("rotulo,gols_atletico,gols_adv,quem_precisa,faltam", [
    ("A) venceu 1x0",  1, 0, "away",  1),
    ("B) empatou 0x0", 0, 0, "ambos", None),
    ("C) perdeu 0x1",  0, 1, "home",  1),
    ("D) perdeu 0x2",  0, 2, "home",  2),
    ("E) venceu 2x0",  2, 0, "away",  2),
    ("F) perdeu 1x3",  1, 3, "home",  2),
])
def test_cada_placar_de_ida_produz_um_contexto_diferente(
        rotulo, gols_atletico, gols_adv, quem_precisa, faltam):
    tie = _contexto(gols_atletico, gols_adv)["tie"]
    assert tie["precisa_de_resultado"] == quem_precisa, rotulo
    assert tie["gols_para_reverter"] == faltam, rotulo


def test_agregado_empatado_nao_desloca_volume():
    """Medido: com o agregado empatado os dois times se anulam e o volume sai
    igual ao de uma partida comum (-0.64 escanteios, ep 0.99). E' o cenario de
    maior TENSAO -- stakes continua alto -- e isso nao e a mesma coisa."""
    ctx = _contexto(0, 0)
    tie = ctx["tie"]
    assert tie["pressao_por_lado"]["home"] == 0.0
    assert tie["pressao_por_lado"]["away"] == 0.0
    assert tie_effect.efeito(_candidato(), ctx)["delta_prob"] == 0.0
    # ... mas a partida continua sendo tratada como decisao pelo que vale.
    assert ctx["stakes"] > context_gate.STAKES_DECISIVO


def test_vantagem_maior_pressiona_mais():
    um_gol = _contexto(0, 1)["tie"]["pressao_por_lado"]["home"]
    dois_gols = _contexto(0, 2)["tie"]["pressao_por_lado"]["home"]
    assert dois_gols > um_gol > 0


# ─────────────────── 3. redistribuicao, nao criacao ───────────────────────
def test_efeito_e_oposto_nos_dois_lados_do_mesmo_jogo():
    """O mandante precisa reverter: o escanteio DELE sobe e o do visitante
    cai. E' a assimetria que o motor nao enxergava -- ele tratava
    "Escanteios Casa" e "Escanteios Visitante" como o mesmo mercado."""
    ctx = _contexto(0, 1)
    casa = tie_effect.efeito(_candidato(scope="home"), ctx)
    fora = tie_effect.efeito(_candidato(scope="away"), ctx)
    assert casa["delta_prob"] > 0 and casa["papel"] == "atras"
    assert fora["delta_prob"] < 0 and fora["papel"] == "na_frente"


def test_mercado_de_jogo_inteiro_quase_nao_se_move():
    """No total os dois efeitos se cancelam -- medido em +0.95 escanteios com
    ep 1.04, indistinguivel de zero. Aplicar o efeito de lado ali seria
    inventar volume que a medicao diz que nao existe."""
    ctx = _contexto(0, 1)
    total = tie_effect.efeito(_candidato(scope="total"), ctx)
    lado = tie_effect.efeito(_candidato(scope="home"), ctx)
    assert abs(total["delta_prob"]) < abs(lado["delta_prob"]) / 3


def test_gate_de_contexto_entrega_o_mercado_de_um_time_pra_camada_medida():
    """Os dois lendo o mesmo agregado cobrariam duas vezes pelo mesmo fato."""
    ctx = _contexto(0, 1)
    under_de_lado = {"market_type": "corners", "scope": "home", "_direction": "under"}
    under_do_jogo = {"market_type": "corners", "scope": "total", "_direction": "under"}
    assert context_gate.evaluate(
        under_de_lado, ctx, delegar_lados=True)["pressao_total"] == 0.0
    assert context_gate.evaluate(
        under_do_jogo, ctx, delegar_lados=True)["pressao_total"] > 0.0


def test_com_a_camada_desligada_o_gate_retoma_o_mercado_de_lado():
    """Nenhum candidato pode ficar sem camada nenhuma quando use_tie_effect
    esta desligado."""
    ctx = _contexto(0, 1)
    under_de_lado = {"market_type": "corners", "scope": "home", "_direction": "under"}
    assert context_gate.evaluate(
        under_de_lado, ctx, delegar_lados=False)["pressao_total"] > 0.0


# ─────────────────── 4. medido, inclusive contra a intuicao ───────────────
def test_faltas_caem_para_quem_precisa_atacar():
    """O resultado mais forte da medicao (-2.48, 3.9 erros-padrao) e o que
    mais contraria a narrativa: quem persegue o resultado tem a bola, e quem
    tem a bola nao comete falta. O gate antigo dizia o contrario."""
    ctx = _contexto(0, 1)
    over_faltas = _candidato(market_type="fouls", scope="home", _direction="over",
                             _line_val=11.5, convergence={"expected_value": 12.0})
    assert tie_effect.efeito(over_faltas, ctx)["delta_prob"] < 0


def test_defesas_de_goleiro_ficam_de_fora_por_medicao():
    """Saves entrou na medicao e ficou fora por ela: -0.14 com ep 0.99 e'
    zero. Ausencia por decisao medida, nao por esquecimento."""
    ctx = _contexto(0, 1)
    saves = _candidato(market_type="saves", scope="home", _direction="over",
                       _line_val=3.5, convergence={"expected_value": 4.0})
    assert tie_effect.efeito(saves, ctx)["delta_prob"] == 0.0


def test_familia_sem_lambda_nao_recebe_ajuste():
    """Sem expected_value nao ha como converter deslocamento de contagem em
    probabilidade, e chutar essa conversao seria escolher um numero."""
    ctx = _contexto(0, 1)
    sem_lambda = _candidato(convergence=None)
    efeito = tie_effect.efeito(sem_lambda, ctx)
    assert efeito["delta_prob"] == 0.0
    assert "lambda" in efeito["motivo"]


def test_ajuste_tem_teto_por_familia():
    """Nem um agregado de 3 gols numa final pode empurrar mais que o teto."""
    ctx = _contexto(0, 3, round_str="Final - 2nd Leg")
    for familia, linha, lam in (("corners", 4.5, 5.45), ("goals", 1.5, 1.4)):
        cand = _candidato(market_type=familia, _line_val=linha,
                          convergence={"expected_value": lam})
        delta = tie_effect.efeito(cand, ctx)["delta_prob"]
        assert abs(delta) <= tie_effect.TETO_DE_DELTA[familia] + 1e-9


def test_partida_de_pontos_corridos_nao_recebe_nada():
    """Compatibilidade: jogo de campeonato segue exatamente como antes."""
    ctx = context_gate.build_context(
        round_str="Regular Season - 12", home_team_id=ATLETICO,
        away_team_id=ADVERSARIO, h2h_matches=[], league_id=71, season=TEMPORADA,
        baseline_cartoes=None, match_date=DIA_DA_VOLTA)
    assert ctx["tie"]["formato"] == mcm.PONTOS_CORRIDOS
    assert tie_effect.efeito(_candidato(), ctx)["delta_prob"] == 0.0


# ─────────────────── 5. o contexto nao cria pick ──────────────────────────
def test_contexto_positivo_nao_aprova_pick_que_nao_passava_sozinho():
    """A trava central do pedido: "nao quero que o contexto de mata-mata
    sozinho transforme uma aposta ruim em uma aposta boa"."""
    reprovado = _candidato(
        taxa_real=0.68, ev=0.0350, taxa_real_sem_contexto=0.64,
        ev_sem_contexto=-0.001, tie_effect={"delta_prob": 0.04},
    )
    aprovados = ranking.rank_all_candidates([reprovado], config=DEFAULT_CONFIG)
    assert aprovados == []


def test_contexto_negativo_pode_reprovar_pick_que_passava():
    """A assimetria e' de proposito: pros dois lados vale o valor mais
    conservador. O Under do time que vai administrar perde por um motivo que
    a amostra historica nao enxerga."""
    com_penalidade = _candidato(
        taxa_real=0.595, ev=-0.006, taxa_real_sem_contexto=0.635,
        ev_sem_contexto=0.0605, tie_effect={"delta_prob": -0.04},
    )
    aprovados = ranking.rank_all_candidates([com_penalidade], config=DEFAULT_CONFIG)
    assert aprovados == []


def test_regime_de_mata_mata_cobra_confianca_e_nao_so_probabilidade():
    """Volta com agregado aberto nao pertence a populacao dos 15 jogos de
    campeonato que geraram a taxa. Isso e' incerteza, entao cobra confidence
    -- cobrar dos dois lados contaria o mesmo fato duas vezes."""
    efeito = tie_effect.efeito(_candidato(), _contexto(0, 1))
    assert efeito["delta_confianca"] < 0
    assert abs(efeito["delta_confianca"]) <= tie_effect.PENALIDADE_DE_REGIME_MAX


def test_explicacao_publica_traz_o_numero_junto_da_afirmacao():
    """Afirmacao de contexto sem o deslocamento que ela produziu e' a
    narrativa que esta camada existe pra nao criar."""
    linhas = tie_effect.descrever(tie_effect.efeito(_candidato(), _contexto(0, 1)))
    assert linhas
    texto = " ".join(linhas)
    assert "ponto(s) percentual(is)" in texto and "medido em" in texto
