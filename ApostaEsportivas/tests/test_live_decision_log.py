"""Rastro do motor AO VIVO em `engine_decisions` (decision_log).

POR QUE ESTE TESTE EXISTE
-------------------------
Em 23/08/2026 o laco do motor ao vivo rodou 91 vezes em PRODUCAO e nao deixou
rastro nenhum: `picks_live` ficou vazia (dry run), e o unico log era o stdout
da ULTIMA rodada, guardado em memoria no processo do site
(`routers/live_picks.py::_run_status`) e perdido no primeiro deploy. Nao havia
como distinguir "o motor nao achou nada" de "o motor achou e nao podia gravar".

Os seis pipelines de pre-jogo ja' gravavam em `engine_decisions` desde 07/08.
O ao vivo era o unico que nao gravava · estes testes travam isso.

O que cada um cobre e' um ponto ONDE A PARTIDA MORRE, porque atribuir a morte
a' camada errada e' o erro mais comum na auditoria deste motor.
"""
from dataclasses import replace

import pytest

from engine_pipelines import decision_log, live_pipeline
from engine_pipelines.decision_log import (
    LIVE_NENHUM_APROVADO, LIVE_REPROVOU_TRIAGEM, LIVE_SEM_ESTATISTICA,
    PIPELINE_LIVE, STATUS_AVALIADO, STATUS_DESCARTADO,
)
from services.pick_engine_live.config import LiveEngineConfig


CONFIG = replace(LiveEngineConfig(habilitado=True, dry_run=True),
                 familias=("corners", "goals"))

BRUTO = {
    "fixture": {"id": 999001, "status": {"short": "2H"}},
    "teams": {"home": {"id": 1, "name": "Alfa"}, "away": {"id": 2, "name": "Beta"}},
    "league": {"id": 71},
}

ESTADO = {"fixture_id": 999001, "minuto": 62, "status": "2H", "league_id": 71,
          "home_goals": 1, "away_goals": 0, "referee": ""}


class _Feed:
    """Feed que nao chama a API. `usadas` existe porque o log registra o custo
    da rodada, e um numero fixo torna a asercao possivel."""
    usadas = 4

    def estatisticas(self, fid):
        return []

    def eventos(self, fid):
        return []

    def tem_orcamento(self, n=1):
        return True

    def odds_ao_vivo(self, fid):
        return []

    def ultimo_erro(self, endpoint):
        """Nenhuma falha de transporte. O pipeline consulta isto pra separar
        "a casa nao cotou" de "a chamada quebrou" -- aqui e' sempre o
        primeiro, que e' o cenario que estes testes exercitam."""
        return None


@pytest.fixture
def gravadas(monkeypatch):
    """Captura o que iria pro Postgres, sem abrir conexao."""
    linhas = []
    monkeypatch.setattr(decision_log, "_gravar", lambda *a: linhas.append(a))
    monkeypatch.setattr(decision_log, "_gravar_arquivo", lambda entry: True)
    return linhas


@pytest.fixture
def motor(monkeypatch):
    """Neutraliza tudo que toca banco ou API. Cada teste so' mexe no ponto
    que quer exercitar."""
    mp = monkeypatch
    mp.setattr(live_pipeline, "ler_estatisticas", lambda *a: ({}, {}))
    mp.setattr(live_pipeline.live_state, "ler_eventos", lambda *a: [])
    mp.setattr(live_pipeline.live_state, "resumo_de_eventos",
               lambda *a: {"disponivel": False})
    mp.setattr(live_pipeline.live_state, "montar_estado", lambda *a: dict(ESTADO))
    mp.setattr(live_pipeline.live_state, "freshness",
               lambda *a: {"nivel": "OK", "motivos": []})
    mp.setattr(live_pipeline, "observacoes_anteriores", lambda *a, **k: [])
    mp.setattr(live_pipeline, "baselines_por_liga", lambda *a: {})
    mp.setattr(live_pipeline, "baseline_do_confronto", lambda *a: {})
    mp.setattr(live_pipeline, "baseline_do_arbitro", lambda *a: {})
    mp.setattr(live_pipeline, "baseline_do_h2h", lambda *a: {})
    mp.setattr(live_pipeline, "contexto_pre_jogo", lambda *a: None)
    mp.setattr(live_pipeline, "picks_da_partida", lambda *a: [])
    mp.setattr(live_pipeline, "_observar", lambda *a: None)
    mp.setattr(live_pipeline.orchestrator, "analisar",
               lambda *a, **k: {"estado": dict(ESTADO), "familias": {},
                                "pressao": {}, "ritmo": {}, "necessidade": {}})
    return mp


def _rodar():
    relatorio = {"picks_criados": [], "erros": []}
    resumo = live_pipeline._processar_partida(
        1, BRUTO, cur=None, conn=None, feed=_Feed(), config=CONFIG,
        relatorio=relatorio)
    return resumo, relatorio


def test_partida_sem_estatistica_deixa_linha(motor, gravadas):
    """A familia inteira sem numero publicado e' cobertura do provedor, nao
    decisao do modelo · sem esta linha o jogo some do log e vira "o motor
    ignorou o jogo"."""
    motor.setattr(live_pipeline.orchestrator, "observado_da_familia", lambda *a: None)

    resumo, _ = _rodar()

    assert resumo["decisao"] == "SKIP"
    pipeline, fixture, status, reason, _, _, contexto = gravadas[0]
    assert (pipeline, status, reason) == (PIPELINE_LIVE, STATUS_DESCARTADO,
                                          LIVE_SEM_ESTATISTICA)
    assert fixture == {"fixture_id": 999001, "home_team": "Alfa", "away_team": "Beta"}
    # `folha_vazia` separa "provedor nao cobre esta partida" de "faltou UMA
    # familia" · a variavel so' existia dentro do ramo que imprime.
    assert contexto["folha_vazia"] is True
    assert contexto["minuto"] == 62


def test_triagem_reprovada_registra_sem_gastar_odd(motor, gravadas):
    """A triagem e' o freio de API: a partida morre aqui SEM a odd consultada.
    O log precisa dizer isso, senao a rodada parece ter avaliado preco."""
    motor.setattr(live_pipeline.orchestrator, "observado_da_familia", lambda *a: 5)
    motor.setattr(live_pipeline.orchestrator, "triagem",
                  lambda *a: {"vale": False, "motivo": "projecao colada",
                              "familias": [], "detalhes": [{"familia": "corners"}]})

    resumo, _ = _rodar()

    assert resumo["odd_consultada"] is False
    pipeline, _, status, reason, _, _, contexto = gravadas[0]
    assert (pipeline, status, reason) == (PIPELINE_LIVE, STATUS_DESCARTADO,
                                          LIVE_REPROVOU_TRIAGEM)
    assert contexto["motivo_triagem"] == "projecao colada"
    assert contexto["triagem"] == [{"familia": "corners"}]


def test_dry_run_registra_o_pick_que_nao_foi_gravado(motor, gravadas):
    """O ponto inteiro do log. Em dry run `picks_live` fica vazia por
    construcao · esta linha e' a UNICA prova de que o motor teria gerado."""
    motor.setattr(live_pipeline.orchestrator, "observado_da_familia", lambda *a: 5)
    motor.setattr(live_pipeline.orchestrator, "triagem",
                  lambda *a: {"vale": True, "motivo": None, "familias": ["corners"]})
    motor.setattr(live_pipeline.live_odds, "extrair_linhas",
                  lambda *a: [{"familia": "corners"}])
    reprovado = {"market": "Escanteios", "line": "Over 10.5", "direcao": "over",
                 "odd": 2.10, "probability": 0.40, "ev": 0.02, "confidence": 0.50,
                 "live_signal_score": 0.3, "aprovado": False,
                 "motivos_reprovacao": ["EV abaixo do minimo", "convergencia fraca"]}
    aprovado = {"market": "Gols", "line": "Over 2.5", "direcao": "over",
                "odd": 1.90, "probability": 0.61, "ev": 0.16, "confidence": 0.66,
                "live_signal_score": 0.7, "aprovado": True, "motivos_reprovacao": []}
    motor.setattr(live_pipeline.orchestrator, "avaliar", lambda *a: [aprovado, reprovado])
    motor.setattr(live_pipeline.orchestrator, "melhor_candidato", lambda *a: aprovado)

    resumo, relatorio = _rodar()

    assert resumo["decisao"] == "PICK LIVE (dry run)"
    assert relatorio["picks_criados"] and relatorio["picks_criados"][0]["dry_run"]

    pipeline, _, status, _, candidatos, _, contexto = gravadas[0]
    assert (pipeline, status) == (PIPELINE_LIVE, STATUS_AVALIADO)
    assert contexto["dry_run"] is True
    assert contexto["desfecho"] == "pick (dry run)"
    assert contexto["aprovados"] == 1
    assert contexto["requisicoes"] == 4

    escolhido = [c for c in candidatos if c["is_best_pick"]]
    assert [c["line"] for c in escolhido] == ["Over 2.5"]
    # Os DOIS motivos, sem short-circuit: saber que caiu por EV *e* por
    # convergencia e' o que diz qual limiar mexer.
    caiu = [c for c in candidatos if not c["eligible"]][0]
    assert caiu["motivos_reprovacao"] == ["EV abaixo do minimo", "convergencia fraca"]


def test_nenhum_aprovado_tambem_deixa_os_candidatos(motor, gravadas):
    """Rodada que avaliou 3 mercados e reprovou os 3 nao pode virar silencio ·
    e' exatamente a rodada que diz qual gate esta' apertado demais."""
    motor.setattr(live_pipeline.orchestrator, "observado_da_familia", lambda *a: 5)
    motor.setattr(live_pipeline.orchestrator, "triagem",
                  lambda *a: {"vale": True, "motivo": None, "familias": ["corners"]})
    motor.setattr(live_pipeline.live_odds, "extrair_linhas",
                  lambda *a: [{"familia": "corners"}])
    motor.setattr(live_pipeline.orchestrator, "avaliar", lambda *a: [
        {"market": "Escanteios", "line": f"Over {n}", "direcao": "over", "odd": 2.0,
         "probability": 0.48, "ev": -0.04, "confidence": 0.52,
         "live_signal_score": 0.2, "aprovado": False,
         "motivos_reprovacao": ["probabilidade abaixo do piso"]}
        for n in ("9.5", "10.5", "11.5")])
    motor.setattr(live_pipeline.orchestrator, "melhor_candidato", lambda *a: None)

    resumo, _ = _rodar()

    assert resumo["decisao"] == "NO PICK"
    _, _, status, _, candidatos, _, contexto = gravadas[0]
    assert status == STATUS_AVALIADO
    assert contexto["desfecho"] == LIVE_NENHUM_APROVADO
    assert contexto["aprovados"] == 0
    assert len(candidatos) == 3
    assert all(not c["eligible"] for c in candidatos)
