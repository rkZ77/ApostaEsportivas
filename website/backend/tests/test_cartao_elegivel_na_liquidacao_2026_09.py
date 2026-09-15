"""O site liquidava cartão pelo número cru da folha da API.

A regra do cartão elegível é de 10/09/2026: cartão de banco e de comissão
técnica não conta pro mercado, e sem a validação o pick fica PENDENTE. Ela foi
escrita no motor (ai_result_checker_service.get_fixture_result) e nunca chegou
em routers/live.py -- que é quem de fato liquida, porque a varredura é puxada
por visita ao site desde 09/08.

Medido em PROD: o pick VIP #1743 (Cartões Menos de 6.5 @1.83, 11/09) foi
gravado RED com 9 pontos crus -- 7 amarelos mais um vermelho. A contagem válida
da mesma partida dava 6: três cartões tinham ido para quem não estava em campo.
Era GREEN.

Nenhum teste toca banco: `_cartoes_elegiveis` é substituída.
"""
import pytest

from routers import live


@pytest.fixture
def sem_rede(monkeypatch):
    """O `_enrich_leg` real busca fixture e folha na API-Football."""
    monkeypatch.setattr(live, "_fetch_fixture", lambda fid: {
        "fixture": {"status": {"short": "FT"}, "timestamp": 1_700_000_000},
        "goals": {"home": 1, "away": 0},
        "teams": {"home": {"id": 10}, "away": {"id": 20}},
        "league": {"id": 72},
    })
    # A folha CRUA da API: 7 amarelos e 1 vermelho = 9 pontos.
    monkeypatch.setattr(live, "_fetch_stats", lambda fid, status: [])
    monkeypatch.setattr(live, "_parse_stats", lambda *a: (
        {"Yellow Cards": 4, "Red Cards": 1}, {"Yellow Cards": 3, "Red Cards": 0}))


def _leg(monkeypatch, elegiveis):
    monkeypatch.setattr(live, "_cartoes_elegiveis", lambda fid, escopo: elegiveis)
    return live._enrich_leg(1492374, "Cartões Mais/Menos", "Under 6.5",
                            "Fortaleza", "Ceara", 10, 20, 1.83,
                            market_type="cards")


def test_o_pick_1743_era_green(sem_rede, monkeypatch):
    """Contagem válida 6 numa linha Menos de 6.5: GREEN, não RED."""
    leg = _leg(monkeypatch, (6, True))
    assert leg["current_val"] == 6
    assert live._locked_leg_result(leg) == "GREEN"


def test_o_numero_cru_da_folha_nao_liquida_mais(sem_rede, monkeypatch):
    """Sem a correção o contador seria 9 (4+1*2 + 3+0*2) e o pick, RED."""
    leg = _leg(monkeypatch, (6, True))
    assert leg["current_val"] != 9


def test_sem_validacao_o_pick_fica_pendente(sem_rede, monkeypatch):
    """"Ainda não sei quem levou" não é resultado, e também não é anulação."""
    leg = _leg(monkeypatch, (None, False))
    assert leg["cartoes_pendentes"] is True
    assert live._locked_leg_result(leg) is None


def test_cartao_pendente_nao_vira_push_por_falta_de_estatistica(sem_rede, monkeypatch):
    """A anulação de 12h existe pra folha que NUNCA vai sair. A validação de
    cartão sai depois, então anular aqui viraria fábrica de PUSH."""
    leg = _leg(monkeypatch, (None, False))
    leg["kickoff_ts"] = 0  # jogo antiquíssimo: a janela de anulação já passou
    assert live._anulacao_sem_estatistica(leg) is None


def test_mercado_que_nao_e_de_cartao_nao_muda(sem_rede, monkeypatch):
    """A regra é da família cartões e não pode encostar nas outras."""
    monkeypatch.setattr(live, "_parse_stats", lambda *a: (
        {"Corner Kicks": 6}, {"Corner Kicks": 5}))
    monkeypatch.setattr(live, "_cartoes_elegiveis",
                        lambda fid, escopo: pytest.fail("não devia ser chamada"))
    leg = live._enrich_leg(1492374, "Escanteios Mais/Menos", "Under 12.5",
                           "Fortaleza", "Ceara", 10, 20, 1.83,
                           market_type="corners")
    assert leg["current_val"] == 11
    assert leg["cartoes_pendentes"] is False
