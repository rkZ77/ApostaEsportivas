"""Varredura de 2026-10-05, motor por motor.

1. NENHUM MOTOR PUBLICA PICK DE JOGO QUE JA' COMECOU. O filtro era so'
   `status = 'NS'`, que so' muda quando a coleta roda. Entre a coleta e a
   geracao (ou num "Gerar X" clicado a tarde), jogo em andamento seguia NS.
2. ALAVANCAGEM GRAVA market_id. Era o unico produto sem, e por isso sem CLV.
"""
import os

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _fonte(caminho: str) -> str:
    with open(os.path.join(SRC, caminho), encoding="utf-8") as fh:
        return fh.read()


def test_apito_futuro_compara_com_o_relogio_de_brasilia():
    from utils import data_br
    assert "AT TIME ZONE 'America/Sao_Paulo'" in data_br.APITO_FUTURO
    assert f"{data_br.MARGEM_APITO_MINUTOS} minutes" in data_br.APITO_FUTURO


@pytest.mark.parametrize("arquivo", [
    "engine_pipelines/dica_pipeline.py",          # Dica do Dia
    "engine_pipelines/alavancagem_pipeline.py",   # Alavancagem
    "engine_pipelines/faltas_pipeline.py",        # Faltas (Pre Live)
    "engine_pipelines/pick_boost_pipeline.py",    # Pick Boost
    "engine_pipelines/player_stats_pipeline.py",  # Jogador
    "services/fixtures_service.py",               # Premium, Multipla, Bingo
    "capturar_odds.py",                           # coleta de odds
])
def test_todo_motor_pre_jogo_exige_apito_no_futuro(arquivo):
    assert "f.match_datetime > {APITO_FUTURO}" in _fonte(arquivo), arquivo


def test_premium_multipla_e_bingo_passam_pelo_servico_com_a_trava():
    """Os tres nao tem query propria: leem fixture pelo servico compartilhado.
    Foi assim que Multipla e Bingo ficaram de fora da correcao do LIVE em 08/2026."""
    for arquivo, metodo in (("engine_pipelines/vip_pipeline.py", "get_ns_without_suggestions"),
                            ("engine_pipelines/multipla_pipeline.py", "get_fixtures_today"),
                            ("engine_pipelines/bingo_pipeline.py", "get_fixtures_today")):
        assert metodo in _fonte(arquivo), arquivo
    servico = _fonte("services/fixtures_service.py")
    for metodo in ("def get_fixtures_today", "def get_ns_without_suggestions"):
        corpo = servico[servico.index(metodo):]
        corpo = corpo[:corpo.index("return self._format_fixtures")]
        assert "APITO_FUTURO" in corpo, metodo


def test_alavancagem_grava_market_id_por_perna():
    fonte = _fonte("engine_pipelines/alavancagem_pipeline.py")
    assert "ADD COLUMN IF NOT EXISTS market_id_{_n}" in fonte
    assert 'f"market_id_{i}"' in fonte
    assert 'p.get("market_id")' in fonte


def test_ledger_le_market_id_da_alavancagem():
    from services import pick_legs_extractor as ex

    class Cur:
        def __init__(self):
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append(sql)

        def fetchone(self):
            return (1,)          # toda coluna "existe"

        def fetchall(self):
            linha = {f"{c}_{i}": None for i in (1, 2, 3) for c in (
                "fixture_id", "home_team", "away_team", "market", "market_type", "line",
                "odd", "bet_house", "confidence", "prob_real", "reasoning", "market_id")}
            linha.update({"id": 9, "match_date": None, "created_at": None, "ai_review": None,
                          "fixture_id_1": 555, "market_id_1": 45})
            return [linha]

    pernas = ex.fetch_alavancagem_legs(Cur())
    assert pernas[0]["market_id"] == 45


def test_pagina_publica_de_clv_le_o_ledger_e_so_fechamento_perto_do_apito():
    """Lia `closing_odds`, que nenhum processo preenche: a pagina dizia
    'sem odds de fechamento' pra sempre."""
    caminho = os.path.join(SRC, "..", "..", "website", "backend", "routers", "public.py")
    with open(caminho, encoding="utf-8") as fh:
        fonte = fh.read()
    bloco = fonte[fonte.index('@router.get("/market-movement")'):]
    bloco = bloco[:bloco.index("@router.", 10)]
    assert "FROM picks_ledger" in bloco
    assert "closing_min_to_ko IS NOT NULL" in bloco
    assert "JOIN closing_odds" not in bloco
