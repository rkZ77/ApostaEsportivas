"""Bug de 07/10: explanation lia `t["name"]` nos titulares desfalcados, mas o
sinal que os 5 pipelines passam (dossie_da_partida) traz so' o nome, string.
TypeError no _save_pick derrubava o motor no primeiro jogo com titular fora."""
import pytest

from services.pick_engine.explanation import build_explanation


def _candidato(news):
    return {"odd": 1.80, "taxa_real": 0.62, "edge": 0.05, "ev": 0.08, "confidence": 0.7,
            "risco": "MODERADO", "market_name": "Gols", "value_label": "Over 1.5",
            "amostra": 12, "news_raw": news}


@pytest.mark.parametrize("titulares", [
    ["Fulano", "Beltrano"],                                  # dossie_da_partida
    [{"name": "Fulano"}, {"name": "Beltrano"}],              # news_model.injury_signal
])
def test_titulares_desfalcados_nos_dois_formatos(titulares):
    news = {"home": {"titulares_desfalcados": titulares, "outros_desfalcados": []},
            "away": {"titulares_desfalcados": [], "outros_desfalcados": []}}
    riscos = build_explanation(_candidato(news))["risks"]
    assert any("Mandante desfalcado de 2 titular(es)" in r and "Fulano, Beltrano" in r
               for r in riscos)
    assert not any("Visitante desfalcado" in r for r in riscos)
