# -*- coding: utf-8 -*-
"""O pick ao vivo na busca do /admin, e o lote que obedece ao filtro da tela.

Os dois defeitos tinham a mesma forma: uma tabela de tradução com um buraco.
`_PICK_TABLES` sem `live` fazia a aba Picks varrer sete produtos e nunca o
oitavo · e `_ids_para_recoletar` sem `filtro` fazia o botão de lote agir sobre
um recorte diferente do que estava na tela.
"""
import pytest

from routers import admin


class TestPickAoVivoNaBusca:
    def test_live_esta_no_mapa_de_tabelas(self):
        """Sem esta linha a busca não varre `picks_live` · era o único produto
        sem tela pra marcar resultado na mão."""
        assert admin._PICK_TABLES["live"][0] == "picks_live"

    def test_colunas_de_time_sao_as_de_picks_live(self):
        """`picks_live` guarda `home_team_name`, não `home_team`. Apontar pra
        coluna errada não some com o tipo: derruba a consulta, o `except`
        engole e o tipo some do mesmo jeito -- que foi como a múltipla ficou
        invisível por meses."""
        _tabela, casa, fora = admin._PICK_TABLES["live"]
        assert (casa, fora) == ("home_team_name", "away_team_name")

    def test_todo_tipo_tem_coluna_de_odd(self):
        """`set-result` calcula profit a partir de `_ODD_COL[tipo]`. Tipo no
        mapa de tabelas e ausente aqui vira KeyError na hora de marcar
        GREEN/RED, que é justamente pra que a busca serve."""
        assert set(admin._PICK_TABLES) <= set(admin._ODD_COL)

    def test_uma_fixture_nao_ganhou_o_live(self):
        """Pendências e descarte de sintéticos leem esta lista. Pick ao vivo
        EXPIRED não tem resultado e não errou nada (ver routers/live_picks.py):
        entrar aqui o listaria como pendência a resolver, que é ruído."""
        assert "live" not in admin._PICK_TABLES_UMA_FIXTURE


class TestFiltroDoLote:
    @pytest.mark.parametrize("chave,esperado", [
        ("faltas",      "home_fouls IS NULL OR away_fouls IS NULL"),
        ("escanteios",  "home_corners IS NULL OR away_corners IS NULL"),
    ])
    def test_familia_vira_predicado(self, chave, esperado):
        assert admin._onde_do_filtro(chave) == f"({esperado})"

    def test_chave_desconhecida_nao_filtra(self):
        """O filtro chega da URL da tela · um typo não pode virar 500, e muito
        menos entrar em SQL por f-string."""
        assert admin._onde_do_filtro("'; DROP TABLE users; --") == ""
        assert admin._onde_do_filtro(None) == ""

    def test_folha_incompleta_e_zeradas_continuam_valendo(self):
        assert admin._onde_do_filtro("folha_incompleta") == admin._FOLHA_INCOMPLETA
        assert admin._SQL_SUSPEITA in admin._onde_do_filtro("zeradas")
