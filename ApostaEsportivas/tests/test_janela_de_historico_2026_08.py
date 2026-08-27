"""A janela de historico da LIGA tinha ficado pra tras da janela da COPA.

O caminho multi-competicao (copa de clube, selecao, mata-mata) subiu de 15 pra
30 jogos em 2026-08-13, com a razao escrita na propria constante: pool_and_field
fica so' com os jogos do MANDO que o mercado descreve, o que corta o pool a
aproximadamente metade -- com 15 o time chegava a ~7 e nao alcancava
sample_rich_n=8 quase nunca.

A razao valia igual pro caminho de LIGA, e ninguem subiu aquele lado. O
resultado era o motor enxergando bem o que e' raro e enxergando pouco
justamente o que e' comum: pontos corridos, que e' a origem da maioria
esmagadora dos jogos analisados.

O outro achado do mesmo lugar: o caminho de liga nao filtrava STATUS. O
multi-competicao sempre filtrou (FIM_DE_JOGO), entao jogo adiado ou
interrompido com linha gravada entrava so' de um dos lados.

Nada aqui toca banco: le-se o SQL do servico.
"""

import inspect
import re

import pytest

from services.match_stats_service import (
    DEFAULT_LIMIT_LEAGUE,
    DEFAULT_LIMIT_MULTI,
    FIM_DE_JOGO,
    MatchStatsService,
)


def _sql(metodo) -> str:
    """O corpo do metodo, com espaco normalizado."""
    return " ".join(inspect.getsource(metodo).split())


DE_LIGA = ("get_all_matches_full", "get_home_matches", "get_away_matches")


class TestJanelaDaLiga:
    @pytest.mark.parametrize("nome", DE_LIGA)
    def test_le_a_temporada_inteira(self, nome):
        """O recorte ja' e' a propria liga e a propria temporada · o campeonato
        tem comeco e fim, e o time joga de 38 a 46 partidas nele. Cortar em 15
        e' jogar fora o primeiro turno."""
        sql = _sql(getattr(MatchStatsService, nome))
        assert "LIMIT 15" not in sql
        assert "{DEFAULT_LIMIT_LEAGUE}" in sql or f"LIMIT {DEFAULT_LIMIT_LEAGUE}" in sql

    @pytest.mark.parametrize("nome", DE_LIGA)
    def test_filtra_jogo_encerrado(self, nome):
        """Jogo adiado ou interrompido com linha gravada entrava no historico
        com o que estivesse na folha."""
        assert "ms.status IN" in _sql(getattr(MatchStatsService, nome))

    def test_a_janela_da_liga_nao_e_menor_que_a_da_copa(self):
        """Foi exatamente a assimetria que existiu entre 13/08 e 27/08. Ela nao
        pode voltar em silencio: a liga tem MAIS jogo disponivel que a copa, nao
        menos."""
        assert DEFAULT_LIMIT_LEAGUE >= DEFAULT_LIMIT_MULTI

    def test_a_janela_cobre_um_returno_inteiro(self):
        """Pontos corridos de 20 times sao 38 rodadas. Uma janela abaixo disso
        significa que o comeco da temporada nunca e' visto -- e o decaimento
        temporal ja' cuida de jogo velho pesar menos, entao o corte duro nao
        precisa fazer esse trabalho."""
        assert DEFAULT_LIMIT_LEAGUE >= 38


class TestJanelaDaCopa:
    def test_continua_multi_competicao_e_com_status(self):
        """O caminho da copa nao foi tocado · o teste existe pra a correcao do
        lado da liga nao ter mexido nele sem querer."""
        sql = _sql(MatchStatsService.get_last_n_all_competitions)
        assert "ms.league_id = %s" not in sql
        assert "ms.status IN" in sql

    def test_fim_de_jogo_inclui_prorrogacao_e_penaltis(self):
        """AET/PEN sao exatamente os jogos de mata-mata, que e' onde a amostra
        e' curta. Quem decide se o jogo serve pra familia de mercado em questao
        e' stats_model.pool_and_field, porque a folha de um AET cobre 120
        minutos e so' gols tem placar de 90 separado."""
        assert set(re.findall(r"'(\w+)'", FIM_DE_JOGO)) == {"FT", "AET", "PEN"}
