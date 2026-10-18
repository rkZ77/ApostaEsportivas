"""O mesmo árbitro em grafias diferentes tem de virar uma chave só."""
import importlib.util
import os

import pytest

from utils import arbitro
from utils.arbitro import chave_do_arbitro, sql_chave


@pytest.mark.parametrize("nome", [
    "Raphael Claus", "Raphael Claus, Brazil", "  raphael  claus ",
    "RAPHAEL CLAUS", "Raphael Claus,Brazil",
])
def test_grafias_da_mesma_pessoa(nome):
    assert chave_do_arbitro(nome) == "raphael claus"


def test_acento_e_ponto():
    assert chave_do_arbitro("Wilton Pereira Sampaio") == "wilton pereira sampaio"
    assert chave_do_arbitro("Anderson Daronco") == chave_do_arbitro("Ánderson Darônco")
    assert chave_do_arbitro("J. Smith") == "j smith"


def test_abreviacao_nao_vira_nome_inteiro():
    """Juntar pessoas diferentes é pior que deixar a amostra partida."""
    assert chave_do_arbitro("R. Claus") != chave_do_arbitro("Raphael Claus")


@pytest.mark.parametrize("nome", [None, "", " , Brazil"])
def test_sem_nome(nome):
    assert chave_do_arbitro(nome) is None


def test_tabelas_de_acento_alinhadas():
    assert len(arbitro.COM_ACENTO) == len(arbitro.SEM_ACENTO)
    assert all(ord(c) < 128 for c in arbitro.SEM_ACENTO)


def test_sql_sem_porcento_e_imutavel():
    expr = sql_chave("ms.referee")
    assert "%" not in expr and "'" + arbitro.COM_ACENTO + "'" in expr
    assert "split_part(ms.referee, ',', 1)" in expr


def test_copia_do_site_igual():
    caminho = os.path.join(os.path.dirname(__file__), "..", "..",
                           "website", "backend", "arbitro.py")
    spec = importlib.util.spec_from_file_location("_arbitro_site", caminho)
    site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site)
    assert site.COM_ACENTO == arbitro.COM_ACENTO
    assert site.SEM_ACENTO == arbitro.SEM_ACENTO
    assert site.sql_chave("x") == arbitro.sql_chave("x")
    for nome in ("Raphael Claus, Brazil", "Ánderson Darônco", "J. Smith", None):
        assert site.chave_do_arbitro(nome) == arbitro.chave_do_arbitro(nome)


# ── nome completo x nome curto (18/10/2026) ──────────────────────────────────
from utils.arbitro import chaves_equivalentes


def test_nome_curto_junta_com_o_unico_nome_longo():
    conhecidas = ["ramon abatti", "ramon abatti abel", "ramon souza"]
    assert chaves_equivalentes("ramon abatti", conhecidas) == ["ramon abatti", "ramon abatti abel"]
    assert chaves_equivalentes("ramon abatti abel", conhecidas) == ["ramon abatti", "ramon abatti abel"]
    assert chaves_equivalentes("ramon souza", conhecidas) == ["ramon souza"]


def test_nome_curto_ambiguo_nao_junta_ninguem():
    conhecidas = ["paulo cesar", "paulo cesar zanovelli", "paulo cesar oliveira"]
    assert chaves_equivalentes("paulo cesar", conhecidas) == ["paulo cesar"]
    assert chaves_equivalentes("paulo cesar zanovelli", conhecidas) == ["paulo cesar zanovelli"]


def test_uma_palavra_so_e_abreviacao_nao_juntam():
    assert chaves_equivalentes("ramon", ["ramon", "ramon abatti"]) == ["ramon"]
    assert chaves_equivalentes("r abatti", ["r abatti", "ramon abatti"]) == ["r abatti"]
    assert chaves_equivalentes(None, ["x y"]) == []


def test_copia_do_site_junta_igual():
    caminho = os.path.join(os.path.dirname(__file__), "..", "..",
                           "website", "backend", "arbitro.py")
    spec = importlib.util.spec_from_file_location("_arbitro_site2", caminho)
    site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site)
    for alvo, conhecidas in (("ramon abatti", ["ramon abatti abel"]),
                             ("paulo cesar", ["paulo cesar a", "paulo cesar b"])):
        assert site.chaves_equivalentes(alvo, conhecidas) == chaves_equivalentes(alvo, conhecidas)
    assert site.sql_candidatas("x") == arbitro.sql_candidatas("x")


def test_motor_le_as_duas_fontes_com_os_parametros_na_ordem():
    """18/10/2026: a media do arbitro no motor soma arbitro_partidas (outras
    ligas do pais). Rodado contra Postgres 16 local com o caso do Ramon Abatti
    (4 jogos -> 18). Aqui so' a forma: as duas fontes e o numero de %s."""
    from services import referee_stats_service as rss
    assert "arbitro_partidas" in rss.SQL_COM_EXTRAS and "arbitro_partidas" not in rss.SQL_SO_BASE
    assert rss.SQL_COM_EXTRAS.count("%s") == 6      # base, extra, agregado
    assert rss.SQL_SO_BASE.count("%s") == 4
    assert "ANY(%s)" in rss.SQL_COM_EXTRAS
